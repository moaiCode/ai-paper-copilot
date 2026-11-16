#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输出笔记摘要卡：front matter 要点、claims、小节标题与行号、分区位置。

用途是先读摘要再定向读原文，减少整篇加载；不修改笔记，也不替代全文核对。
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vault_utils import inside_path, note_regions, read_note  # noqa: E402

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
KEY_FIELDS = ("type", "title", "authors", "year", "venue", "doi", "citekey", "zotero_key",
              "pdf_key", "status", "review_status", "tags", "claims", "questions")


class DigestError(Exception):
    """带稳定错误码的摘要失败。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def _scalar(value):
    """只保留适合摘要卡的短值；长文本留给原文。"""
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value if isinstance(value, str) else str(value)
        return text if len(text) <= 160 else text[:157] + "..."
    if isinstance(value, list):
        return [_scalar(item) for item in value[:12]]
    if isinstance(value, dict):
        return {str(key): _scalar(item) for key, item in list(value.items())[:8]}
    return None


def digest(vault, relative):
    """生成单个 Markdown 笔记的摘要；文件必须位于 Vault 内。"""
    try:
        path = inside_path(vault, relative)
    except ValueError as exc:
        raise DigestError("PATH_REJECTED", str(exc))
    if path.suffix.lower() != ".md":
        raise DigestError("NOT_MARKDOWN", "只支持 Markdown 笔记：{}".format(relative))
    if not path.is_file():
        raise DigestError("NOTE_NOT_FOUND", "笔记不存在：{}".format(relative))
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        metadata, body, body_start = read_note(text)
    except ValueError:
        metadata, body, body_start = {}, text, 0
    body_line = _line_of(text, body_start)
    headings = []
    matches = list(HEADING_RE.finditer(body))
    for index, match in enumerate(matches):
        level = len(match.group(1))
        end = len(body)
        for later in matches[index + 1:]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        start_line = body_line + body.count("\n", 0, match.start())
        end_line = body_line + body.count("\n", 0, max(end - 1, match.start()))
        headings.append({"level": level, "title": match.group(2), "line": start_line,
                         "end_line": end_line, "lines": max(end_line - start_line + 1, 1)})
    regions = {}
    try:
        ai, human = note_regions(body)
        for name, span in (("ai", ai), ("human", human)):
            regions[name] = {"start_line": body_line + body.count("\n", 0, span[0]),
                             "end_line": body_line + body.count("\n", 0, max(span[1] - 1, span[0]))}
    except ValueError:
        pass
    selected = {key: _scalar(metadata[key]) for key in KEY_FIELDS if key in metadata}
    front_lines = text.count("\n", 0, body_start)
    return {"path": relative, "title": selected.get("title") or _fallback_title(body),
            "front_matter_lines": front_lines, "line_count": text.count("\n") + 1,
            "char_count": len(text), "metadata": selected, "headings": headings,
            "regions": regions,
            "hint": "先按标题行号选读小节；claims 只是索引，引用前回原文核对。"}


def _fallback_title(body):
    match = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    return match.group(1) if match else ""


def render(items):
    """把摘要渲染成紧凑文本，避免输出整篇笔记。"""
    lines = []
    for item in items:
        lines.append(item["path"])
        lines.append("标题：{} | {} 行 / {} 字符 | front matter {} 行".format(
            item["title"] or "（无标题）", item["line_count"], item["char_count"], item["front_matter_lines"]))
        claims = item["metadata"].get("claims")
        if claims:
            lines.append("claims：")
            for claim in claims:
                if isinstance(claim, dict):
                    # claim 对象只展示 id、正文与来源/核验状态，详细论证仍在原文。
                    meta = "，".join(str(claim[key]) for key in ("source", "verification")
                                    if claim.get(key))
                    lines.append("- {}: {}{}".format(
                        claim.get("id") or "?", claim.get("text") or "",
                        "（{}）".format(meta) if meta else ""))
                else:
                    lines.append("- {}".format(claim))
        if item["headings"]:
            lines.append("小节（行号）：")
            for heading in item["headings"]:
                lines.append("  L{} {} {}（L{}-L{}，{} 行）".format(
                    heading["line"], "#" * heading["level"], heading["title"],
                    heading["line"], heading["end_line"], heading["lines"]))
        if item["regions"]:
            lines.append("分区：" + "；".join(
                "{} L{}-L{}".format(name.upper(), span["start_line"], span["end_line"])
                for name, span in item["regions"].items()))
        lines.append("提示：先定向读小节，claims 引用前回原文核对。")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv=None):
    parser = argparse.ArgumentParser(description="输出 Markdown 笔记的摘要卡，便于定向阅读")
    parser.add_argument("--vault", required=True, help="正式库绝对路径")
    parser.add_argument("notes", nargs="+", help="Vault 内相对路径，例如 02vault/论文.md")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)
    try:
        items = [digest(args.vault, note) for note in args.notes]
    except DigestError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "message": exc.message},
                         ensure_ascii=False, indent=2))
        return 1
    if args.json:
        print(json.dumps({"status": "ok", "notes": items}, ensure_ascii=False, indent=2))
    else:
        print(render(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
