#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""笔记摘要卡 note_digest.py 的离线测试。"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from vault_utils import AI_END, AI_START, HUMAN_END, HUMAN_START  # noqa: E402

SPEC = importlib.util.spec_from_file_location("tested_note_digest", SCRIPTS / "note_digest.py")
digest_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(digest_module)

NOTE = """---
type: literature-note
title: 示例论文
year: 2025
citekey: example2025
claims:
  - id: C1
    text: 方法 A 在数据集 B 上提升 3 个百分点
    source: PDF p.3 / Table 1
    verification: unverified
---

# 示例论文

## 摘要

一句话摘要。

<!-- AI:START -->
## 方法

细节。
<!-- AI:END -->

<!-- HUMAN:START -->
## 我的思考

人工内容。
<!-- HUMAN:END -->
"""


class NoteDigestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-digest-test-")
        self.addCleanup(self.temporary.cleanup)
        self.vault = Path(self.temporary.name).resolve()
        (self.vault / "02vault").mkdir()
        (self.vault / "02vault/论文.md").write_text(NOTE, encoding="utf-8")

    def test_digest_reports_claims_headings_and_line_numbers(self):
        item = digest_module.digest(self.vault, "02vault/论文.md")
        self.assertEqual(item["title"], "示例论文")
        self.assertEqual(item["metadata"]["citekey"], "example2025")
        self.assertEqual(item["metadata"]["claims"][0]["id"], "C1")
        self.assertEqual(item["metadata"]["claims"][0]["text"], "方法 A 在数据集 B 上提升 3 个百分点")
        headings = {heading["title"]: heading for heading in item["headings"]}
        self.assertEqual(headings["方法"]["level"], 2)
        text = (self.vault / "02vault/论文.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(text[headings["方法"]["line"] - 1], "## 方法")
        self.assertIn("ai", item["regions"])
        self.assertIn("human", item["regions"])
        self.assertGreater(headings["方法"]["lines"], 0)

    def test_render_is_compact_and_mentions_claims(self):
        rendered = digest_module.render([digest_module.digest(self.vault, "02vault/论文.md")])
        self.assertIn("claims", rendered)
        self.assertIn("C1: 方法 A", rendered)
        self.assertIn("PDF p.3 / Table 1", rendered)
        self.assertIn("L", rendered)
        self.assertNotIn("一句话摘要。", rendered)
        self.assertLess(len(rendered), 1000)

    def test_paths_outside_vault_are_rejected(self):
        with self.assertRaises(digest_module.DigestError) as caught:
            digest_module.digest(self.vault, "../outside.md")
        self.assertEqual(caught.exception.code, "PATH_REJECTED")

    def test_missing_note_is_reported(self):
        with self.assertRaises(digest_module.DigestError) as caught:
            digest_module.digest(self.vault, "02vault/absent.md")
        self.assertEqual(caught.exception.code, "NOTE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
