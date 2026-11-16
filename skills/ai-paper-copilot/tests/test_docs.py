#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库文档完整性检查：相对链接、锚点、禁用词与 SKILL 元信息。

只读仓库内 Markdown 与 llms.txt；不访问网络。CI 通过 unittest discover 自动执行。
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".agents", ".pytest_cache", ".mypy_cache"}
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
BANNED = ("codex", "research-vault-entry.md", "zotero_codex", "codex_app_server")
VERSION_RE = re.compile(r'^\s+version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$', re.M)
NAME_RE = re.compile(r"^name:\s*([A-Za-z0-9_.-]+)\s*$", re.M)


def markdown_files():
    files = []
    for path in ROOT.rglob("*.md"):
        if any(part in EXCLUDED for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def strip_code(text):
    """去掉围栏与行内代码，避免把示例当成真实链接或标题。"""
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))


def slugify(text):
    text = text.strip().lower().replace("`", "")
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", text)
    return re.sub(r"\s+", "-", text)


def anchors(text):
    """近似 GitHub 的标题锚点；重复标题追加 -1、-2。"""
    found, seen = set(), {}
    for match in HEADING_RE.finditer(strip_code(text)):
        base = slugify(match.group(2))
        count = seen.get(base, 0)
        found.add(base if count == 0 else "{}-{}".format(base, count))
        seen[base] = count + 1
    return found


def links_in(path):
    return LINK_RE.findall(strip_code(path.read_text(encoding="utf-8", errors="replace")))


class DocsTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        failures = []
        for path in markdown_files():
            for target in links_in(path):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                file_part, _, anchor = target.partition("#")
                file_part = file_part.replace("%20", " ")
                if not file_part:
                    destination = path
                else:
                    destination = (path.parent / file_part).resolve()
                if not destination.exists():
                    failures.append("{} -> {} 不存在".format(path.relative_to(ROOT), target))
                    continue
                if anchor and destination.suffix.lower() == ".md" and destination.is_file():
                    if anchor not in anchors(destination.read_text(encoding="utf-8", errors="replace")):
                        failures.append("{} -> {} 锚点不存在".format(path.relative_to(ROOT), target))
        self.assertEqual(failures, [], "\n".join(failures))

    def test_no_legacy_client_terms_in_docs(self):
        failures = []
        for path in markdown_files() + [ROOT / "llms.txt"]:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for term in BANNED:
                if term in text:
                    failures.append("{} 含禁用词 {}".format(path.relative_to(ROOT), term))
        self.assertEqual(failures, [], "\n".join(failures))

    def test_skill_metadata_is_consistent(self):
        for name in ("ai-paper-copilot", "ai-paper-setup"):
            path = ROOT / "skills" / name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            head = "\n".join(text.splitlines()[:30])
            self.assertRegex(head, r"^---", "{} 缺少 front matter".format(name))
            self.assertEqual(NAME_RE.search(head).group(1), name)
            self.assertRegex(head, VERSION_RE, "{} 缺少语义化版本".format(name))
            metadata = {}
            for key in ("name", "version"):
                match = re.search(r"^\s*" + key + r":\s*\"?([^\"\n]+)\"?\s*$", head, re.M)
                metadata[key] = match.group(1).strip() if match else None
            self.assertTrue(metadata["version"])


if __name__ == "__main__":
    unittest.main()
