#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全文导出器的隔离行为测试，不接触真实 Zotero、网络或解析服务。

所有输入均为 TemporaryDirectory 中的合成缓存；小型 PDF 只测试复制与指纹，
不把测试通过解释为 PDF 排版、OCR 或科学结论已得到验证。
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_fulltext.py"


class ExportFulltextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-copilot-export-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.vault = self.root / "vault"
        self.cache = self.root / "cache" / "42"
        self.vault.mkdir()
        self.cache.mkdir(parents=True)
        self.pdf = self.root / "original.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\nsynthetic fixture, not a parser test\n")
        (self.cache / "full.md").write_text("# A paper\n\nOriginal extracted text.\n", encoding="utf-8")
        self.write_json(self.cache / "_llm_source.json", {
            "kind": "llm-for-zotero/mineru-cache-source", "version": 2,
            "attachmentId": 42, "attachmentKey": "EFGH5678", "parentItemKey": "ABCD1234"})
        self.target = self.vault / "03fulltext/users/0/EFGH5678"

    @staticmethod
    def write_json(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def command(self, *extra, omit=None):
        arguments = {"--vault": str(self.vault), "--cache-dir": str(self.cache), "--source-pdf": str(self.pdf)}
        if omit:
            arguments.pop(omit)
        command = [sys.executable, str(SCRIPT), "--json"]
        for key, value in arguments.items():
            command.extend([key, value])
        command.extend(extra)
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        try:
            result = json.loads(process.stdout)
        except ValueError:
            self.fail(f"脚本未返回 JSON：{process.stdout!r}；stderr={process.stderr!r}")
        self.assertNotIn("Traceback", process.stderr)
        return process.returncode, result

    def assert_error(self, expected_code, *extra, exit_code=1):
        code, result = self.command(*extra)
        self.assertEqual(code, exit_code, result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["issues"][0]["code"], expected_code)
        return result

    def package_json(self):
        return json.loads((self.target / "provenance.json").read_text(encoding="utf-8"))

    def cache_snapshot(self):
        return {path.relative_to(self.cache).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.cache.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_create_self_contained_package_without_changing_source(self):
        before = self.cache_snapshot()
        source_before = self.pdf.read_bytes()
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["fulltext_path"], "03fulltext/users/0/EFGH5678/full.md")
        self.assertEqual((self.target / "full.md").read_bytes(), (self.cache / "full.md").read_bytes())
        self.assertEqual((self.target / "source.pdf").read_bytes(), source_before)
        data = self.package_json()
        self.assertEqual(data["library_scope"], "users/0")
        self.assertEqual(data["zotero_key"], "ABCD1234")
        self.assertEqual(data["pdf_key"], "EFGH5678")
        self.assertEqual(data["source_pdf"]["sha256"], hashlib.sha256(source_before).hexdigest())
        self.assertFalse(data["quality_verified"])
        self.assertFalse(data["source_association_verified"])
        self.assertEqual(before, self.cache_snapshot())

    def test_images_and_explicit_zero_based_page_indices(self):
        (self.cache / "images").mkdir()
        (self.cache / "images/figure.png").write_bytes(b"synthetic image bytes")
        markdown = "# Paper\n\n![Figure 1](images/figure.png)\n"
        (self.cache / "full.md").write_text(markdown, encoding="utf-8")
        self.write_json(self.cache / "content_list.json", [
            {"type": "text", "text": "Title", "page_idx": 0},
            {"type": "image", "img_path": "images/figure.png", "page_idx": 2}])
        self.write_json(self.cache / "manifest.json", {"allFigures": [{"path": "images/figure.png", "page": 2}]})
        code, result = self.command()
        self.assertEqual(code, 0, result)
        data = self.package_json()
        self.assertEqual([row["pdf_physical_page"] for row in data["page_mapping"]["entries"]], [1, 3])
        self.assertEqual(data["images"][0]["locations"][0]["pdf_physical_page"], 3)
        self.assertTrue(data["images"][0]["referenced_in_markdown"])
        self.assertIn("PDF 物理页 3", (self.target / "assets.md").read_text(encoding="utf-8"))
        self.assertEqual((self.target / "full.md").read_text(encoding="utf-8"), markdown)

    def test_plain_manifest_page_is_not_assumed_to_be_zero_based(self):
        self.write_json(self.cache / "manifest.json", {"sections": [{"heading": "Method", "page": 4}]})
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertIn("PAGE_MAPPING_MISSING", {row["code"] for row in result["issues"]})
        self.assertEqual(self.package_json()["page_mapping"]["entries"], [])

    def test_invalid_page_indices_are_not_converted(self):
        self.write_json(self.cache / "content_list.json", [{"page_idx": -1}, {"page_idx": True}, {"page_idx": "4"}])
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertIn("INVALID_PAGE_INDEX", {row["code"] for row in result["issues"]})
        self.assertEqual(self.package_json()["page_mapping"]["entries"], [])

    def test_dry_run_does_not_create_anything(self):
        before = self.cache_snapshot()
        code, result = self.command("--dry-run")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(list(self.vault.iterdir()), [])
        self.assertEqual(before, self.cache_snapshot())

    def test_repeat_is_unchanged_including_export_timestamp(self):
        self.assertEqual(self.command()[0], 0)
        original = (self.target / "provenance.json").read_bytes()
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual((self.target / "provenance.json").read_bytes(), original)

    def test_changed_cache_needs_replace_and_preview_remains_read_only(self):
        self.command()
        previous = (self.target / "full.md").read_bytes()
        (self.cache / "full.md").write_text("New extracted content\n", encoding="utf-8")
        self.assert_error("PACKAGE_CHANGED")
        self.assertEqual((self.target / "full.md").read_bytes(), previous)
        code, preview = self.command("--dry-run")
        self.assertEqual(code, 0, preview)
        self.assertEqual(preview["planned_action"], "replace")
        self.assertIn("REPLACE_REQUIRED", {row["code"] for row in preview["issues"]})
        self.assertEqual((self.target / "full.md").read_bytes(), previous)
        code, result = self.command("--replace")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "replaced")
        self.assertEqual((self.target / "full.md").read_text(encoding="utf-8"), "New extracted content\n")
        self.assertFalse(any(path.name.startswith(".") for path in self.target.parent.iterdir()))

    def test_changed_pdf_needs_replace(self):
        self.command()
        self.pdf.write_bytes(b"%PDF-1.7\nchanged PDF fixture\n")
        self.assert_error("PACKAGE_CHANGED")
        self.assertEqual(self.command("--replace")[1]["status"], "replaced")

    def test_missing_fulltext_and_pdf_have_resource_exit_code(self):
        (self.cache / "full.md").unlink()
        self.assert_error("FULLTEXT_MISSING", exit_code=2)
        self.pdf.unlink()
        self.assert_error("PDF_MISSING", exit_code=2)

    def test_empty_or_non_utf8_fulltext_is_rejected(self):
        (self.cache / "full.md").write_text(" \n", encoding="utf-8")
        self.assert_error("FULLTEXT_EMPTY")
        (self.cache / "full.md").write_bytes(b"\xff\xfe")
        self.assert_error("FULLTEXT_ENCODING")

    def test_non_pdf_source_is_rejected(self):
        self.pdf.write_text("This is not PDF", encoding="utf-8")
        self.assert_error("INVALID_PDF")

    def test_identity_conflict_and_invalid_key_are_rejected(self):
        self.assert_error("IDENTITY_CONFLICT", "--attachment-key", "ZZZZ9999")
        self.assert_error("IDENTITY_CONFLICT", "--parent-key", "ZZZZ9999")
        self.write_json(self.cache / "_llm_source.json", {"attachmentKey": "../escape"})
        self.assert_error("INVALID_KEY")

    def test_missing_source_identity_can_be_provided_explicitly(self):
        (self.cache / "_llm_source.json").unlink()
        self.assert_error("MISSING_IDENTITY")
        code, result = self.command("--attachment-key", "EFGH5678", "--parent-key", "ABCD1234")
        self.assertEqual(code, 0, result)
        self.assertIn("SOURCE_METADATA_MISSING", {row["code"] for row in result["issues"]})

    def test_missing_parent_is_temporary_not_fabricated(self):
        self.write_json(self.cache / "_llm_source.json", {"attachmentKey": "EFGH5678"})
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertIsNone(self.package_json()["zotero_key"])
        self.assertIn("PARENT_IDENTITY_MISSING", {row["code"] for row in result["issues"]})

    def test_scope_rejects_traversal_absolute_and_ambiguous_values(self):
        for scope in ("../escape", "/users/0", "users/0/../other", "users\\0", "groups/0", "users/00"):
            with self.subTest(scope=scope):
                self.assert_error("INVALID_SCOPE", "--library-scope", scope)
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_configurable_fulltext_path_stays_in_vault(self):
        self.write_json(self.vault / "research-profile.json", {"paths": {"fulltext": "全文资料"}})
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertTrue((self.vault / "全文资料/users/0/EFGH5678/full.md").is_file())
        self.write_json(self.vault / "research-profile.json", {"paths": {"fulltext": "../escape"}})
        self.assert_error("UNSAFE_PATH")

    def test_symlink_in_cache_is_rejected_even_if_unselected(self):
        (self.cache / "extra.bin").symlink_to(self.pdf)
        self.assert_error("CACHE_SYMLINK")
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_cache_root_symlink_is_rejected(self):
        link = self.root / "linked-cache"
        link.symlink_to(self.cache, target_is_directory=True)
        self.cache = link
        self.assert_error("CACHE_SYMLINK")

    def test_symlinked_output_directory_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.vault / "03fulltext").symlink_to(outside, target_is_directory=True)
        self.assert_error("OUTPUT_SYMLINK")
        self.assertEqual(list(outside.iterdir()), [])

    def test_unowned_existing_target_is_never_replaced(self):
        self.target.mkdir(parents=True)
        (self.target / "my-note.md").write_text("human content", encoding="utf-8")
        self.assert_error("UNOWNED_TARGET", "--replace")
        self.assertEqual((self.target / "my-note.md").read_text(encoding="utf-8"), "human content")

    def test_extra_user_file_prevents_replacement(self):
        self.command()
        (self.target / "my-note.md").write_text("human content", encoding="utf-8")
        self.assert_error("UNOWNED_TARGET_FILES", "--replace")

    def test_corrupted_export_is_not_reported_unchanged_and_can_be_repaired(self):
        self.command()
        (self.target / "full.md").write_text("corrupt", encoding="utf-8")
        self.assert_error("PACKAGE_CHANGED")
        code, result = self.command("--replace")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "replaced")

    def test_target_provenance_symlink_is_not_followed(self):
        self.target.mkdir(parents=True)
        (self.target / "provenance.json").symlink_to(self.pdf)
        self.assert_error("TARGET_SYMLINK", "--replace")

    def test_missing_remote_and_external_local_images_are_reported(self):
        (self.cache / "full.md").write_text(
            "# Paper\n![missing](images/missing.png)\n![remote](https://example.org/image.png)\n"
            "![outside](../../private.png)\n", encoding="utf-8")
        code, result = self.command()
        self.assertEqual(code, 0, result)
        codes = {row["code"] for row in result["issues"]}
        self.assertTrue({"IMAGE_MISSING", "EXTERNAL_IMAGE", "IMAGE_OUTSIDE_CACHE"}.issubset(codes))
        self.assertFalse(self.package_json()["quality_verified"])

    def test_source_output_overlap_is_rejected(self):
        self.write_json(self.vault / "research-profile.json", {"paths": {"fulltext": "cache/42/output"}})
        # 把源缓存移入 vault，确保输出会落入源目录的情形确实被识别。
        moved = self.vault / "cache" / "42"
        moved.parent.mkdir()
        self.cache.rename(moved)
        self.cache = moved
        self.assert_error("SOURCE_OUTPUT_OVERLAP")
        self.assertFalse((moved / "output").exists())

    def test_multiple_attachments_and_group_scope_have_separate_packages(self):
        self.command()
        self.write_json(self.cache / "_llm_source.json", {"attachmentKey": "IJKL1234", "parentItemKey": "ABCD1234"})
        code, result = self.command("--library-scope", "groups/123")
        self.assertEqual(code, 0, result)
        self.assertTrue(self.target.is_dir())
        self.assertTrue((self.vault / "03fulltext/groups/123/IJKL1234/full.md").is_file())

    def test_malformed_image_uri_is_warning_not_traceback(self):
        (self.cache / "full.md").write_text("# Paper\n![bad](https://[bad)\n![null](images/%00.png)\n", encoding="utf-8")
        code, result = self.command()
        self.assertEqual(code, 0, result)
        self.assertIn("INVALID_IMAGE_REFERENCE", {row["code"] for row in result["issues"]})

    def test_failure_during_commit_restores_previous_generated_package(self):
        self.command()
        previous = {path.relative_to(self.target).as_posix(): path.read_bytes()
                    for path in self.target.rglob("*") if path.is_file()}
        (self.cache / "full.md").write_text("New cache content\n", encoding="utf-8")
        specification = importlib.util.spec_from_file_location("tested_fulltext_exporter", SCRIPT)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        args = SimpleNamespace(vault=str(self.vault), cache_dir=str(self.cache), source_pdf=str(self.pdf),
                               library_scope="users/0", parent_key=None, attachment_key=None,
                               converter_version="unknown", replace=True, dry_run=False)
        rename = Path.rename

        def fail_stage_commit(path, target):
            if path.name.startswith(".EFGH5678.export-") and Path(target).resolve() == self.target.resolve():
                raise OSError("injected rename failure for rollback test")
            return rename(path, target)

        # 在旧包已移入备份后模拟新包提交失败，检查真正的回滚分支。
        with mock.patch.object(module.Path, "rename", new=fail_stage_commit):
            with self.assertRaises(OSError):
                module.export(args)
        current = {path.relative_to(self.target).as_posix(): path.read_bytes()
                   for path in self.target.rglob("*") if path.is_file()}
        self.assertEqual(previous, current)
        self.assertFalse(any(path.name.startswith(".") for path in self.target.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
