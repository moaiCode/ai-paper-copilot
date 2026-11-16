#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""升级助手 sync_skills.py 的离线测试：只操作临时库。"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "ai-paper-setup/scripts/sync_skills.py"
SPEC = importlib.util.spec_from_file_location("tested_sync_skills", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def write_skill(directory, version, extra=""):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        "---\nname: {}\ndescription: 测试\nmetadata:\n  version: \"{}\"\n---\n# 技能\n{}".format(
            directory.name, version, extra), encoding="utf-8")


class SyncSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-sync-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo, self.vault = self.root / "repo", self.root / "vault"
        for name, version in (("ai-paper-copilot", "2.2.0"), ("ai-paper-setup", "1.2.0")):
            write_skill(self.repo / "skills" / name, version)
        for name, version in (("ai-paper-copilot", "2.1.0"), ("ai-paper-setup", "1.1.0")):
            write_skill(self.vault / ".agents/skills" / name, version)
        (self.vault / ".agents/skills/ai-paper-copilot/old.md").write_text("旧文件", encoding="utf-8")
        (self.vault / "research-vault-entry.md").write_text("旧入口", encoding="utf-8")
        (self.vault / "research-profile.json").write_text(json.dumps({
            "schema_version": 2, "zotero": {"library_scope": "users/0"},
            "integrations": {"llm_for_zotero": {"codex_app_server": False}}}), encoding="utf-8")

    def test_preview_reports_changes_and_legacy_without_writing(self):
        result = sync.plan(self.vault, self.repo)
        self.assertEqual(result["status"], "preview")
        copilot = result["skills"][0]
        self.assertEqual(copilot["installed_version"], "2.1.0")
        self.assertEqual(copilot["source_version"], "2.2.0")
        self.assertTrue(copilot["needs_update"])
        self.assertIn("SKILL.md", copilot["changed"])
        self.assertIn("old.md", copilot["removed"])
        codes = {item["code"] for item in result["legacy"]}
        self.assertEqual(codes, {"LEGACY_ENTRY_FILE", "LEGACY_PROFILE_KEYS"})
        self.assertEqual((self.vault / ".agents/skills/ai-paper-copilot/SKILL.md").read_text(
            encoding="utf-8").count("2.1.0"), 1)

    def test_apply_updates_copies_and_keeps_backup(self):
        result = sync.apply_skills(self.vault, self.repo, sync.plan(self.vault, self.repo))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(sync.skill_version(self.vault / ".agents/skills/ai-paper-copilot"), "2.2.0")
        self.assertEqual(sync.skill_version(self.vault / ".agents/skills/ai-paper-setup"), "1.2.0")
        self.assertFalse((self.vault / ".agents/skills/ai-paper-copilot/old.md").exists())
        backups = list((self.vault / ".agents/skill-backups").rglob("SKILL.md"))
        self.assertEqual(len(backups), 2)
        self.assertEqual(sync.plan(self.vault, self.repo)["skills"][0]["needs_update"], False)

    def test_clean_legacy_removes_entry_and_profile_field_only(self):
        cleaned = sync.clean_legacy(self.vault)
        self.assertEqual(len(cleaned), 2)
        self.assertFalse((self.vault / "research-vault-entry.md").exists())
        profile = json.loads((self.vault / "research-profile.json").read_text(encoding="utf-8"))
        self.assertNotIn("integrations", profile)
        self.assertEqual(profile["zotero"]["library_scope"], "users/0")
        self.assertTrue(any((self.vault).glob("research-profile.json.bak-*")))
        self.assertEqual(sync.legacy_report(self.vault), [])

    def test_symlinked_skill_is_refused(self):
        installed = self.vault / ".agents/skills/ai-paper-copilot"
        outside = self.root / "outside"
        installed.rename(outside)
        installed.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(sync.SyncError) as caught:
            sync.apply_skills(self.vault, self.repo, sync.plan(self.vault, self.repo))
        self.assertEqual(caught.exception.code, "SKILL_IS_SYMLINK")

    def test_missing_vault_is_reported(self):
        with self.assertRaises(sync.SyncError) as caught:
            sync.plan(self.root / "absent", self.repo)
        self.assertEqual(caught.exception.code, "VAULT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
