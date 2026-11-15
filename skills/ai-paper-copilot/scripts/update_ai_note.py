#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用完整候选笔记更新 AI 区与机器字段，保留人工区及其他正文。

只允许修改已明确分区的笔记，不猜测哪一段属于用户。写入前复查原文件
指纹，并在同目录阶段文件完成后原子替换；失败时不留下半篇笔记。
"""

import argparse
import difflib
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

try:
    from vault_utils import read_note, note_regions, inside_path, yaml
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(2)

# 这些身份字段不应在一次补读中悄悄改变。绑定临时笔记、合并文献等操作
# 需要单独检查，不允许借用本脚本把一篇已归档笔记变成另一篇论文。
IDENTITY_FIELDS = ("type", "library_scope", "zotero_key", "pdf_key", "citekey")
EDITABLE_FIELDS = {
    "title", "aliases", "tags", "material_status", "claims", "fulltext_path",
    "doi", "arxiv", "year", "venue", "task", "setting", "protocol",
    "source_sha256", "updated", "coverage", "source_url",
}
VERIFICATIONS = {"unverified", "agent_verified", "human_verified"}


def safe_claims(candidate, previous, source_changed):
    """新的人工确认只能由真实用户产生，不能从候选文件自行升级。"""
    if not isinstance(candidate, list) or not isinstance(previous, list):
        raise ValueError("claims 必须为数组")
    old = {claim.get("id"): claim for claim in previous if isinstance(claim, dict)}
    claims, downgraded, seen = [], [], set()
    for claim in candidate:
        if not isinstance(claim, dict):
            raise ValueError("claims 中每项必须是对象")
        claim = dict(claim)
        identifier = claim.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError("claim id 为空或重复")
        seen.add(identifier)
        if not isinstance(claim.get("text"), str) or not claim["text"].strip():
            raise ValueError("claim text 不可为空")
        verification = claim.get("verification", "unverified")
        if not isinstance(verification, str) or verification not in VERIFICATIONS:
            raise ValueError("claim verification 非法")
        if verification != "unverified" and (not isinstance(claim.get("source"), str) or not claim["source"].strip()):
            raise ValueError("已核验 claim 必须有 source")
        if "quote" in claim and (not isinstance(claim["quote"], str) or not claim["quote"].strip()):
            raise ValueError("可省略 quote，但填写时不能是空引用")
        prior = old.get(identifier, {})
        unchanged = all(prior.get(field) == claim.get(field) for field in ("text", "source", "quote"))
        if verification == "human_verified" and not (
                unchanged and prior.get("verification") == "human_verified" and not source_changed):
            claim["verification"] = "unverified"
            downgraded.append(identifier)
        else:
            claim["verification"] = verification
        claims.append(claim)
    return claims, downgraded


def prepare(original, candidate):
    """纯函数准备变更，供预览与测试共用；不修改磁盘。"""
    old, body, _ = read_note(original)
    new, new_body, _ = read_note(candidate)
    ai, _ = note_regions(body)
    new_ai, _ = note_regions(new_body)
    for field in IDENTITY_FIELDS:
        if old.get(field) != new.get(field):
            raise ValueError("身份字段 {} 发生变化；请先单独核对归档身份".format(field))
    changed_unknown = [field for field in new if field not in EDITABLE_FIELDS and field not in IDENTITY_FIELDS
                       and field != "review_status" and old.get(field) != new[field]]
    if changed_unknown:
        raise ValueError("候选包含未获支持的元信息变更：{}".format(", ".join(changed_unknown)))
    metadata = dict(old)
    for field in EDITABLE_FIELDS:
        if field in new:
            metadata[field] = new[field]
    # 预防候选把合法笔记变成类型错误或越界路径；材料不齐可以明确留空，
    # 但不能把空标题、任意状态或 ../ 路径当成一次成功更新。
    if not isinstance(metadata.get("title"), str) or not metadata["title"].strip():
        raise ValueError("title 必须是非空字符串")
    if metadata.get("material_status") not in ("abstract", "pdf", "parsed"):
        raise ValueError("material_status 只能是 abstract、pdf 或 parsed")
    fulltext = metadata.get("fulltext_path", "")
    if not isinstance(fulltext, str):
        raise ValueError("fulltext_path 必须为字符串")
    if fulltext and (Path(fulltext).is_absolute() or ".." in Path(fulltext).parts):
        raise ValueError("fulltext_path 必须是 Vault 内相对路径")
    if metadata.get("material_status") == "parsed" and not fulltext:
        raise ValueError("parsed 状态必须提供 fulltext_path；仅有 PDF 请保留 pdf 状态")
    source_changed = any(old.get(field) != metadata.get(field) for field in ("source_sha256", "fulltext_path"))
    claims, downgraded = safe_claims(metadata.get("claims", []), old.get("claims", []), source_changed)
    metadata["claims"] = claims
    # 不采用候选文件的人工区和普通正文：它们可能是空模板、旧副本或模型误改。
    updated_body = body[:ai[0]] + new_body[new_ai[0]:new_ai[1]] + body[ai[1]:]
    changed = metadata != old or updated_body != body
    if not changed:
        return original, dict(status="unchanged", downgraded_claims=downgraded)
    metadata["review_status"] = "unreviewed"
    output = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip() + "\n---\n" + updated_body
    return output, dict(status="updated", downgraded_claims=downgraded,
                        review_status="unreviewed", human_content_preserved=True)


def atomic_update(path, expected, output):
    """保留文件权限，检测生成候选期间的并发修改，完成后再替换目标。"""
    temporary = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        with tempfile.NamedTemporaryFile(prefix=".ai-note-", dir=str(path.parent), delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(str(temporary), mode)
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("原笔记已被其他程序修改；本次未覆盖，请重新读取并合并")
        os.replace(str(temporary), str(path))
        temporary = None
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--note", required=True, help="已有笔记路径")
    parser.add_argument("--content", required=True, help="包含完整frontmatter与分区的候选笔记")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        note = Path(args.note).expanduser().absolute()
        candidate = Path(args.content).expanduser().absolute()
        if note.is_symlink() or not note.is_file() or not candidate.is_file():
            raise FileNotFoundError("目标必须是已有普通文件，且候选文件必须存在")
        if note.resolve() == candidate.resolve():
            raise ValueError("候选文件不能就是原笔记")
        raw = note.read_bytes()
        output, report = prepare(raw.decode("utf-8"), candidate.read_text(encoding="utf-8"))
        # 能找到 Vault 时进一步检查实际目标；临时独立笔记没有 Vault 时，
        # 只做相对路径形式检查，不凭不存在的库根猜测文件位置。
        metadata = read_note(output)[0]
        vault = next((parent for parent in note.parents if (parent / "research-profile.json").is_file()), None)
        if vault and metadata.get("fulltext_path"):
            if not inside_path(vault, metadata["fulltext_path"]).is_file():
                raise ValueError("fulltext_path 指向的资料不存在；本次未更新")
        if report["status"] == "updated":
            if args.dry_run:
                report["status"] = "would_update"
                report["diff"] = "".join(difflib.unified_diff(
                    raw.decode("utf-8").splitlines(keepends=True), output.splitlines(keepends=True),
                    fromfile="原笔记", tofile="候选AI更新", n=0))
            else:
                atomic_update(note, hashlib.sha256(raw).hexdigest(), output)
        report.update(note=str(note), dry_run=args.dry_run)
        code = 0
    except (OSError, ValueError, UnicodeError) as exc:
        report, code = dict(status="error", message=str(exc)), 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["status"] + ": " + report.get("message", report.get("note", "")))
        if report.get("diff"):
            print(report["diff"])
    return code


if __name__ == "__main__":
    sys.exit(main())
