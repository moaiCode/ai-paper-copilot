#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隔离验证诊断的配置漂移、未知状态与敏感信息保护。

所有 Zotero 偏好和 XPI 都在临时目录构造；登录状态与网络探测全部 mock，
测试不会启动应用、读取真实 Token、修改用户配置或提交 PDF。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import doctor


class DoctorTests(unittest.TestCase):
    def setUp(self):
        """准备独立 Vault、Zotero profile 和只含测试默认值的本地 XPI。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.vault = self.root / "Vault"
        self.vault.mkdir()
        (self.vault / "AGENTS.md").write_text("测试库", encoding="utf-8")
        self.profile_dir = self.root / "ZoteroProfile"
        self.profile_dir.mkdir()
        self.addon_path = self.profile_dir / "llm.xpi"
        self.profile = {
            "zotero": {"api_base_url": "http://127.0.0.1:23119/api", "library_scope": "users/0"},
            "mineru": {"backend": "cloud", "automatic_parse": False},
        }
        self.write_profile()
        self.write_defaults({doctor.MINERU_MODE_PREF: "cloud", doctor.AUTO_PARSE_PREF: False})
        self.write_prefs({})
        self.write_addons()

    def write_profile(self):
        (self.vault / "research-profile.json").write_text(json.dumps(self.profile), encoding="utf-8")

    def write_addons(self):
        data = {"addons": [
            {"id": "better-bibtex@iris-advies.com", "active": True, "version": "test"},
            {"id": "zotero-llm@github.com.yilewang", "active": True,
             "version": "3.9.17-fixture", "path": str(self.addon_path)},
        ]}
        (self.profile_dir / "extensions.json").write_text(json.dumps(data), encoding="utf-8")

    @staticmethod
    def pref_text(values, function):
        """JSON 编码保证字符串不会被当作 JavaScript 执行。"""
        return "\n".join('{}({}, {});'.format(function, json.dumps(key), json.dumps(value))
                         for key, value in values.items()) + "\n"

    def write_defaults(self, values):
        with zipfile.ZipFile(self.addon_path, "w") as archive:
            archive.writestr("prefs.js", self.pref_text(values, "pref"))

    def write_prefs(self, values):
        (self.profile_dir / "prefs.js").write_text(self.pref_text(values, "user_pref"), encoding="utf-8")

    def checks(self):
        """只让 inspect 访问隔离 profile；不调用真实 CLI 或 HTTP 服务。"""
        with patch.object(doctor, "zotero_profile", return_value=self.profile_dir), \
             patch.object(doctor.shutil, "which", return_value=None), \
             patch.object(doctor, "probe", return_value=True):
            return {item["name"]: item for item in doctor.inspect(self.vault)}

    def test_matching_explicit_preferences_are_reported(self):
        self.write_prefs({doctor.MINERU_MODE_PREF: "cloud", doctor.AUTO_PARSE_PREF: False})
        checks = self.checks()
        mode = checks["MinerU 插件有效后端"]
        auto = checks["MinerU 插件全局自动解析"]
        self.assertEqual(mode["status"], "configured")
        self.assertEqual(mode["actual_value"], "cloud")
        self.assertEqual(mode["preference_source"], "explicit")
        self.assertEqual(auto["status"], "configured")
        self.assertIs(auto["actual_value"], False)

    def test_mode_drift_is_required_setup(self):
        self.write_prefs({doctor.MINERU_MODE_PREF: "local", doctor.AUTO_PARSE_PREF: False})
        mode = self.checks()["MinerU 插件有效后端"]
        self.assertEqual(mode["status"], "mismatch")
        self.assertTrue(mode["required"])
        self.assertEqual((mode["actual_value"], mode["expected_value"]), ("local", "cloud"))

    def test_enabled_automatic_parse_cannot_be_reported_ready(self):
        self.write_prefs({doctor.MINERU_MODE_PREF: "cloud", doctor.AUTO_PARSE_PREF: True})
        auto = self.checks()["MinerU 插件全局自动解析"]
        self.assertEqual(auto["status"], "mismatch")
        self.assertTrue(auto["required"])
        self.assertIs(auto["actual_value"], True)
        # 验证总状态确实把该漂移判成 needs_setup，而非仅输出一条可忽略消息。
        stdout = io.StringIO()
        with patch.object(doctor, "inspect", return_value=[auto]), \
             patch.object(sys, "argv", ["doctor.py", "--vault", str(self.vault), "--json"]), \
             contextlib.redirect_stdout(stdout):
            code = doctor.main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "needs_setup")

    def test_absent_user_values_use_installed_defaults(self):
        checks = self.checks()
        for name in ("MinerU 插件有效后端", "MinerU 插件全局自动解析"):
            self.assertEqual(checks[name]["status"], "configured")
            self.assertEqual(checks[name]["preference_source"], "installed_default")
        self.assertIs(checks["MinerU 插件全局自动解析"]["actual_value"], False)

    def test_unavailable_defaults_are_unknown_not_assumed_safe(self):
        self.addon_path.unlink()
        checks = self.checks()
        for name in ("MinerU 插件有效后端", "MinerU 插件全局自动解析"):
            self.assertEqual(checks[name]["status"], "unknown")
            self.assertIsNone(checks[name]["actual_value"])
            self.assertTrue(checks[name]["required"])

    def test_invalid_explicit_values_do_not_fall_back_or_leak(self):
        secret = "fixture-sensitive-value-do-not-print"
        self.write_prefs({doctor.MINERU_MODE_PREF: secret, doctor.AUTO_PARSE_PREF: "false",
                          doctor.PREF_PREFIX + "mineruToken": secret})
        checks = self.checks()
        self.assertEqual(checks["MinerU 插件有效后端"]["status"], "invalid")
        self.assertEqual(checks["MinerU 插件全局自动解析"]["status"], "invalid")
        self.assertNotIn(secret, json.dumps(checks))
        self.assertNotIn(doctor.PREF_PREFIX + "mineruToken", doctor.selected_prefs(self.profile_dir / "prefs.js"))

    def test_malformed_explicit_json_is_invalid_not_default(self):
        (self.profile_dir / "prefs.js").write_text(
            'user_pref("' + doctor.AUTO_PARSE_PREF + '", not_json);\n', encoding="utf-8")
        actual = self.checks()["MinerU 插件全局自动解析"]
        self.assertEqual(actual["status"], "invalid")
        self.assertEqual(actual["preference_source"], "explicit")

    def test_missing_profile_intent_is_not_configured(self):
        self.profile["mineru"] = {"backend": None}
        self.write_profile()
        checks = self.checks()
        self.assertEqual(checks["MinerU 后端选择"]["status"], "not_configured")
        self.assertEqual(checks["MinerU 自动解析意图"]["status"], "not_configured")
        # 即使 XPI 有安全默认，也不会冒充用户已经作出了后端选择。
        self.assertEqual(checks["MinerU 插件有效后端"]["actual_value"], "cloud")

    def test_note_vault_match_and_mismatch_without_echoing_raw_path(self):
        self.write_prefs({doctor.VAULT_PATH_PREF: str(self.vault)})
        self.assertEqual(self.checks()["插件笔记 Vault"]["status"], "configured")
        other = "/fixture/other-vault-sensitive-name"
        self.write_prefs({doctor.VAULT_PATH_PREF: other})
        result = self.checks()["插件笔记 Vault"]
        self.assertEqual(result["status"], "mismatch")
        self.assertNotIn(other, json.dumps(result))

    def test_service_urls_reject_types_credentials_and_queries(self):
        invalid = ({}, [], None, "http://:secret@127.0.0.1/api",
                   "http://127.0.0.1/api?token=secret", "http://127.0.0.1/api#secret",
                   "http://127.0.0.1:bad/api", "http://127.0.0.1/api\nsecret")
        for value in invalid:
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError) as exc:
                doctor.validate_service_url(value, "api", local_only=True)
            self.assertNotIn("secret", str(exc.exception))

    def test_inspect_never_changes_fixture_inputs(self):
        self.write_prefs({doctor.MINERU_MODE_PREF: "local", doctor.AUTO_PARSE_PREF: True})
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.checks()
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
