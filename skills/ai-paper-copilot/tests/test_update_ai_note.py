#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用可观察的保护与并发行为验证更新器，而非检查固定措辞。"""

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_ai_note as updater
from vault_utils import note_regions, read_note, yaml


def note(metadata=None, ai="AI旧分析", human="我亲自记录：这个假设还要核查。\n保持空格  和公式 $x$。"):
    """测试身份只存在临时目录，绝不导入真实 Zotero。"""
    data = dict(type="literature-note", title="结构测试", library_scope="users/0",
                zotero_key="ABCD2345", pdf_key="EFGH2345", citekey="fixture2026",
                material_status="pdf", review_status="reviewed", claims=[])
    if metadata:
        data.update(metadata)
    return "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n前言保留\n<!-- AI:START -->\n" + ai + "\n<!-- AI:END -->\n分区外保留\n<!-- HUMAN:START -->\n" + human + "\n<!-- HUMAN:END -->\n尾注保留\n"


def with_metadata(text, changes):
    """保留正文，只构造完整候选的元数据变化，避免通过固定文本替换伪造测试。"""
    metadata, body, _ = read_note(text)
    metadata.update(changes)
    return "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + body


def knowledge_note():
    """知识页没有论文身份字段，也保留不能由 AI 自动更改的人工决定。"""
    data = dict(type="knowledge-page", knowledge_kind="theme", title="已有主题",
                aliases=[], tags=["knowledge"], status="active", created="2026-11-15",
                updated="2026-11-16", project="用户选择的项目", source_notes=[], related=[],
                evidence_status="note_only")
    body = "前言保留\n<!-- AI:START -->\n# 已有主题\n旧判断\n<!-- AI:END -->\n分区外保留\n<!-- HUMAN:START -->\n用户采纳旧版本中的条件。  \n<!-- HUMAN:END -->\n尾注保留\n"
    return "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n" + body


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

    def test_knowledge_update_refreshes_evidence_and_preserves_human_decisions(self):
        original = knowledge_note()
        candidate = with_metadata(original, {"source_notes": ["[[证据页]]"], "related": ["[[方法页]]"],
                                             "evidence_status": "mixed"})
        candidate = candidate.replace("旧判断", "有新证据支持的判断").replace("用户采纳旧版本中的条件。", "AI 误改用户决定")
        output, report = updater.prepare(original, candidate)
        metadata, body, _ = read_note(output)
        old_metadata, old_body, _ = read_note(original)
        old_ai, old_human = note_regions(old_body)
        new_ai, new_human = note_regions(body)
        self.assertEqual(body[new_human[0]:new_human[1]], old_body[old_human[0]:old_human[1]])
        self.assertEqual(body[:new_ai[0]], old_body[:old_ai[0]])
        self.assertEqual(body[new_ai[1]:], old_body[old_ai[1]:])
        self.assertIn("有新证据支持的判断", body)
        self.assertNotIn("AI 误改用户决定", body)
        for field in ("type", "knowledge_kind", "created", "project", "status"):
            self.assertEqual(metadata[field], old_metadata[field])
        self.assertEqual(metadata["source_notes"], ["[[证据页]]"])
        self.assertEqual(metadata["evidence_status"], "mixed")
        self.assertFalse({"material_status", "claims", "review_status"} & set(metadata))
        self.assertTrue(report["human_content_preserved"])
        self.assertTrue(report["human_review_required"])

    def test_knowledge_no_change_keeps_original_without_inventing_review(self):
        original = knowledge_note()
        output, report = updater.prepare(original, original)
        self.assertEqual(output, original)
        self.assertEqual(report["status"], "unchanged")
        self.assertFalse(report.get("human_review_required", False))

    def test_knowledge_identity_and_user_decisions_cannot_change_in_candidate(self):
        original = knowledge_note()
        for field, value in (("type", "literature-note"), ("knowledge_kind", "concept"),
                             ("created", "2026-11-17"), ("project", "AI另选课题"), ("status", "archived")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                updater.prepare(original, with_metadata(original, {field: value}))

    def test_knowledge_cannot_inject_paper_fields_or_human_verification(self):
        original = knowledge_note()
        for field, value in (("material_status", "parsed"), ("review_status", "reviewed"),
                             ("claims", [{"id": "K1", "verification": "human_verified"}]),
                             ("human_verified", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                updater.prepare(original, with_metadata(original, {field: value}))

    def test_knowledge_metadata_types_and_evidence_states_are_checked(self):
        original = knowledge_note()
        cases = ({"title": ""}, {"source_notes": "[[单个字符串]]"}, {"source_notes": [""]},
                 {"related": [{"name": "对象"}]}, {"aliases": None}, {"tags": [1]},
                 {"evidence_status": "human_verified"}, {"evidence_status": []})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                updater.prepare(original, with_metadata(original, changes))

    def test_knowledge_classification_is_optional_and_existing_custom_kind_is_protected(self):
        metadata, body, _ = read_note(knowledge_note())
        del metadata["knowledge_kind"]
        original = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + body
        output, _ = updater.prepare(original, original.replace("旧判断", "新判断"))
        self.assertNotIn("knowledge_kind", read_note(output)[0])
        custom = with_metadata(knowledge_note(), {"knowledge_kind": "用户自定义分类"})
        output, _ = updater.prepare(custom, custom.replace("旧判断", "新判断"))
        self.assertEqual(read_note(output)[0]["knowledge_kind"], "用户自定义分类")
        with self.assertRaises(ValueError):
            updater.prepare(custom, with_metadata(custom, {"knowledge_kind": "AI另分的类"}))

    def test_real_synthesis_template_refreshes_title_and_ai_without_changing_human(self):
        template = Path(__file__).resolve().parents[1] / "templates/主题综合模板.md"
        original = template.read_text(encoding="utf-8").replace("{{date}}", "2026-11-16")
        original = re.sub(r"\{\{[^}]+\}\}", "已有知识", original)
        original = original.replace("<!-- HUMAN:START -->", "<!-- HUMAN:START -->\n用户核查记录：只同意旧条件。")
        candidate = with_metadata(original, {"title": "更新知识", "source_notes": ["[[新增证据]]"],
                                             "evidence_status": "mixed"})
        # 从真实模板提取 AI 区构造补读稿；不依赖固定章节名或知识分类体系。
        candidate_meta, candidate_body, _ = read_note(candidate)
        candidate_ai, _ = note_regions(candidate_body)
        payload = candidate_body[candidate_ai[0]:candidate_ai[1]].replace("# 已有知识", "# 更新知识")
        payload += "\n补读摘要：新证据改变了适用条件。\n"
        candidate_body = candidate_body[:candidate_ai[0]] + payload + candidate_body[candidate_ai[1]:]
        candidate_body = candidate_body.replace("用户核查记录：只同意旧条件。", "不应写入的人核结论")
        candidate = "---\n" + yaml.safe_dump(candidate_meta, allow_unicode=True, sort_keys=False) + "---\n" + candidate_body
        output, report = updater.prepare(original, candidate)
        metadata, body, _ = read_note(output)
        _, original_body, _ = read_note(original)
        ai, human = note_regions(body)
        old_ai, old_human = note_regions(original_body)
        self.assertIn("# 更新知识", body[ai[0]:ai[1]])
        self.assertIn("补读摘要：新证据改变了适用条件。", body[ai[0]:ai[1]])
        self.assertEqual(body[human[0]:human[1]], original_body[old_human[0]:old_human[1]])
        self.assertEqual(body[:ai[0]], original_body[:old_ai[0]])
        self.assertEqual(body[ai[1]:], original_body[old_ai[1]:])
        self.assertEqual(metadata["title"], "更新知识")
        self.assertEqual(metadata["source_notes"], ["[[新增证据]]"])
        self.assertEqual(metadata["evidence_status"], "mixed")
        self.assertNotIn("claims", metadata)
        self.assertTrue(report["human_review_required"])

    def test_other_page_types_are_not_implicitly_supported(self):
        original = with_metadata(knowledge_note(), {"type": "experiment-run"})
        with self.assertRaises(ValueError):
            updater.prepare(original, original.replace("旧判断", "新判断"))

    def test_knowledge_cli_reports_review_and_preserves_original_during_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, candidate = root / "knowledge.md", root / "candidate.md"
            original.write_text(knowledge_note(), encoding="utf-8")
            candidate.write_text(knowledge_note().replace("旧判断", "新证据判断"), encoding="utf-8")
            command = [sys.executable, updater.__file__, "--note", str(original), "--content", str(candidate), "--json"]
            before = original.read_bytes()
            preview = subprocess.run(command + ["--dry-run"], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertTrue(json.loads(preview.stdout)["human_review_required"])
            self.assertEqual(original.read_bytes(), before)
            actual = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(json.loads(actual.stdout)["status"], "updated")
            self.assertIn("新证据判断", original.read_text())
            self.assertIn("用户采纳旧版本中的条件。", original.read_text())

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
