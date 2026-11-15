#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用可观察的保护与并发行为验证更新器，而非检查固定措辞。"""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_ai_note as updater
from vault_utils import read_note, yaml


def note(metadata=None, ai="AI旧分析", human="我亲自记录：这个假设还要核查。\n保持空格  和公式 $x$。"):
    """测试身份只存在临时目录，绝不导入真实 Zotero。"""
    data = dict(type="literature-note", title="结构测试", library_scope="users/0",
                zotero_key="ABCD2345", pdf_key="EFGH2345", citekey="fixture2026",
                material_status="pdf", review_status="reviewed", claims=[])
    if metadata:
        data.update(metadata)
    return "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n前言保留\n<!-- AI:START -->\n" + ai + "\n<!-- AI:END -->\n分区外保留\n<!-- HUMAN:START -->\n" + human + "\n<!-- HUMAN:END -->\n尾注保留\n"


class UpdateTests(unittest.TestCase):
    def test_preserves_human_and_outside_content(self):
        original = note()
        output, report = updater.prepare(original, note(ai="更正后的推断", human="候选误改人工区"))
        self.assertIn("我亲自记录", output)
        self.assertNotIn("候选误改人工区", output)
        self.assertIn("前言保留", output)
        self.assertIn("尾注保留", output)
        self.assertEqual(read_note(output)[0]["review_status"], "unreviewed")
        self.assertTrue(report["human_content_preserved"])

    def test_no_change_does_not_reset_review(self):
        original = note()
        output, report = updater.prepare(original, original)
        self.assertEqual(output, original)
        self.assertEqual(report["status"], "unchanged")

    def test_identity_change_rejected(self):
        for field in updater.IDENTITY_FIELDS:
            with self.subTest(field=field), self.assertRaises(ValueError):
                updater.prepare(note(), note({field: "changed"}))

    def test_unchanged_human_claim_can_survive_ai_refresh(self):
        claim = dict(id="C1", text="待测试主张", source="PDF p.1", verification="human_verified")
        output, _ = updater.prepare(note({"claims": [claim]}), note({"claims": [claim]}, ai="新增解释"))
        self.assertEqual(read_note(output)[0]["claims"][0]["verification"], "human_verified")

    def test_changed_or_new_claim_cannot_inherit_human_review(self):
        claim = dict(id="C1", text="原主张", source="PDF p.1", verification="human_verified")
        changed = dict(claim, text="另一主张")
        output, report = updater.prepare(note({"claims": [claim]}), note({"claims": [changed]}))
        self.assertEqual(report["downgraded_claims"], ["C1"])
        self.assertEqual(read_note(output)[0]["claims"][0]["verification"], "unverified")

    def test_reading_index_fields_can_be_refreshed_without_changing_identity(self):
        output, report = updater.prepare(note(), note({
            "authors": ["Author One"],
            "year": 2024,
            "theme": "方法比较",
            "methodology": "受控实验",
            "key_finding": "需要回到原文核查的摘要",
            "related_notes": ["[[主题页]]"],
        }, ai="补充后的 AI 分析"))
        metadata = read_note(output)[0]
        self.assertEqual(metadata["authors"], ["Author One"])
        self.assertEqual(metadata["year"], 2024)
        self.assertEqual(metadata["related_notes"], ["[[主题页]]"])
        self.assertEqual(report["status"], "updated")
        self.assertEqual(metadata["review_status"], "unreviewed")

    def test_source_revision_invalidates_claim(self):
        claim = dict(id="C1", text="原主张", source="PDF p.1", verification="human_verified")
        output, _ = updater.prepare(note({"claims": [claim], "source_sha256": "old"}),
                                    note({"claims": [claim], "source_sha256": "new"}))
        self.assertEqual(read_note(output)[0]["claims"][0]["verification"], "unverified")

    def test_malformed_regions_rejected(self):
        for candidate in (note().replace("<!-- HUMAN:END -->", ""),
                          note() + "<!-- AI:START -->", note().replace("<!-- AI:END -->", "<!-- HUMAN:START -->")):
            with self.subTest(candidate=candidate[-70:]), self.assertRaises(ValueError):
                updater.prepare(note(), candidate)

    def test_bad_claim_types_rejected(self):
        base = dict(id="C1", text="主张", source="PDF p.1", verification="agent_verified")
        for claim in (dict(base, text=""), dict(base, source=None), dict(base, quote=""), dict(base, verification=[])):
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                updater.prepare(note(), note({"claims": [claim]}))

    def test_duplicate_yaml_key_rejected(self):
        with self.assertRaises(ValueError):
            updater.prepare(note(), note().replace("title: 结构测试", "title: A\ntitle: B"))

    def test_unknown_metadata_change_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            updater.prepare(note(), note({"manual_decision": "AI不应替用户决定"}))

    def test_invalid_metadata_cannot_corrupt_legal_note(self):
        for data in ({"title": ""}, {"title": ["错误类型"]}, {"material_status": "E5"},
                     {"material_status": "parsed", "fulltext_path": ""},
                     {"fulltext_path": "../逃出Vault.md"}, {"fulltext_path": "/tmp/外部.md"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                updater.prepare(note(), note(data))

    def test_concurrent_edit_prevents_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text(note(), encoding="utf-8")
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_text("用户刚刚进行了修改", encoding="utf-8")
            with self.assertRaises(ValueError):
                updater.atomic_update(path, fingerprint, note(ai="新稿"))
            self.assertEqual(path.read_text(), "用户刚刚进行了修改")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_cli_dry_run_and_actual_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, candidate = root / "note.md", root / "candidate.md"
            original.write_text(note(), encoding="utf-8")
            candidate.write_text(note(ai="新稿"), encoding="utf-8")
            command = [sys.executable, updater.__file__, "--note", str(original), "--content", str(candidate), "--json"]
            before = original.read_bytes()
            preview = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(json.loads(preview.stdout)["status"], "would_update")
            self.assertIn("新稿", json.loads(preview.stdout)["diff"])
            self.assertNotIn("我亲自记录", json.loads(preview.stdout)["diff"])
            self.assertEqual(original.read_bytes(), before)
            actual = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertIn("新稿", original.read_text())
            self.assertIn("我亲自记录", original.read_text())


if __name__ == "__main__":
    unittest.main()
