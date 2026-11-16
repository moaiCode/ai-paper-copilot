#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖准备脚本 setup_env.py 的离线测试：只预览或验证错误路径。"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "ai-paper-setup/scripts/setup_env.py"
SPEC = importlib.util.spec_from_file_location("tested_setup_env", SCRIPT)
env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(env)


class SetupEnvTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paper-env-test-")
        self.addCleanup(self.temporary.cleanup)
        self.vault = Path(self.temporary.name).resolve() / "vault"
        self.skill = self.vault / ".agents/skills/ai-paper-copilot"
        self.skill.mkdir(parents=True)
        (self.skill / "requirements.txt").write_text("PyYAML==6.0.3\n", encoding="utf-8")

    def test_preview_lists_commands_without_creating_environment(self):
        result = env.plan(self.vault, sys.executable)
        self.assertEqual(result["status"], "preview")
        self.assertFalse(result["venv_exists"])
        self.assertFalse((self.vault / ".venv").exists())
        self.assertEqual(len(result["commands"]), 3)
        self.assertIn("-m", result["commands"][0])
        self.assertIn("import yaml", result["commands"][-1][-1])

    def test_missing_requirements_is_reported(self):
        (self.skill / "requirements.txt").unlink()
        with self.assertRaises(env.EnvError) as caught:
            env.plan(self.vault, sys.executable)
        self.assertEqual(caught.exception.code, "REQUIREMENTS_MISSING")

    def test_broken_environment_requires_recreate(self):
        (self.vault / ".venv").mkdir()
        with self.assertRaises(env.EnvError) as caught:
            env.apply_env(self.vault, sys.executable)
        self.assertEqual(caught.exception.code, "VENV_BROKEN")

    def test_missing_vault_is_reported(self):
        with self.assertRaises(env.EnvError) as caught:
            env.plan(self.vault / "absent", sys.executable)
        self.assertEqual(caught.exception.code, "VAULT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
