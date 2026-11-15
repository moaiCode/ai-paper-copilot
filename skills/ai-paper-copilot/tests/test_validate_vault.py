#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vault 结构检查的行为测试；临时合成资料不代表真实科研结果。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_vault.py"
EXPORT = SCRIPT.parent / "export_fulltext.py"
BODY = """# 阅读笔记

<!-- AI:START -->
## AI 分析
这是用于检查结构的合成分析。
<!-- AI:END -->

<!-- HUMAN:START -->
## 人工核查与我的思考
尚未人工核查。
<!-- HUMAN:END -->
"""


class ValidateVaultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-copilot-validate-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.vault = self.root / "vault"
        for directory in ("01knowledge", "02vault", "03fulltext", "04projects", "05writing", "06inbox", "templates"):
            (self.vault / directory).mkdir(parents=True)

    @staticmethod
    def metadata(**changes):
        data = {"type": "literature-note", "title": "Synthetic paper", "library_scope": "users/0",
                "zotero_key": "ABCD1234", "pdf_key": "EFGH5678", "citekey": "test2026",
                "material_status": "pdf", "review_status": "unreviewed", "fulltext_path": None,
                "claims": [{"id": "C1", "text": "用于测试的待核查主张", "source": "PDF p.1", "verification": "unverified"}]}
        data.update(changes)
        return data

    def note(self, relative="02vault/test.md", metadata=None, body=BODY):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.metadata() if metadata is None else metadata
        path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n" + body, encoding="utf-8")
        return path

    def run_check(self, *extra):
        process = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.vault), "--json", *extra],
                                 capture_output=True, text=True, check=False)
        self.assertNotIn("Traceback", process.stderr, process.stderr)
        try:
            report = json.loads(process.stdout)
        except ValueError:
            self.fail(f"未返回有效 JSON：{process.stdout!r}；{process.stderr!r}")
        return process.returncode, report

    def codes(self, report):
        return {row["code"] for row in report["issues"]}

    def test_empty_vault_is_not_whole_workflow_acceptance(self):
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "empty_vault")
        self.assertEqual(report["notes"], 0)
        self.assertFalse(report["content_verified"])

    def test_direct_pdf_does_not_require_markdown_or_mineru(self):
        self.note()
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "structure_ok")
        self.assertEqual(report["notes"], 1)
        self.assertNotIn("FULLTEXT_REQUIRED", self.codes(report))

    def test_real_yaml_comment_and_multiline_are_accepted(self):
        note = self.note()
        text = note.read_text(encoding="utf-8").replace("material_status: pdf", "material_status: pdf # 合法行尾注释")
        text = text.replace("title: Synthetic paper", "title: >\n  Synthetic\n  paper")
        note.write_text(text, encoding="utf-8")
        self.assertEqual(self.run_check()[0], 0)

    def test_duplicate_and_invalid_yaml_fields_are_errors(self):
        path = self.note()
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("title: Synthetic paper", "title: Synthetic paper\ntitle: conflicting"), encoding="utf-8")
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("FRONTMATTER", self.codes(report))
        path.write_text("---\ntitle: [unclosed\n---\n", encoding="utf-8")
        self.assertEqual(self.run_check()[0], 1)

    def test_empty_claim_and_explicit_empty_quote_are_rejected(self):
        self.note(metadata=self.metadata(claims=[{"id": "C1", "text": "", "quote": "", "verification": "unverified"}]))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertTrue({"CLAIM_EMPTY", "QUOTE_EMPTY"}.issubset(self.codes(report)))

    def test_verified_claim_needs_source_and_ids_are_unique(self):
        self.note(metadata=self.metadata(claims=[
            {"id": "C1", "text": "one", "source": "", "verification": "agent_verified"},
            {"id": "C1", "text": "two", "source": "PDF p.2", "verification": "human_verified"}]))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertTrue({"VERIFIED_WITHOUT_SOURCE", "CLAIM_DUPLICATE"}.issubset(self.codes(report)))

    def test_missing_claims_are_warning_not_a_content_certificate(self):
        self.note(metadata=self.metadata(claims=[]))
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertIn("CLAIMS_MISSING", self.codes(report))
        self.assertFalse(report["content_verified"])

    def test_reviewed_requires_human_verified_claims(self):
        self.note(metadata=self.metadata(review_status="reviewed"))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("REVIEW_STATUS_CONFLICT", self.codes(report))

    def test_malformed_scalar_types_report_errors_without_traceback(self):
        self.note(metadata=self.metadata(material_status=[], review_status={}, library_scope=[],
                                        claims=[{"id": [], "text": [], "source": [], "verification": []}]))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("MATERIAL_STATUS", self.codes(report))

    def test_regions_cannot_overlap_or_repeat(self):
        cross = "<!-- AI:START --> AI <!-- HUMAN:START --> HUMAN <!-- AI:END --> <!-- HUMAN:END -->"
        self.note(body=cross)
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("NOTE_REGIONS", self.codes(report))
        self.note(body=BODY + "<!-- AI:START -->")
        self.assertEqual(self.run_check()[0], 1)

    def test_duplicate_identity_is_scoped_to_library(self):
        self.note("02vault/one.md")
        self.note("02vault/two.md", metadata=self.metadata(citekey="other2026"))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("DUPLICATE_IDENTITY", self.codes(report))
        self.note("02vault/two.md", metadata=self.metadata(library_scope="groups/123", citekey="other2026"))
        self.assertEqual(self.run_check()[0], 0)

    def test_selected_check_skips_unrelated_broken_note(self):
        self.note("02vault/good.md")
        (self.vault / "02vault/bad.md").write_text("no frontmatter", encoding="utf-8")
        self.assertEqual(self.run_check()[0], 1)
        code, report = self.run_check("--path", "02vault/good.md")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["notes"], 1)
        self.assertEqual(report["check_scope"], "selected_documents")

    def test_selected_paths_reject_escape_missing_and_source_fulltext(self):
        for path in ("../outside.md", "/tmp/outside.md", "02vault/missing.md"):
            with self.subTest(path=path):
                self.assertEqual(self.run_check("--path", path)[0], 2)
        fulltext = self.vault / "03fulltext/raw.md"
        fulltext.write_text("raw paper, intentionally not a note", encoding="utf-8")
        self.assertEqual(self.run_check("--path", "03fulltext/raw.md")[0], 2)

    def test_temporary_draft_needs_no_zotero_identity(self):
        self.note("06inbox/temporary.md", metadata={"type": "reading-draft", "title": "临时阅读"}, body="直接讨论一份尚未入库的 PDF。\n")
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["notes"], 0)
        self.assertNotIn("REQUIRED_FIELD", self.codes(report))

    def test_templates_and_fulltext_content_are_not_checked_as_notes(self):
        (self.vault / "templates/raw.md").write_text("{{title}} [[not-created]]", encoding="utf-8")
        (self.vault / "03fulltext/raw.md").write_text("No frontmatter [[not-a-vault-link]]", encoding="utf-8")
        self.note()
        self.assertEqual(self.run_check()[0], 0)

    def test_todo_and_pending_discussion_are_allowed(self):
        self.note(body=BODY.replace("这是用于检查结构的合成分析。", "TODO：核查实验设定。[待补]负结果。"))
        self.assertEqual(self.run_check()[0], 0)

    def test_legacy_empty_findings_and_quotes_no_longer_pass(self):
        body = BODY.replace("这是用于检查结构的合成分析。", '- **主要发现 1**：\n- **原文引用 1**：\n  > ""\n')
        self.note(metadata=self.metadata(evidence_level="E5"), body=body)
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("LEGACY_EMPTY_EVIDENCE", self.codes(report))
        self.assertIn("LEGACY_EVIDENCE_LEVEL", self.codes(report))

    def test_broken_knowledge_links_and_missing_images_are_errors(self):
        self.note("01knowledge/主题.md", metadata={"type": "knowledge-page", "title": "主题"},
                  body="[[不存在的笔记]]\n![image](assets/missing.png)\n")
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("LINK_MISSING", self.codes(report))

    def test_wikilink_stem_ambiguity_is_reported(self):
        self.note("02vault/a/paper.md")
        self.note("02vault/b/paper.md", metadata=self.metadata(zotero_key="IJKL1234", citekey="other"))
        self.note("01knowledge/主题.md", metadata={"type": "knowledge-page", "title": "主题"}, body="[[paper]]\n")
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertIn("LINK_AMBIGUOUS", self.codes(report))

    def test_code_examples_and_remote_links_do_not_trigger_network_checks(self):
        self.note("01knowledge/主题.md", metadata={"type": "knowledge-page", "title": "主题"},
                  body="[remote](https://example.org/missing)\n```md\n[[example-not-a-real-note]]\n```\n")
        self.assertEqual(self.run_check()[0], 0)

    def make_archive(self):
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "full.md").write_text("# Paper\nExtracted text.\n", encoding="utf-8")
        (cache / "_llm_source.json").write_text(json.dumps({"attachmentKey": "EFGH5678", "parentItemKey": "ABCD1234"}), encoding="utf-8")
        source = self.root / "source.pdf"
        source.write_bytes(b"%PDF-1.7\nsynthetic test fixture\n")
        process = subprocess.run([sys.executable, str(EXPORT), "--vault", str(self.vault), "--cache-dir", str(cache),
                                  "--source-pdf", str(source), "--json"], capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        relative = "03fulltext/users/0/EFGH5678/full.md"
        self.note(metadata=self.metadata(material_status="parsed", fulltext_path=relative))
        return self.vault / "03fulltext/users/0/EFGH5678"

    def test_exported_archive_integrity_and_warning_inheritance(self):
        self.make_archive()
        code, report = self.run_check()
        self.assertEqual(code, 0, report)
        self.assertIn("PAGE_MAPPING_MISSING", self.codes(report))
        self.assertIn("EXPORT_NO_IMAGES", self.codes(report))

    def test_changed_archived_pdf_is_detected_by_fingerprint(self):
        package = self.make_archive()
        (package / "source.pdf").write_bytes(b"%PDF-1.7\nchanged fixture\n")
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("ARCHIVE_PDF_HASH", self.codes(report))

    def test_archive_identity_conflict_and_outside_fulltext_are_rejected(self):
        self.make_archive()
        self.note(metadata=self.metadata(material_status="parsed", fulltext_path="03fulltext/users/0/EFGH5678/full.md", zotero_key="IJKL1234"))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("ARCHIVE_IDENTITY", self.codes(report))
        self.note(metadata=self.metadata(material_status="parsed", fulltext_path="../outside.md"))
        self.assertIn("FULLTEXT_PATH", self.codes(self.run_check()[1]))

    def test_parsed_status_requires_an_actual_package(self):
        self.note(metadata=self.metadata(material_status="parsed", fulltext_path=None))
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("FULLTEXT_REQUIRED", self.codes(report))

    def test_latex_reference_keys_match_local_bibliography(self):
        directory = self.vault / "05writing/paper"
        directory.mkdir()
        tex = directory / "main.tex"
        tex.write_text(r"A claim \cite{known}.\bibliography{references}", encoding="utf-8")
        (directory / "references.bib").write_text("@article{known, title={Synthetic fixture}}\n", encoding="utf-8")
        self.assertEqual(self.run_check()[0], 0)
        tex.write_text(r"A claim \cite{unknown}.\bibliography{references}", encoding="utf-8")
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("CITEKEY_MISSING", self.codes(report))

    def test_profile_path_and_document_symlink_cannot_escape_vault(self):
        (self.vault / "research-profile.json").write_text(json.dumps({"paths": {"notes": "../outside"}}), encoding="utf-8")
        self.assertEqual(self.run_check()[0], 2)
        (self.vault / "research-profile.json").unlink()
        outside = self.root / "private.md"
        outside.write_text("not a vault document", encoding="utf-8")
        (self.vault / "02vault/linked.md").symlink_to(outside)
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("DOCUMENT_READ", self.codes(report))

    def test_document_symlink_loop_is_reported_without_traceback(self):
        (self.vault / "02vault/loop.md").symlink_to("loop.md")
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("DOCUMENT_READ", self.codes(report))

    def test_implicit_bibliography_symlink_cannot_escape_vault(self):
        outside = self.root / "private.bib"
        outside.write_text("@article{private, title={private fixture}}", encoding="utf-8")
        directory = self.vault / "05writing/paper"
        directory.mkdir()
        (directory / "main.tex").write_text(r"A claim \cite{private}.", encoding="utf-8")
        (directory / "references.bib").symlink_to(outside)
        code, report = self.run_check()
        self.assertEqual(code, 1, report)
        self.assertIn("BIB_MISSING", self.codes(report))


if __name__ == "__main__":
    unittest.main()
