#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比或更新已安装库中的两个项目 skill，默认只预览。

脚本只触碰 Vault 根的 `.agents/skills/` 与可选的旧版入口文件，不读取笔记、
不连接应用、不安装依赖。更新前保留原副本备份，便于回滚。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

SKILL_NAMES = ("ai-paper-copilot", "ai-paper-setup")
IGNORED = {".DS_Store", "__pycache__", ".venv", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
VERSION_RE = re.compile(r'^\s+version:\s*"?([^"\n]+?)"?\s*$', re.M)
LEGACY_ENTRY = "research-vault-entry.md"
LEGACY_SKILL = "research-vault"
LEGACY_PROFILE_PATH = ("integrations", "llm_for_zotero", "codex_app_server")


class SyncError(Exception):
    """带稳定错误码的同步失败；JSON 输出不包含凭据或用户笔记。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def skill_version(directory):
    """读取 SKILL.md 顶部元信息中的版本；缺失时返回 None。"""
    path = Path(directory) / "SKILL.md"
    if not path.is_file():
        return None
    head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:40])
    match = VERSION_RE.search(head)
    return match.group(1).strip() if match else None


def inventory(directory):
    """返回相对路径到 SHA-256 的映射；忽略缓存与系统临时文件。"""
    directory = Path(directory)
    files = {}
    for root, dirs, names in os.walk(directory, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in IGNORED)
        for name in sorted(names):
            if name in IGNORED:
                continue
            path = Path(root) / name
            files[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def compare(source, installed):
    """比较两个目录，返回新增、删除和内容变化的相对路径。"""
    source_files, installed_files = inventory(source), inventory(installed)
    added = sorted(set(source_files) - set(installed_files))
    removed = sorted(set(installed_files) - set(source_files))
    changed = sorted(name for name in set(source_files) & set(installed_files)
                     if source_files[name] != installed_files[name])
    return {"added": added, "removed": removed, "changed": changed,
            "needs_update": bool(added or removed or changed)}


def profile_legacy_keys(vault):
    """只报告旧版字段是否存在，不回显其他配置值。"""
    path = Path(vault) / "research-profile.json"
    if not path.is_file():
        return False
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    node = profile
    for part in LEGACY_PROFILE_PATH:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def legacy_report(vault):
    """列出 2.0.x 遗留的插件入口、旧 skill 目录与 profile 字段。"""
    vault = Path(vault)
    report = []
    entry = vault / LEGACY_ENTRY
    if entry.is_file() or entry.is_symlink():
        report.append({"code": "LEGACY_ENTRY_FILE", "path": str(entry),
                       "message": "旧版插件入口文件，可用 --clean-legacy 删除。"})
    old_skill = vault / ".agents" / "skills" / LEGACY_SKILL
    if old_skill.exists():
        report.append({"code": "LEGACY_SKILL_DIR", "path": str(old_skill),
                       "message": "旧版插件技能目录，可用 --clean-legacy 删除。"})
    if profile_legacy_keys(vault):
        report.append({"code": "LEGACY_PROFILE_KEYS", "path": str(vault / "research-profile.json"),
                       "message": "profile 含旧版插件运行时字段，可用 --clean-legacy 移除。"})
    return report


def plan(vault, repo):
    """生成只读预览；不写入任何文件。"""
    vault, repo = Path(vault).expanduser(), Path(repo).expanduser()
    if not vault.is_dir():
        raise SyncError("VAULT_NOT_FOUND", "正式库目录不存在：{}".format(vault))
    if not (repo / "skills").is_dir():
        raise SyncError("REPO_NOT_FOUND", "源码仓库缺少 skills 目录：{}".format(repo))
    skills = []
    for name in SKILL_NAMES:
        source = repo / "skills" / name
        installed = vault / ".agents" / "skills" / name
        if not source.is_dir():
            raise SyncError("SOURCE_SKILL_MISSING", "源码缺少技能目录：{}".format(source))
        info = {"name": name, "source": str(source), "installed": str(installed),
                "source_version": skill_version(source), "installed_version": skill_version(installed),
                "installed_present": installed.is_dir(), "symlink": installed.is_symlink()}
        if not installed.is_dir():
            info.update({"added": sorted(inventory(source)), "removed": [], "changed": [],
                         "needs_update": True})
        else:
            info.update(compare(source, installed))
        skills.append(info)
    return {"status": "preview", "vault": str(vault.resolve()), "repo": str(repo.resolve()),
            "skills": skills, "legacy": legacy_report(vault),
            "message": "预览不写文件；确认后用 --apply 更新副本，更新前自动备份。"}


def _timestamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _stage_copy(source, skills_dir, name, stamp):
    staging = skills_dir / (".staging-{}-{}".format(stamp, name))
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging, ignore=shutil.ignore_patterns(*IGNORED))
    return staging


def apply_skills(vault, repo, result):
    """以备份和原子重命名更新两个技能目录；失败时恢复旧副本。"""
    vault = Path(vault)
    skills_dir = vault / ".agents" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    backup_root = vault / ".agents" / "skill-backups" / stamp
    for info in result["skills"]:
        if info["symlink"]:
            raise SyncError("SKILL_IS_SYMLINK", "技能目录是符号链接，请人工处理后重试：{}".format(info["installed"]))
        if not info["needs_update"]:
            continue
        source, installed = Path(info["source"]), Path(info["installed"])
        staging = _stage_copy(source, skills_dir, info["name"], stamp)
        moved = None
        try:
            if installed.exists():
                backup_root.mkdir(parents=True, exist_ok=True)
                moved = backup_root / info["name"]
                shutil.move(str(installed), str(moved))
            os.replace(str(staging), str(installed))
        except OSError as exc:
            if installed.exists():
                shutil.rmtree(installed, ignore_errors=True)
            if moved and moved.exists():
                shutil.move(str(moved), str(installed))
            raise SyncError("APPLY_FAILED", "更新技能失败，已尝试回滚：{}".format(exc))
        info["backup"] = str(moved) if moved else None
    result["status"] = "applied"
    result["backup_root"] = str(backup_root) if backup_root.exists() else None
    result["message"] = "已更新技能副本；如未生成备份，说明该技能此前未安装。"
    return result


def clean_legacy(vault):
    """删除旧版入口并移除 profile 中的插件运行时段，保留其余字段。"""
    vault = Path(vault)
    removed = []
    entry = vault / LEGACY_ENTRY
    if entry.is_symlink() or entry.is_file():
        entry.unlink()
        removed.append(str(entry))
    old_skill = vault / ".agents" / "skills" / LEGACY_SKILL
    if old_skill.is_dir() and not old_skill.is_symlink():
        shutil.rmtree(old_skill)
        removed.append(str(old_skill))
    profile_path = vault / "research-profile.json"
    if profile_legacy_keys(vault) and profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        backup = profile_path.with_name(profile_path.name + ".bak-" + _timestamp())
        shutil.copy2(profile_path, backup)
        chain, keys = [profile], []
        node = profile
        for part in LEGACY_PROFILE_PATH[:-1]:
            node = node[part]
            chain.append(node)
            keys.append(part)
        chain[-1].pop(LEGACY_PROFILE_PATH[-1], None)
        for index in range(len(chain) - 2, -1, -1):
            if chain[index + 1] == {}:
                chain[index].pop(keys[index], None)
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        removed.append(str(profile_path) + " (旧字段，备份：{})".format(backup.name))
    return removed


def run(args):
    result = plan(args.vault, args.repo)
    if args.clean_legacy:
        cleaned = clean_legacy(args.vault)
        result["cleaned"] = cleaned
        result["legacy"] = legacy_report(args.vault)
    if args.apply:
        result = apply_skills(args.vault, args.repo, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="对比或更新正式库中的项目 skill 副本")
    parser.add_argument("--vault", required=True, help="正式库绝对路径")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]), help="源码仓库路径")
    parser.add_argument("--apply", action="store_true", help="写入更新；默认只预览")
    parser.add_argument("--clean-legacy", action="store_true", help="删除遗留入口文件并移除 profile 旧字段")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except SyncError as exc:
        result = {"status": "error", "code": exc.code, "message": exc.message}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("目标：{}".format(result["vault"]))
        for info in result["skills"]:
            print("- {name}: 已装 {installed_version} / 源码 {source_version}，{state}".format(
                state="需更新" if info["needs_update"] else "已一致", **info))
            for key in ("added", "removed", "changed"):
                if info.get(key):
                    print("  {}: {}".format(key, ", ".join(info[key])))
        for item in result["legacy"]:
            print("遗留：{} ({})".format(item["code"], item["path"]))
        if result.get("cleaned"):
            print("已清理：" + "；".join(result["cleaned"]))
        print(result["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
