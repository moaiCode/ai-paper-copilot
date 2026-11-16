#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读检查科研工作流；不会安装软件、改偏好或提交 PDF。

环境、配置与实测是不同状态。例如发现 MinerU Token 只表示已配置，
不会为验证 Token 而擅自上传文献。JSON 报告不包含凭据或文献内容。
"""

import argparse
import configparser
import http.client
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


def zotero_profile():
    """只检查标准 profile 注册表；多 profile 无默认时不随意挑选。"""
    home = Path.home()
    roots = [home / "Library/Application Support/Zotero", home / ".zotero/zotero"]
    for root in roots:
        registry = root / "profiles.ini"
        if not registry.is_file():
            continue
        parser = configparser.ConfigParser()
        parser.read(str(registry), encoding="utf-8")
        profiles = []
        for section in parser.sections():
            if not section.startswith("Profile") or not parser.has_option(section, "Path"):
                continue
            entry = Path(parser.get(section, "Path"))
            if parser.get(section, "IsRelative", fallback="1") == "1":
                entry = root / entry
            if parser.get(section, "Default", fallback="0") == "1":
                return entry
            profiles.append(entry)
        if len(profiles) == 1:
            return profiles[0]
    return None


PREF_PREFIX = "extensions.zotero.llmforzotero."
MINERU_MODE_PREF = PREF_PREFIX + "mineruMode"
AUTO_PARSE_PREF = PREF_PREFIX + "mineruGlobalAutoParse"
VAULT_PATH_PREF = PREF_PREFIX + "obsidianVaultPath"
TARGET_FOLDER_PREF = PREF_PREFIX + "obsidianTargetFolder"
ATTACHMENTS_FOLDER_PREF = PREF_PREFIX + "obsidianAttachmentsFolder"
ALLOWED_PREFS = {
    "extensions.zotero.dataDir", "extensions.zotero.useDataDir",
    MINERU_MODE_PREF, AUTO_PARSE_PREF, VAULT_PATH_PREF,
    TARGET_FOLDER_PREF, ATTACHMENTS_FOLDER_PREF,
}
# 显式值损坏时保留“无效”状态，不能悄悄回退默认并报告已配置。
INVALID_PREF = object()


def parse_selected_prefs(text, function_name="user_pref"):
    """解析固定偏好键的 JSON 标量；不执行 JavaScript，也不返回 Token。

    用户 prefs.js 与插件默认 prefs.js 分别使用 user_pref/pref。只收集
    白名单中的键；即使其他行含凭据，也不会进入返回值或诊断报告。
    """
    result = {}
    pattern = re.compile(r'^\s*' + re.escape(function_name) + r'\("([^"\n]+)",\s*(.*?)\);\s*$')
    for line in text.splitlines():
        match = pattern.match(line)
        if match and match.group(1) in ALLOWED_PREFS:
            try:
                result[match.group(1)] = json.loads(match.group(2))
            except ValueError:
                result[match.group(1)] = INVALID_PREF
    return result


def selected_prefs(path):
    """只返回用于状态判断的白名单偏好，不暴露完整文件与秘密字段。"""
    if not path or not path.is_file():
        return {}
    return parse_selected_prefs(path.read_text(encoding="utf-8"))


def installed_default_prefs(addon):
    """只从已安装插件的本地文件读取默认值；失败时返回未知而非猜默认。

    llm-for-zotero 3.9.17 的默认偏好位于 XPI 根 prefs.js；同时兼容
    常规的 defaults/preferences/prefs.js 与解包扩展目录。不下载插件、
    不读取存储令牌的文件，也不把解析失败的原始内容写进错误消息。
    """
    if not isinstance(addon, dict) or not isinstance(addon.get("path"), str):
        return {}
    path = Path(addon["path"]).expanduser()
    names = ("prefs.js", "defaults/preferences/prefs.js")
    try:
        if path.is_dir():
            values = {}
            for name in names:
                candidate = path / name
                if candidate.is_file() and candidate.stat().st_size <= 1024 * 1024:
                    values.update(parse_selected_prefs(candidate.read_text(encoding="utf-8"), "pref"))
            return values
        if path.is_file() and zipfile.is_zipfile(path):
            values = {}
            with zipfile.ZipFile(path) as archive:
                for name in names:
                    try:
                        entry = archive.getinfo(name)
                    except KeyError:
                        continue
                    if entry.file_size <= 1024 * 1024:
                        values.update(parse_selected_prefs(archive.read(entry).decode("utf-8"), "pref"))
            return values
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile):
        pass
    return {}


def effective_pref(explicit, defaults, key):
    """返回配置值与来源；显式无效值绝不能被默认值覆盖。"""
    if key in explicit:
        return explicit[key], "explicit"
    if key in defaults:
        return defaults[key], "installed_default"
    return None, "unknown"


def validate_service_url(value, label, local_only=False):
    """拒绝凭据、查询串和控制字符，错误只输出字段名，不回显秘密值。"""
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(label + " 必须是有效的无凭据服务地址")
    try:
        parsed = urllib.parse.urlsplit(value)
        # 读取 port 会验证诸如 :abc 的畸形端口，避免稍后进入 urllib traceback。
        parsed.port
    except ValueError:
        raise ValueError(label + " 地址格式无效") from None
    schemes = ("http",) if local_only else ("http", "https")
    if (parsed.scheme not in schemes or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError(label + " 必须是无凭据、查询串和片段的服务地址")
    if local_only and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(label + " 必须使用本机 http 地址")
    return value


def probe(url):
    """只接收小型健康响应；不用密钥、不跟随到其他主机的重定向。"""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(url, timeout=3) as response:
            response.read(1024)
            return response.status == 200
    except (OSError, urllib.error.URLError, ValueError, http.client.HTTPException):
        return False


def inspect(vault):
    checks = []
    def add(name, status, message, required=False, **details):
        checks.append(dict(name=name, status=status, message=message, required=required, **details))

    profile_path = vault / "research-profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
    if not isinstance(profile, dict):
        raise ValueError("research-profile.json 必须为对象")
    add("研究配置", "configured" if profile else "not_configured", str(profile_path), True)
    add("Vault 指令", "configured" if (vault / "AGENTS.md").is_file() else "missing",
        "根 AGENTS.md 存在不代表当前会话一定加载；请以 Vault 为主文件夹。", True)
    try:
        import yaml  # 只验证依赖，不在 doctor 中解析用户笔记。
        add("PyYAML", "verified", "安全 YAML 解析器 " + yaml.__version__, True)
    except ImportError:
        add("PyYAML", "missing", "在虚拟环境中安装 skill 的 requirements.txt。", True)

    for app in ("Zotero", "Obsidian"):
        exists = (Path("/Applications") / (app + ".app")).is_dir()
        add(app, "configured" if exists else "unknown", "检测 macOS /Applications 安装目录。", True)
    zotero = profile.get("zotero", {})
    if not isinstance(zotero, dict):
        raise ValueError("配置 zotero 必须为对象")
    base = validate_service_url(zotero.get("api_base_url", "http://127.0.0.1:23119/api"),
                                "zotero.api_base_url", local_only=True)
    scope = zotero.get("library_scope", "users/0")
    if not isinstance(scope, str) or not re.fullmatch(r"(?:users|groups)/[0-9]+", scope):
        raise ValueError("zotero.library_scope 格式应为 users/0 或 groups/数字")
    ready = probe(base.rstrip("/") + "/" + scope + "/items?limit=1")
    add("Zotero 本地 API", "verified" if ready else "not_configured",
        "只读请求成功；未输出文献内容。" if ready else "启动 Zotero 并在高级设置启用本地通信。", True)

    profile_dir = zotero_profile()
    prefs = selected_prefs(profile_dir / "prefs.js" if profile_dir else None)
    addons = []
    extension_file = profile_dir / "extensions.json" if profile_dir else None
    if extension_file and extension_file.is_file():
        extension_data = json.loads(extension_file.read_text(encoding="utf-8"))
        if not isinstance(extension_data, dict) or not isinstance(extension_data.get("addons", []), list):
            raise ValueError("Zotero extensions.json 的 addons 必须为数组")
        addons = extension_data.get("addons", [])
        if any(not isinstance(entry, dict) for entry in addons):
            raise ValueError("Zotero extensions.json 的插件条目必须为对象")
    for name, identifier in (("Better BibTeX", "better-bibtex@iris-advies.com"),
                             ("LLM-for-Zotero", "zotero-llm@github.com.yilewang")):
        installed = next((entry for entry in addons if entry.get("id") == identifier), None)
        status = "configured" if installed and installed.get("active") else "missing"
        message = "已启用 " + str(installed.get("version")) if status == "configured" else "未检测到已启用的插件；核对 Zotero 当前 profile。"
        add(name, status, message, True)

    mineru = profile.get("mineru", {})
    if not isinstance(mineru, dict):
        raise ValueError("配置 mineru 必须为对象")
    backend = mineru.get("backend")
    if backend not in (None, "cloud", "local"):
        raise ValueError("mineru.backend 只能是 null、cloud 或 local")
    add("MinerU 后端选择", "configured" if backend else "not_configured",
        backend or "首次使用时选择云端或自托管；目前不会上传。", True)
    llm_addon = next((entry for entry in addons if entry.get("id") == "zotero-llm@github.com.yilewang"), None)
    defaults = installed_default_prefs(llm_addon)

    # profile 是用户希望的设置；插件有效值来自显式偏好或已安装版本默认。
    # 两者必须分开报告，避免把文档写成 cloud/false 当成实际已经设置成功。
    actual_mode, mode_source = effective_pref(prefs, defaults, MINERU_MODE_PREF)
    mode_known = isinstance(actual_mode, str) and actual_mode in ("cloud", "local")
    if mode_source == "unknown":
        mode_status, mode_message = "unknown", "无法读取插件后端；未据此假定已采用 profile 设置。"
    elif not mode_known:
        mode_status, mode_message = "invalid", "插件后端值无效；未回显原始偏好值，请在插件中核对。"
    elif backend is not None and actual_mode != backend:
        mode_status, mode_message = "mismatch", "插件有效后端与 research-profile.json 不一致，未自动修改。"
    else:
        mode_status, mode_message = "configured", "已读取插件有效后端；这不表示服务连通或解析已实测。"
    add("MinerU 插件有效后端", mode_status, mode_message, True,
        preference_source=mode_source, actual_value=actual_mode if mode_known else None,
        expected_value=backend)

    expected_auto = mineru.get("automatic_parse")
    auto_intent_status = ("configured" if isinstance(expected_auto, bool)
                          else "not_configured" if "automatic_parse" not in mineru else "invalid")
    add("MinerU 自动解析意图", auto_intent_status,
        "profile 已明确自动解析意图。" if auto_intent_status == "configured" else
        "请在 profile 中明确设置布尔值 automatic_parse；doctor 不替用户选择。", True,
        expected_value=expected_auto if isinstance(expected_auto, bool) else None)
    actual_auto, auto_source = effective_pref(prefs, defaults, AUTO_PARSE_PREF)
    if auto_source == "unknown":
        auto_status, auto_message = "unknown", "无法读取插件全局自动解析状态；不能假定它处于关闭状态。"
    elif not isinstance(actual_auto, bool):
        auto_status, auto_message = "invalid", "插件自动解析值不是布尔值；未回显原始偏好值。"
    elif isinstance(expected_auto, bool) and actual_auto != expected_auto:
        auto_status, auto_message = "mismatch", "插件全局自动解析与 profile 意图不一致，需用户核对；未自动修改。"
    else:
        auto_status, auto_message = "configured", "已读取插件全局自动解析的有效配置；不代表附件级策略或上传已获授权。"
    add("MinerU 插件全局自动解析", auto_status, auto_message, True,
        preference_source=auto_source,
        actual_value=actual_auto if isinstance(actual_auto, bool) else None,
        expected_value=expected_auto if isinstance(expected_auto, bool) else None)

    # 只比较路径是否匹配，不输出插件内原始字符串；避免误填的敏感值被回显。
    export_vault, vault_source = effective_pref(prefs, defaults, VAULT_PATH_PREF)
    if vault_source == "unknown":
        export_status, export_message = "unknown", "未读取到插件笔记 Vault 设置；此项不影响直接阅读本地材料。"
    elif not isinstance(export_vault, str):
        export_status, export_message = "invalid", "插件笔记 Vault 路径类型无效。"
    elif not export_vault.strip():
        export_status, export_message = "not_configured", "插件尚未绑定笔记 Vault。"
    else:
        try:
            matches = Path(export_vault).expanduser().resolve() == vault.resolve()
            export_status = "configured" if matches else "mismatch"
            export_message = "插件笔记 Vault 与本次 Vault 匹配。" if matches else "插件笔记导出指向其他 Vault；本次未改设置。"
        except (OSError, ValueError):
            export_status, export_message = "invalid", "插件笔记 Vault 路径无法解析。"
    add("插件笔记 Vault", export_status, export_message, preference_source=vault_source)

    if backend == "cloud":
        add("MinerU 云连通性", "unknown", "由用户在插件中填写 Token 并执行测试；doctor 不读取 Token、不调用付费解析。")
    elif backend == "local":
        local_url = validate_service_url(mineru.get("local_url", "http://127.0.0.1:8000"), "mineru.local_url")
        health = probe(local_url.rstrip("/") + "/health")
        add("MinerU 自托管健康检查", "verified" if health else "unknown",
            "健康端点成功；未提交 PDF。" if health else "未确认 /health；不同版本 API 仍需单篇解析验证。")
    data_dir = zotero.get("data_dir")
    if not data_dir:
        # Zotero 可能保留旧自定义目录；只有 useDataDir=true 时它才是有效目录。
        data_dir = (prefs.get("extensions.zotero.dataDir")
                    if prefs.get("extensions.zotero.useDataDir") is True else None)
        data_dir = data_dir or str(Path.home() / "Zotero")
    if not isinstance(data_dir, str):
        raise ValueError("zotero.data_dir 必须为路径字符串或 null")
    cache = Path(data_dir).expanduser() / "llm-for-zotero-mineru"
    add("MinerU 缓存", "configured" if cache.is_dir() else "not_configured",
        "缓存目录存在；内容质量和对应关系尚未据此验证。" if cache.is_dir() else "尚无缓存目录；首次解析成功后再归档。")
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    try:
        if not vault.is_dir():
            raise ValueError("Vault 不存在")
        checks = inspect(vault)
        incomplete = [item for item in checks if item["required"] and item["status"] not in ("configured", "verified")]
        report = dict(status="needs_setup" if incomplete else "baseline_ready", vault=str(vault),
                      checks=checks, workflow_verified=False,
                      message="baseline_ready 仅表示基础项可用；真实阅读/解析链路需另行验收。")
        code = 1 if incomplete else 0
    except (OSError, ValueError, TypeError) as exc:
        report, code = dict(status="error", message=str(exc)), 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif "checks" in report:
        for item in report["checks"]:
            print("[{status}] {name}: {message}".format(**item))
        print(report["status"] + "；" + report["message"])
    else:
        print(report["message"], file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
