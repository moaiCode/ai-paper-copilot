#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线安装助手的隔离行为测试，不部署真实库，不访问应用、网络或凭据。

每项测试创建独立的最小套件副本和目标路径；真实发布测试只发生在临时目录。
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "ai-paper-setup/scripts/setup_vault.py"
SPEC = importlib.util.spec_from_file_location("tested_setup_vault", SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class SetupVaultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-setup-test-")
        self.addCleanup(self.temporary.cleanup)
        # macOS 的 /var 可能是符号链接；测试源与目标明确使用其实际路径。
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        self.template = self.repo / "ResearchVault"
        self.main_skill = self.repo / "skills/ai-paper-copilot"
        self.setup_skill = self.repo / "skills/ai-paper-setup"
        self.target = self.root / "formal" / "ResearchVault"
        self.profile = {"schema_version": 2,
                        "zotero": {"api_base_url": "http://127.0.0.1:23119/api", "library_scope": "users/0", "data_dir": None},
                        "integrations": {"llm_for_zotero": {"codex_app_server": None}},
                        "mineru": {"backend": None, "automatic_parse": False, "upload_policy": "ask_before_upload", "local_url": "http://127.0.0.1:8000"},
                        "paths": {"knowledge": "01knowledge", "notes": "02vault", "fulltext": "03fulltext", "projects": "04projects",
                                  "writing": "05writing", "inbox": "06inbox", "templates": "templates"}}
        for directory in self.profile["paths"].values():
            path = self.template / directory
            path.mkdir(parents=True)
            (path / ".gitkeep").write_text("", encoding="utf-8")
        (self.template / "AGENTS.md").write_text("# 测试 Vault\n人工内容保护规则。\n", encoding="utf-8")
        (self.template / ".gitignore").write_text(".env\n", encoding="utf-8")
        (self.template / ".hidden-template").write_text("保留隐藏模板", encoding="utf-8")
        self.write_profile()
        for directory in (self.main_skill, self.setup_skill):
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text("---\nname: fixture\ndescription: fixture\n---\n# 测试技能\n", encoding="utf-8")
        (self.main_skill / "templates").mkdir()
        (self.main_skill / "templates/阅读模板.md").write_text("---\ntype: literature-note\ntitle: '{{title}}'\n---\n", encoding="utf-8")
        shutil.copyfile(self.main_skill / "templates/阅读模板.md", self.template / "templates/阅读模板.md")
        # 两个位置的 gitkeep 也应属于同一模板集合，保证测试确实覆盖完整双份复制。
        (self.main_skill / "templates/.gitkeep").write_text("", encoding="utf-8")
        (self.setup_skill / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.setup_skill / "scripts/setup_vault.py")
        (self.main_skill / "references").mkdir()
        (self.main_skill / "references/.gitkeep").write_text("", encoding="utf-8")

    def write_profile(self):
        (self.template / "research-profile.json").write_text(json.dumps(self.profile), encoding="utf-8")

    def args(self, **changes):
        values = dict(vault=str(self.target), repo=str(self.repo), mineru_backend="unconfigured",
                      upload_policy="ask_before_upload", local_url="http://127.0.0.1:8000",
                      zotero_codex="unconfigured", apply=False, json=True)
        values.update(changes)
        return SimpleNamespace(**values)

    def snapshot(self):
        return {path.relative_to(self.repo).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.repo.rglob("*") if path.is_file() and not path.is_symlink()}

    def assert_rejected(self, code, **changes):
        with self.assertRaises(setup.SetupError) as error:
            setup.prepare(self.args(**changes))
        self.assertEqual(error.exception.code, code)
        return error.exception

    def assert_no_stage(self):
        self.assertFalse(list(self.root.rglob(".ai-paper-setup-*")))

    def test_preview_has_no_writes_even_when_parent_is_missing(self):
        before = self.snapshot()
        result = setup.prepare(self.args())
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["decisions"]["upload_policy"], "ask_before_upload")
        self.assertFalse(self.target.parent.exists())
        self.assertEqual(before, self.snapshot())
        self.assert_no_stage()

    def test_apply_copies_complete_template_and_two_real_skills(self):
        before = self.snapshot()
        result = setup.prepare(self.args(apply=True))
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["stage"], "files_prepared")
        for relative in self.profile["paths"].values():
            self.assertTrue((self.target / relative / ".gitkeep").is_file())
        self.assertEqual((self.target / ".hidden-template").read_text(encoding="utf-8"), "保留隐藏模板")
        self.assertEqual((self.target / ".gitignore").read_bytes(), (self.template / ".gitignore").read_bytes())
        for name in setup.SKILL_NAMES:
            installed = self.target / ".agents/skills" / name / "SKILL.md"
            self.assertTrue(installed.is_file())
            self.assertFalse(installed.is_symlink())
            self.assertEqual(installed.read_bytes(), (self.repo / "skills" / name / "SKILL.md").read_bytes())
        self.assertEqual((self.target / "templates/阅读模板.md").read_bytes(), (self.target / ".agents/skills/ai-paper-copilot/templates/阅读模板.md").read_bytes())
        self.assertIsNone(result["paths"]["entry"])
        self.assertFalse((self.target / "research-vault-entry.md").exists())
        self.assertEqual(before, self.snapshot())
        self.assert_no_stage()

    def test_default_profile_preserves_unbound_scope_and_disables_automation(self):
        setup.prepare(self.args(apply=True))
        profile = json.loads((self.target / "research-profile.json").read_text())
        self.assertIsNone(profile["zotero"]["data_dir"])
        self.assertEqual(profile["zotero"]["library_scope"], "users/0")
        self.assertIsNone(profile["mineru"]["backend"])
        self.assertFalse(profile["mineru"]["automatic_parse"])
        self.assertEqual(profile["mineru"]["upload_policy"], "ask_before_upload")
        self.assertIsNone(profile["integrations"]["llm_for_zotero"]["codex_app_server"])

    def test_zotero_codex_choice_is_recorded_without_credentials(self):
        setup.prepare(self.args(apply=True, zotero_codex="enabled"))
        profile = json.loads((self.target / "research-profile.json").read_text())
        state = json.loads((self.target / "setup-state.json").read_text())
        self.assertTrue(profile["integrations"]["llm_for_zotero"]["codex_app_server"])
        self.assertEqual(state["decisions"]["zotero_codex_app_server"], "enabled")
        self.assertNotIn("token", json.dumps(profile).lower())

    def test_zotero_codex_can_be_explicitly_disabled(self):
        setup.prepare(self.args(apply=True, zotero_codex="disabled"))
        profile = json.loads((self.target / "research-profile.json").read_text())
        state = json.loads((self.target / "setup-state.json").read_text())
        self.assertFalse(profile["integrations"]["llm_for_zotero"]["codex_app_server"])
        self.assertEqual(state["decisions"]["zotero_codex_app_server"], "disabled")
        self.assertIsNone(state["paths"]["entry"])
        self.assertFalse((self.target / "research-vault-entry.md").exists())

    def test_unconfigured_zotero_codex_does_not_create_bridge_entry(self):
        result = setup.prepare(self.args(apply=True, zotero_codex="unconfigured"))
        self.assertIsNone(result["paths"]["entry"])
        self.assertFalse((self.target / "research-vault-entry.md").exists())

    def test_explicit_backend_and_upload_decisions_are_recorded(self):
        setup.prepare(self.args(apply=True, mineru_backend="local", upload_policy="public_papers_only", local_url="https://mineru.example.org/api/"))
        profile = json.loads((self.target / "research-profile.json").read_text())
        self.assertEqual(profile["mineru"]["backend"], "local")
        self.assertEqual(profile["mineru"]["upload_policy"], "public_papers_only")
        self.assertEqual(profile["mineru"]["local_url"], "https://mineru.example.org/api")
        self.assertFalse(profile["mineru"]["automatic_parse"])

    def test_state_and_entry_report_only_files_prepared(self):
        git = self.repo / ".git"
        git.mkdir()
        (git / "HEAD").write_text("a" * 40 + "\n", encoding="utf-8")
        setup.prepare(self.args(apply=True, mineru_backend="cloud", zotero_codex="enabled"))
        state = json.loads((self.target / "setup-state.json").read_text())
        self.assertEqual(state["stage"], "files_prepared")
        self.assertEqual(state["checks"]["local_files"], "verified")
        self.assertTrue(all(state["checks"][name] == "pending" for name in setup.PENDING_CHECKS))
        self.assertFalse(state["decisions"]["automatic_upload"])
        self.assertEqual(state["source"]["repo"], str(self.repo))
        self.assertEqual(state["source"]["commit"], "a" * 40)
        self.assertEqual(state["source"]["commit_matches_snapshot"], "not_checked")
        entry = (self.target / "research-vault-entry.md").read_text(encoding="utf-8")
        for relative in ("AGENTS.md", "research-profile.json", ".agents/skills/ai-paper-copilot/SKILL.md"):
            self.assertIn(str(self.target / relative), entry)
        self.assertNotIn(str(self.template / "AGENTS.md"), entry)
        self.assertIn("Zotero 内 Codex App Server：`enabled`", entry)

    def test_unselected_mineru_is_not_marked_ready(self):
        setup.prepare(self.args(apply=True))
        state = json.loads((self.target / "setup-state.json").read_text())
        self.assertEqual(state["checks"]["mineru"], "not_selected")
        self.assertEqual(state["checks"]["sample_validation"], "pending")

    def test_local_state_and_secret_files_are_not_copied(self):
        for name in (".DS_Store", ".env", ".env.local"):
            (self.main_skill / name).write_text("fixture-private", encoding="utf-8")
        (self.main_skill / ".env.example").write_text("EXAMPLE=\n", encoding="utf-8")
        for name in (".git", ".venv", "__pycache__"):
            (self.main_skill / name).mkdir()
            (self.main_skill / name / "ignored.py").write_text("fixture", encoding="utf-8")
        setup.prepare(self.args(apply=True))
        installed = self.target / ".agents/skills/ai-paper-copilot"
        for name in (".DS_Store", ".env", ".env.local", ".git", ".venv", "__pycache__"):
            self.assertFalse((installed / name).exists())
        self.assertTrue((installed / ".env.example").is_file())

    def test_any_existing_target_is_rejected_without_changes(self):
        self.target.parent.mkdir()
        for kind in ("directory", "file", "broken_symlink"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    self.target.mkdir()
                elif kind == "file":
                    self.target.write_text("existing", encoding="utf-8")
                else:
                    self.target.symlink_to(self.root / "missing")
                self.assert_rejected("TARGET_EXISTS", apply=True)
                self.assertTrue(os.path.lexists(str(self.target)))
                if self.target.is_dir():
                    self.target.rmdir()
                else:
                    self.target.unlink()
        self.assert_no_stage()

    def test_placeholders_relative_and_traversal_paths_are_rejected(self):
        for raw in ("/用户确认的正式库绝对路径", "/请填写正式库绝对路径", "/path/to/MyVault", "/tmp/{{vault}}", "/tmp/<vault>"):
            with self.subTest(raw=raw):
                self.assert_rejected("TARGET_PLACEHOLDER", vault=raw)
        self.assertEqual(self.assert_rejected("TARGET_ABSOLUTE", vault="relative-vault").exit_code, 2)
        self.assert_rejected("TARGET_TRAVERSAL", vault=str(self.root) + "/new/../vault")

    def test_source_descendant_and_ancestor_targets_are_rejected(self):
        for target in (self.repo, self.repo / "new-vault", self.template, self.root):
            with self.subTest(target=target):
                self.assert_rejected("TARGET_IN_SOURCE", vault=str(target))

    def test_symlink_parent_is_rejected_before_writing(self):
        parent = self.root / "linked-parent"
        parent.symlink_to(self.root, target_is_directory=True)
        self.assert_rejected("SYMLINK_PATH", vault=str(parent / "new-vault"), apply=True)
        self.assertFalse((self.root / "new-vault").exists())

    def test_source_symlink_is_rejected_even_in_ignored_state(self):
        (self.main_skill / ".venv").symlink_to(self.root, target_is_directory=True)
        self.assert_rejected("SOURCE_SYMLINK", apply=True)
        self.assertFalse(self.target.parent.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "需要 POSIX FIFO 接口")
    def test_source_special_file_is_rejected_without_reading_it(self):
        os.mkfifo(str(self.main_skill / "fifo"))
        self.assert_rejected("SOURCE_SPECIAL_FILE", apply=True)
        self.assertFalse(self.target.parent.exists())

    def test_incomplete_source_and_template_drift_are_preflight_errors(self):
        (self.setup_skill / "SKILL.md").unlink()
        self.assertEqual(self.assert_rejected("SOURCE_INCOMPLETE", apply=True).exit_code, 2)
        (self.setup_skill / "SKILL.md").write_text("fixture", encoding="utf-8")
        (self.template / "templates/阅读模板.md").write_text("different", encoding="utf-8")
        self.assert_rejected("SOURCE_TEMPLATE_MISMATCH", apply=True)
        self.assertFalse(self.target.parent.exists())

    def test_bound_or_credential_template_profile_is_not_copied(self):
        self.profile["zotero"]["data_dir"] = "/fixture/private-data"
        self.write_profile()
        self.assert_rejected("SOURCE_BOUND", apply=True)
        self.profile["zotero"]["data_dir"] = None
        self.profile["integrations"]["llm_for_zotero"]["codex_app_server"] = True
        self.write_profile()
        self.assert_rejected("SOURCE_BOUND", apply=True)
        self.profile["integrations"]["llm_for_zotero"]["codex_app_server"] = None
        self.profile["mineru"]["backend"] = "cloud"
        self.write_profile()
        self.assert_rejected("SOURCE_BOUND", apply=True)
        self.profile["mineru"]["backend"] = None
        self.profile["mineru"]["automatic_parse"] = True
        self.write_profile()
        self.assert_rejected("SOURCE_BOUND", apply=True)
        self.profile["mineru"]["automatic_parse"] = False
        self.profile["mineru"]["upload_policy"] = "public_papers_only"
        self.write_profile()
        self.assert_rejected("SOURCE_BOUND", apply=True)
        self.profile["mineru"]["upload_policy"] = "ask_before_upload"
        self.profile["mineru"]["token"] = "fixture-sensitive-token"
        self.write_profile()
        self.assert_rejected("SOURCE_CREDENTIALS", apply=True)
        self.assertFalse(self.target.parent.exists())

    def test_prior_setup_state_in_template_is_rejected(self):
        (self.template / "setup-state.json").write_text("{}", encoding="utf-8")
        self.assert_rejected("SOURCE_NOT_INITIAL", apply=True)

    def test_template_app_state_and_real_research_content_are_not_copied(self):
        for name in (".obsidian", ".agents", ".git"):
            with self.subTest(state=name):
                state = self.template / name
                state.mkdir()
                self.assert_rejected("SOURCE_NOT_INITIAL", apply=True)
                state.rmdir()
        for kind in ("fulltext", "projects", "writing", "inbox", "notes"):
            with self.subTest(kind=kind):
                real = self.template / self.profile["paths"][kind] / "private-reading.md"
                real.write_text("private fixture", encoding="utf-8")
                self.assert_rejected("SOURCE_NOT_INITIAL", apply=True)
                real.unlink()
        self.assertFalse(self.target.parent.exists())

    def test_initial_template_checks_follow_custom_profile_paths(self):
        custom = self.template / "自定义全文"
        custom.mkdir()
        (custom / ".gitkeep").write_text("", encoding="utf-8")
        self.profile["paths"]["fulltext"] = "自定义全文"
        self.write_profile()
        self.assertEqual(setup.prepare(self.args())["status"], "preview")
        (custom / "real-paper.md").write_text("private fixture", encoding="utf-8")
        self.assert_rejected("SOURCE_NOT_INITIAL", apply=True)

    @unittest.skipUnless(sys.platform == "darwin", "macOS 系统别名的实际平台检查")
    def test_confirmed_macos_tmp_and_var_aliases_use_canonical_target(self):
        for alias, expected in (("/tmp", "/private/tmp"), ("/var", "/private/var")):
            with self.subTest(alias=alias):
                if not Path(alias).is_symlink() or os.readlink(alias) not in {expected, expected.lstrip("/")}:
                    continue
                # /private/var 根目录通常不可写；/var/tmp 是其公开可写的稳定子目录。
                writable_base = Path(expected) / "tmp" if alias == "/var" else Path(expected)
                directory = tempfile.TemporaryDirectory(prefix="paper-system-alias-", dir=str(writable_base))
                self.addCleanup(directory.cleanup)
                canonical = Path(directory.name).resolve() / "formal-vault"
                raw = str(Path(alias) / canonical.relative_to(expected))
                result = setup.prepare(self.args(vault=raw, apply=True))
                self.assertEqual(result["status"], "created")
                self.assertEqual(result["paths"]["vault"], str(canonical))
                self.assertTrue((canonical / "setup-state.json").is_file())

    def test_copy_failure_cleans_only_its_own_stage_and_new_parents(self):
        before = self.snapshot()
        with patch.object(setup, "copy_selected", side_effect=OSError("injected copy failure")):
            with self.assertRaises(OSError):
                setup.prepare(self.args(apply=True))
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.parent.exists())
        self.assertEqual(before, self.snapshot())
        self.assert_no_stage()

    def test_state_write_failure_leaves_no_partial_vault(self):
        write = Path.write_text

        def fail_state(path, *args, **kwargs):
            if path.name == "setup-state.json":
                raise OSError("injected state write failure")
            return write(path, *args, **kwargs)

        with patch.object(Path, "write_text", new=fail_state):
            with self.assertRaises(OSError):
                setup.prepare(self.args(apply=True))
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.parent.exists())
        self.assert_no_stage()

    def test_publish_failure_is_cleaned_without_unsafe_fallback(self):
        error = setup.SetupError("PUBLISH_UNSUPPORTED", "injected unsupported publisher", 2)
        with patch.object(setup, "publish_noreplace", side_effect=error):
            self.assertEqual(self.assert_rejected("PUBLISH_UNSUPPORTED", apply=True).exit_code, 2)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.parent.exists())
        self.assert_no_stage()

    def test_concurrently_created_nonempty_target_is_preserved(self):
        publish = setup.publish_noreplace

        def create_competitor(stage, target):
            target.mkdir()
            (target / "human.md").write_text("concurrent human content", encoding="utf-8")
            publish(stage, target)

        with patch.object(setup, "publish_noreplace", side_effect=create_competitor):
            self.assert_rejected("TARGET_EXISTS", apply=True)
        self.assertEqual((self.target / "human.md").read_text(), "concurrent human content")
        self.assertEqual(list(self.target.iterdir()), [self.target / "human.md"])
        self.assert_no_stage()

    def test_concurrently_created_empty_target_is_not_replaced(self):
        publish = setup.publish_noreplace
        inode = []

        def create_competitor(stage, target):
            target.mkdir()
            inode.append(target.stat().st_ino)
            publish(stage, target)

        with patch.object(setup, "publish_noreplace", side_effect=create_competitor):
            self.assert_rejected("TARGET_EXISTS", apply=True)
        self.assertEqual(self.target.stat().st_ino, inode[0])
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_no_stage()

    def test_parent_creation_failure_recovers_own_empty_ancestors(self):
        target = self.root / "new-one" / "new-two" / "vault"
        mkdir = Path.mkdir

        def fail_second(path, *args, **kwargs):
            if path.name == "new-two":
                raise OSError("injected mkdir failure")
            return mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=fail_second):
            with self.assertRaises(OSError):
                setup.prepare(self.args(vault=str(target), apply=True))
        self.assertFalse((self.root / "new-one").exists())

    def test_local_url_rejects_credentials_query_fragment_and_controls(self):
        for url in ("http://user:secret@example.org", "http://localhost:8000?token=secret", "http://localhost:8000#secret", "http://localhost:bad", "http://localhost:8000\n"):
            with self.subTest(url=url):
                error = self.assert_rejected("LOCAL_URL", local_url=url)
                self.assertNotIn("secret", str(error))

    def test_cli_unknown_credential_argument_is_rejected_without_echoing_it(self):
        secret = "fixture-do-not-print-this-token"
        process = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.target), "--repo", str(self.repo),
                                  "--token", secret, "--json"], capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(json.loads(process.stdout)["status"], "error")
        self.assertNotIn(secret, process.stdout + process.stderr)
        self.assertFalse(self.target.parent.exists())

    def test_cli_invalid_zotero_codex_choice_is_rejected(self):
        process = subprocess.run([sys.executable, str(SCRIPT), "--vault", str(self.target), "--repo", str(self.repo),
                                  "--zotero-codex", "maybe", "--json"], capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 2)
        report = json.loads(process.stdout)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["issues"][0]["code"], "ARGUMENTS")
        self.assertNotIn("maybe", process.stdout + process.stderr)
        self.assertFalse(self.target.parent.exists())

    def test_cli_default_repo_and_preview_use_fixture_script_location(self):
        script = self.setup_skill / "scripts/setup_vault.py"
        process = subprocess.run([sys.executable, str(script), "--vault", str(self.target), "--json"], capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "preview")
        self.assertFalse(self.target.parent.exists())


if __name__ == "__main__":
    unittest.main()
