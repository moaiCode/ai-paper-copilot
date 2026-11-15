#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读 llm-for-zotero 的单篇 MinerU 缓存，导出可迁移的全文资料包。

本脚本不调用解析服务、不上传文件、不修改 Zotero 缓存。原文 Markdown 保持
逐字节不变；图片通过 assets.md 导航，而不是猜测它们应该插入原文的位置。
退出码：0=导出/预览成功（可能有警告），1=内容或冲突错误，2=参数/资源错误。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


EXPORTER = "ai-paper-copilot/export_fulltext"
SCHEMA_VERSION = 1
KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
SCOPE_RE = re.compile(r"^(?:users/(?:0|[1-9][0-9]*)|groups/[1-9][0-9]*)$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
CACHE_SUFFIXES = IMAGE_SUFFIXES | {".md", ".json"}
RESERVED_NAMES = {"source.pdf", "assets.md", "provenance.json"}


class ExportError(Exception):
    """将可预期错误变成稳定的机器可读 code，避免向用户倾倒 traceback。"""

    def __init__(self, code, message, exit_code=1):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def issue(code, message, level="WARN"):
    return {"level": level, "code": code, "message": message}


def within(path, root):
    """兼容系统 Python 3.8，不依赖较新版本的 Path.is_relative_to。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ExportError("INVALID_JSON", f"JSON 无法解析：{path.name}：{exc}")


def safe_relative(value, label):
    """配置路径必须是 Vault 内的相对路径，不接受 ..、绝对路径或平台分隔歧义。"""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ExportError("UNSAFE_PATH", f"{label} 必须是非空的相对路径")
    path = Path(value)
    if path.is_absolute() or any(part in (".", "..") for part in value.split("/")):
        raise ExportError("UNSAFE_PATH", f"{label} 禁止绝对路径和 . / .. 路径段")
    if any(ord(char) < 32 for char in value):
        raise ExportError("UNSAFE_PATH", f"{label} 包含控制字符")
    return path


def ensure_no_symlink_between(root, target):
    """先检查词法路径的每一段，再 resolve，防止写入时跟随已有符号链接。"""
    if not within(target, root):
        raise ExportError("UNSAFE_OUTPUT", "输出目录超出 Vault")
    cursor = root
    for part in target.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ExportError("OUTPUT_SYMLINK", f"输出路径包含符号链接：{cursor}")
    if not within(target.resolve(), root):
        raise ExportError("UNSAFE_OUTPUT", "输出目录解析后超出 Vault")


def cache_inventory(cache):
    """只归档文本、结构 JSON 和图像；扫描时拒绝缓存中任何符号链接/特殊文件。

    digest 按相对路径和内容计算，不依赖 mtime。这样复制或恢复的等价缓存仍能
    幂等识别，同时数字 attachmentId 从不被用作跨库身份。
    """
    files = []
    for directory, dirs, names in os.walk(str(cache), followlinks=False):
        for name in sorted(dirs + names):
            path = Path(directory) / name
            rel = path.relative_to(cache).as_posix()
            if path.is_symlink():
                raise ExportError("CACHE_SYMLINK", f"缓存包含符号链接，未读取：{rel}")
            mode = path.stat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ExportError("CACHE_SPECIAL_FILE", f"缓存包含非常规文件：{rel}")
            safe_relative(rel, "缓存文件路径")
            if rel in RESERVED_NAMES:
                raise ExportError("RESERVED_CACHE_NAME", f"缓存文件与导出文件名冲突：{rel}")
            if path.suffix.lower() in CACHE_SUFFIXES:
                files.append({"path": rel, "sha256": sha256_file(path), "size": path.stat().st_size})
    files.sort(key=lambda row: row["path"])
    digest = hashlib.sha256()
    for row in files:
        # 用 JSON 编码边界，避免文件名/内容哈希的简单连接产生歧义。
        digest.update(json.dumps([row["path"], row["sha256"]], ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    return files, digest.hexdigest()


def resolve_key(explicit, source, field, required=False):
    if explicit and source and explicit != source:
        raise ExportError("IDENTITY_CONFLICT", f"显式身份与 _llm_source.json 的 {field} 不一致")
    value = explicit or source
    if value is not None and (not isinstance(value, str) or not KEY_RE.fullmatch(value)):
        raise ExportError("INVALID_KEY", f"{field} 应为 8 位大写字母数字")
    if required and not value:
        raise ExportError("MISSING_IDENTITY", f"缺少 {field}，请检查来源或显式提供对应 key")
    return value


def extract_page_mapping(cache, files, issues):
    """只把明确的 page_idx 转为物理页，不解释含义不明的通用 page 字段。

    保存源 JSON 路径和指针，供人或 Agent 回看；这里建立的是转换器位置映射，
    不是 PDF 内容已核验的声明，也不等于印刷页码。
    """
    entries = []

    def walk(value, source_file, pointer=""):
        if isinstance(value, dict):
            index = value.get("page_idx")
            if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
                row = {"source_file": source_file, "json_pointer": pointer or "/",
                       "page_idx": index, "pdf_physical_page": index + 1}
                for name in ("type", "img_path"):
                    if isinstance(value.get(name), str):
                        row[name] = value[name]
                entries.append(row)
            elif "page_idx" in value:
                issues.append(issue("INVALID_PAGE_INDEX", f"{source_file}{pointer} 的 page_idx 无效，未生成页码"))
            for key, child in value.items():
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                walk(child, source_file, pointer + "/" + escaped)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, source_file, pointer + "/" + str(index))

    for row in files:
        name = Path(row["path"]).name
        if name == "content_list.json" or name.endswith("_content_list.json"):
            try:
                walk(read_json(cache / row["path"]), row["path"])
            except ExportError as exc:
                issues.append(issue("PAGE_SOURCE_INVALID", str(exc)))
    if not entries:
        issues.append(issue("PAGE_MAPPING_MISSING", "无可用 content_list.page_idx；保留原始 manifest，但不得从 Markdown 顺序猜页码"))
    return {"status": "available" if entries else "missing",
            "basis": "MinerU content_list.page_idx（0 基）；PDF 物理页 = page_idx + 1；印刷页码未核验",
            "verified_against_pdf": False, "entries": entries}


def markdown_image_targets(text):
    """识别常用 Markdown、HTML 与 Obsidian 图像引用，不充当完整 Markdown 解析器。"""
    targets = []
    pattern = r"!\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)(?:\s+[^)\n]*)?\)"
    for match in re.finditer(pattern, text):
        targets.append(match.group(1).strip("<>"))
    for match in re.finditer(r'<img\b[^>]*\bsrc=[\"\']([^\"\']+)[\"\']', text, re.IGNORECASE):
        targets.append(match.group(1))
    for match in re.finditer(r"!\[\[([^\]\n]+)\]\]", text):
        targets.append(match.group(1).split("|", 1)[0])
    return list(dict.fromkeys(targets))


def image_records(cache, files, text, page_mapping, issues):
    images = [{"path": row["path"], "sha256": row["sha256"], "referenced_in_markdown": False}
              for row in files if Path(row["path"]).suffix.lower() in IMAGE_SUFFIXES]
    image_map = {row["path"]: row for row in images}
    known_files = {row["path"] for row in files}
    for target in markdown_image_targets(text):
        try:
            url = urlsplit(target)
        except ValueError:
            issues.append(issue("INVALID_IMAGE_REFERENCE", "图像 URL 无法解析，未读取：" + target))
            continue
        if url.scheme == "data":
            continue
        if url.scheme or url.netloc:
            issues.append(issue("EXTERNAL_IMAGE", f"原文包含外部图像，未下载，资料包未保证离线完整：{target}"))
            continue
        relative = unquote(url.path)
        candidate = cache / relative
        try:
            resolved = candidate.resolve()
        except (ValueError, OSError):
            issues.append(issue("INVALID_IMAGE_REFERENCE", "图像路径无效，未读取：" + target))
            continue
        if Path(relative).is_absolute() or not within(resolved, cache):
            issues.append(issue("IMAGE_OUTSIDE_CACHE", f"图像引用超出缓存，未读取：{target}"))
            continue
        # 允许 URL 中出现 a/../b，但规范到真实路径后仍须属于已归档选择集。
        normalized = resolved.relative_to(cache).as_posix()
        if normalized not in known_files:
            issues.append(issue("IMAGE_MISSING", f"图像不存在或未归档：{target}"))
        elif normalized in image_map:
            image_map[normalized]["referenced_in_markdown"] = True
    for mapping in page_mapping["entries"]:
        image_path = mapping.get("img_path")
        if isinstance(image_path, str):
            try:
                parsed = urlsplit(image_path)
            except ValueError:
                continue
            if not parsed.scheme and not parsed.netloc:
                candidate = cache / unquote(parsed.path)
                try:
                    resolved = candidate.resolve()
                except (ValueError, OSError):
                    continue
                if not within(resolved, cache):
                    continue
                normalized = resolved.relative_to(cache).as_posix()
                if normalized in image_map:
                    image_map[normalized].setdefault("locations", []).append({
                        "pdf_physical_page": mapping["pdf_physical_page"],
                        "source_file": mapping["source_file"],
                        "json_pointer": mapping["json_pointer"]})
    if not images:
        issues.append(issue("NO_IMAGES", "缓存没有图像文件；若论文有图，需在原 PDF 核查，不代表论文没有图"))
    return images


def assets_markdown(images, page_mapping):
    lines = ["# 全文资料包：图像与定位导航", "",
             "原文 `full.md` 保持转换产物不变；以下图像未按推测插回原文。", "",
             "[原始 PDF](source.pdf) · [全文 Markdown](full.md) · [来源清单](provenance.json)", "",
             "页位置来自转换器，尚未逐项核对 PDF；物理页与印刷页码可能不同。", ""]
    if page_mapping["status"] == "missing":
        lines.extend(["> 当前缺少明确的页码映射，请回原 PDF 定位。", ""])
    for row in images:
        label = row["path"].replace("[", "\\[").replace("]", "\\]")
        pages = sorted({loc["pdf_physical_page"] for loc in row.get("locations", [])})
        location = "PDF 物理页 " + ", ".join(map(str, pages)) if pages else "页位置未提供"
        lines.extend([f"## {label}", "", location, "",
                      f"![{label}]({quote(row['path'], safe='/')})", ""])
    if not images:
        lines.append("未归档图像文件；请核查原始 PDF。")
    return "\n".join(lines) + "\n"


def existing_package(target, identity, fingerprints):
    """确认目标确为本脚本生成；只有清单中的文件可在 --replace 时被替换。"""
    if not target.exists():
        return None, False
    if (target / "provenance.json").is_symlink():
        raise ExportError("TARGET_SYMLINK", "已有包的来源清单是符号链接，未读取或覆盖")
    if not target.is_dir() or target.is_symlink() or not (target / "provenance.json").is_file():
        raise ExportError("UNOWNED_TARGET", "目标已存在但不是本脚本生成的资料包，未覆盖")
    data = read_json(target / "provenance.json")
    if not isinstance(data, dict) or data.get("exporter") != EXPORTER:
        raise ExportError("UNOWNED_TARGET", "目标缺少本导出器身份标记，未覆盖")
    if any(data.get(key) != value for key, value in identity.items()):
        raise ExportError("TARGET_IDENTITY_CONFLICT", "已有包的文献/附件身份不同，未覆盖")
    inventory = data.get("files")
    if not isinstance(inventory, list):
        raise ExportError("UNOWNED_TARGET", "已有包缺少有效文件清单，未覆盖")
    expected = {}
    for row in inventory:
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
            raise ExportError("UNOWNED_TARGET", "已有包文件清单无效，未覆盖")
        rel = safe_relative(row.get("path"), "已有包文件清单").as_posix()
        expected[rel] = row["sha256"]
    actual = set()
    intact = True
    for directory, dirs, names in os.walk(str(target), followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise ExportError("TARGET_SYMLINK", "已有包包含符号链接，未覆盖")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ExportError("UNOWNED_TARGET", "已有包含非常规文件，未覆盖")
            rel = path.relative_to(target).as_posix()
            if rel == "provenance.json":
                continue
            actual.add(rel)
            if rel in expected and sha256_file(path) != expected[rel]:
                intact = False
    extras = actual - set(expected)
    if extras:
        raise ExportError("UNOWNED_TARGET_FILES", "已有包有清单外文件，未覆盖：" + ", ".join(sorted(extras)))
    intact = intact and actual == set(expected)
    if not isinstance(data.get("source_pdf"), dict) or not isinstance(data.get("converter"), dict):
        raise ExportError("UNOWNED_TARGET", "已有包的来源或转换器清单无效，未覆盖")
    same = (data.get("cache_sha256") == fingerprints["cache_sha256"]
            and data["source_pdf"].get("sha256") == fingerprints["source_sha256"]
            and data["converter"].get("version") == fingerprints["converter_version"])
    return data, same and intact


def export(args):
    issues = []
    vault = Path(args.vault).expanduser().resolve()
    cache_arg = Path(args.cache_dir).expanduser().absolute()
    if not vault.is_dir():
        raise ExportError("VAULT_MISSING", f"Vault 不存在：{vault}", 2)
    if cache_arg.is_symlink():
        raise ExportError("CACHE_SYMLINK", "缓存根目录不能是符号链接")
    cache = cache_arg.resolve()
    source = Path(args.source_pdf).expanduser().resolve()
    if not cache.is_dir():
        raise ExportError("CACHE_MISSING", f"单篇缓存目录不存在：{cache}", 2)
    if not source.is_file():
        raise ExportError("PDF_MISSING", f"原 PDF 不存在：{source}", 2)
    with source.open("rb") as stream:
        if b"%PDF-" not in stream.read(1024):
            raise ExportError("INVALID_PDF", "原文件没有 PDF 文件头，未导出")
    if not SCOPE_RE.fullmatch(args.library_scope):
        raise ExportError("INVALID_SCOPE", "library-scope 应为 users/0、users/<数字ID> 或 groups/<正整数ID>")
    files, cache_hash = cache_inventory(cache)
    if not (cache / "full.md").is_file():
        raise ExportError("FULLTEXT_MISSING", "缓存缺少 full.md；请先在插件中完成该附件的解析", 2)
    try:
        text = (cache / "full.md").read_text(encoding="utf-8")
    except UnicodeError:
        raise ExportError("FULLTEXT_ENCODING", "full.md 不是有效 UTF-8 文本")
    if not text.strip():
        raise ExportError("FULLTEXT_EMPTY", "full.md 为空，未导出")
    provenance_path = cache / "_llm_source.json"
    provenance = read_json(provenance_path) if provenance_path.is_file() else {}
    if not isinstance(provenance, dict):
        raise ExportError("INVALID_SOURCE_METADATA", "_llm_source.json 应为 JSON 对象")
    if not provenance_path.is_file():
        issues.append(issue("SOURCE_METADATA_MISSING", "缓存没有 _llm_source.json；采用显式身份，需人工核对原 PDF 与附件对应关系"))
    parent_key = resolve_key(args.parent_key, provenance.get("parentItemKey"), "parentItemKey")
    attachment_key = resolve_key(args.attachment_key, provenance.get("attachmentKey"), "attachmentKey", required=True)
    if parent_key is None:
        issues.append(issue("PARENT_IDENTITY_MISSING", "尚未绑定 Zotero 父条目，只能作为临时全文资料；正式入库前补齐身份"))
    fulltext_dir = "03fulltext"
    profile_path = vault / "research-profile.json"
    if profile_path.is_file():
        profile = read_json(profile_path)
        if not isinstance(profile, dict) or not isinstance(profile.get("paths", {}), dict):
            raise ExportError("INVALID_PROFILE", "research-profile.json 及 paths 必须是 JSON 对象")
        fulltext_dir = profile.get("paths", {}).get("fulltext", fulltext_dir)
    root = vault / safe_relative(fulltext_dir, "paths.fulltext")
    target = root / args.library_scope / attachment_key
    ensure_no_symlink_between(vault, target)
    if within(target, cache) or within(cache, target) or within(source, target):
        raise ExportError("SOURCE_OUTPUT_OVERLAP", "输出目录与只读源缓存/PDF 重叠，未导出")
    source_hash = sha256_file(source)
    mapping = extract_page_mapping(cache, files, issues)
    images = image_records(cache, files, text, mapping, issues)
    identity = {"library_scope": args.library_scope, "zotero_key": parent_key, "pdf_key": attachment_key}
    fingerprints = {"cache_sha256": cache_hash, "source_sha256": source_hash,
                    "converter_version": args.converter_version}
    previous, unchanged = existing_package(target, identity, fingerprints)
    result = {"status": "unchanged" if unchanged else "dry_run" if args.dry_run else "replaced" if previous else "created",
              "output": str(target), "fulltext_path": (target / "full.md").relative_to(vault).as_posix(),
              "issues": issues, "quality_verified": False,
              "planned_action": "none" if unchanged else "replace" if previous else "create"}
    if unchanged:
        return result
    if args.dry_run:
        if previous and not args.replace:
            issues.append(issue("REPLACE_REQUIRED", "已有派生包将发生变化；本次仅预览，实际替换需 --replace"))
        return result
    if previous and not args.replace:
        raise ExportError("PACKAGE_CHANGED", "已有包与当前源或配置不同；先查看差异，再使用 --replace 替换派生资料包")

    # 预览分支到此已返回；只有正式执行才创建目录、锁和阶段资料包。
    target.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_between(vault, target)
    lock = target.parent / ("." + attachment_key + ".export-lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise ExportError("EXPORT_LOCKED", f"另一次导出可能正在运行；确认后处理锁目录：{lock}")
    stage = None
    backup = None
    try:
        # 在锁内重新确认目标，避免同一脚本的并发导出覆盖已变更的包。
        locked_previous, locked_unchanged = existing_package(target, identity, fingerprints)
        if locked_unchanged:
            result.update(status="unchanged", planned_action="none")
            return result
        if locked_previous and not args.replace:
            raise ExportError("PACKAGE_CHANGED", "锁定后发现目标已有不同内容，未覆盖")
        stage = Path(tempfile.mkdtemp(prefix="." + attachment_key + ".export-", dir=str(target.parent)))
        generated_files = []
        for row in files:
            src = cache / row["path"]
            ensure_no_symlink_between(cache, src)
            if src.is_symlink():
                raise ExportError("CACHE_CHANGED", "导出过程中缓存变成符号链接，已停止")
            destination = stage / row["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(src), str(destination))
            if sha256_file(destination) != row["sha256"]:
                raise ExportError("CACHE_CHANGED", "导出过程中源缓存内容发生变化，旧包已保留，请重试")
            generated_files.append({"path": row["path"], "sha256": row["sha256"]})
        shutil.copyfile(str(source), str(stage / "source.pdf"))
        if sha256_file(stage / "source.pdf") != source_hash:
            raise ExportError("PDF_CHANGED", "导出过程中原 PDF 发生变化，旧包已保留，请重试")
        generated_files.append({"path": "source.pdf", "sha256": source_hash})
        (stage / "assets.md").write_text(assets_markdown(images, mapping), encoding="utf-8")
        generated_files.append({"path": "assets.md", "sha256": sha256_file(stage / "assets.md")})
        metadata = {"schema_version": SCHEMA_VERSION, "exporter": EXPORTER, **identity,
                    "source_pdf": {"relative_path": "source.pdf", "sha256": source_hash,
                                   "original_filename": source.name},
                    "cache_sha256": cache_hash, "cache_digest_basis": "归档选择集：相对路径和文件 SHA-256，含原始缓存 JSON/MD/图像",
                    "converter": {"name": "MinerU via llm-for-zotero", "version": args.converter_version},
                    "exported_at": datetime.now(timezone.utc).isoformat(), "page_mapping": mapping,
                    "images": images, "files": sorted(generated_files, key=lambda row: row["path"]),
                    "issues": issues, "quality_verified": False,
                    "source_association_verified": False}
        (stage / "provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        current_previous, _ = existing_package(target, identity, fingerprints)
        if bool(current_previous) != bool(locked_previous):
            raise ExportError("TARGET_CHANGED", "构建资料包时目标目录发生变化，未覆盖")
        if locked_previous:
            backup = target.parent / ("." + attachment_key + ".backup-" + uuid.uuid4().hex)
            target.rename(backup)
        try:
            stage.rename(target)
            stage = None
        except OSError:
            if backup is not None and not target.exists():
                backup.rename(target)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(str(backup))
            backup = None
        result["status"] = "replaced" if locked_previous else "created"
        return result
    finally:
        # 只清理本次生成的临时目录；若回滚失败，backup 保留供用户恢复。
        if stage is not None and stage.exists():
            shutil.rmtree(str(stage))
        lock.rmdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True, help="Vault 根目录")
    parser.add_argument("--cache-dir", required=True, help="单个附件的 MinerU 缓存目录（含 full.md）")
    parser.add_argument("--source-pdf", required=True, help="与该缓存对应的原始 PDF")
    parser.add_argument("--library-scope", default="users/0", help="users/0、users/<ID> 或 groups/<ID>")
    parser.add_argument("--parent-key", help="Zotero 父条目 key；须与缓存身份一致")
    parser.add_argument("--attachment-key", help="Zotero PDF 附件 key；须与缓存身份一致")
    parser.add_argument("--converter-version", default="unknown", help="实际解析器版本；未知时如实保留 unknown")
    parser.add_argument("--replace", action="store_true", help="替换已有且身份一致的本导出器资料包")
    parser.add_argument("--dry-run", action="store_true", help="只读预览，不创建目录或文件")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)
    code = 0
    try:
        result = export(args)
    except ExportError as exc:
        code = exc.exit_code
        result = {"status": "error", "output": None, "issues": [issue(exc.code, str(exc), "ERROR")], "quality_verified": False}
    except OSError as exc:
        code = 2
        result = {"status": "error", "output": None, "issues": [issue("IO_ERROR", str(exc), "ERROR")], "quality_verified": False}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"状态：{result['status']}")
        if result["output"]:
            print(f"资料包：{result['output']}")
        for row in result["issues"]:
            print(f"[{row['level']}] {row['code']}：{row['message']}")
        print("此结果仅报告归档状态，不表示原文、页码或科研结论已经核验。")
    return code


if __name__ == "__main__":
    sys.exit(main())
