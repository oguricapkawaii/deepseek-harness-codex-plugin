from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import json

from deepseek_coding_agent.harness import (
    DEFAULT_HARNESS_HOME,
    MAX_TASK_CHARS,
    HarnessLayout,
    build_task,
    model_override,
    validate_workspace,
)


class HarnessTests(unittest.TestCase):
    def test_task_adds_workspace_and_git_safety_rules(self) -> None:
        prompt = build_task("Fix the parser and run its tests")
        self.assertIn("Work only inside the current workspace", prompt)
        self.assertIn("Do not commit, push", prompt)
        self.assertTrue(prompt.endswith("Fix the parser and run its tests"))

    def test_task_rejects_empty_and_oversized_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            build_task("  ")
        with self.assertRaisesRegex(ValueError, "character limit"):
            build_task("x" * (MAX_TASK_CHARS + 1))

    def test_workspace_allowlist_is_enforced(self) -> None:
        allowed = ROOT / "tests"
        outside = ROOT / "src"
        harness = ROOT / "not-the-harness-installation"
        data_home = ROOT / "not-the-data-home"
        plugin = ROOT / "not-the-plugin-root"
        with patch.dict(os.environ, {"DEEPSEEK_HARNESS_ALLOWED_ROOTS": str(allowed)}, clear=False):
            self.assertEqual(
                validate_workspace(
                    str(allowed), harness_home=harness, data_home=data_home, plugin_root=plugin
                ),
                allowed.resolve(),
            )
            with self.assertRaisesRegex(ValueError, "outside DEEPSEEK_HARNESS_ALLOWED_ROOTS"):
                validate_workspace(
                    str(outside), harness_home=harness, data_home=data_home, plugin_root=plugin
                )

    def test_harness_installation_is_rejected_as_workspace(self) -> None:
        target = ROOT / "src"
        harness = ROOT
        data_home = ROOT / "not-the-data-home"
        plugin = ROOT / "not-the-plugin-root"
        with patch.dict(os.environ, {"DEEPSEEK_HARNESS_ALLOWED_ROOTS": ""}, clear=False):
            with self.assertRaisesRegex(ValueError, "Harness installation"):
                validate_workspace(
                    str(target), harness_home=harness, data_home=data_home, plugin_root=plugin
                )

    def test_data_home_is_rejected_as_workspace(self) -> None:
        target = ROOT / "tests"
        with patch.dict(os.environ, {"DEEPSEEK_HARNESS_ALLOWED_ROOTS": ""}, clear=False):
            with self.assertRaisesRegex(ValueError, "isolated Harness data"):
                validate_workspace(
                    str(target),
                    harness_home=ROOT / "not-the-harness-installation",
                    data_home=ROOT,
                    plugin_root=ROOT / "not-the-plugin-root",
                )

    def test_model_override_is_per_run_and_preserves_other_settings(self) -> None:
        data_home = ROOT / "tests" / "tmp-model-home"
        data_home.mkdir(exist_ok=True)
        settings_path = data_home / "settings.yaml"
        settings_path.write_text("ui-conversation:\n  busyEnter: steer\n", encoding="utf-8")
        install_home = DEFAULT_HARNESS_HOME.resolve()
        layout = HarnessLayout(
            install_home,
            data_home,
            install_home / "resources" / "runtime" / "node.exe",
            install_home / "resources" / "runtime" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js",
        )
        try:
            with model_override(layout, "deepseek-v4-pro", "max") as (model, effort, patch_path):
                self.assertEqual(model, "deepseek-v4-pro")
                self.assertEqual(effort, "max")
                patch_data = json.loads(patch_path.read_text(encoding="utf-8"))
                temp_settings = Path(patch_data[0]["config"]["path"])
                values = json.loads(temp_settings.read_text(encoding="utf-8"))
                self.assertEqual(values["agent-default-model"]["model"], "deepseek-v4-pro")
                self.assertEqual(values["agent-default-model"]["reasoningEffort"], "max")
                self.assertEqual(values["ui-conversation"]["busyEnter"], "steer")
            self.assertFalse(patch_path.exists())
            self.assertNotIn("agent-default-model", settings_path.read_text(encoding="utf-8"))
        finally:
            if settings_path.exists():
                settings_path.unlink()
            runtime_dir = data_home / ".mcp-runtime"
            if runtime_dir.exists():
                runtime_dir.rmdir()
            if data_home.exists():
                data_home.rmdir()


if __name__ == "__main__":
    unittest.main()
