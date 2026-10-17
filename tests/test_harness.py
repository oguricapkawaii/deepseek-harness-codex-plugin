from __future__ import annotations

import os
import asyncio
import sys
import tempfile
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
    _normalize_model,
    parse_run_events,
    _run_capture,
    validate_workspace,
)


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_stops_owned_process(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "owned workers stopped"):
            await _run_capture([sys.executable, "-c", "import time; time.sleep(30)"], ROOT, os.environ.copy(), 0.1)

    async def test_cancel_waits_for_cleanup_and_propagates(self) -> None:
        task = asyncio.create_task(_run_capture([sys.executable, "-c", "import time; time.sleep(30)"], ROOT, os.environ.copy(), 30))
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


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
        with tempfile.TemporaryDirectory() as directory:
            data_home = Path(directory)
            settings_path = data_home / "settings.yaml"
            settings_path.write_text("ui-conversation:\n  busyEnter: steer\n", encoding="utf-8")
            original = settings_path.read_bytes()
            layout = HarnessLayout(ROOT, data_home, ROOT / "node", ROOT / "cli")
            with model_override(layout, "deepseek-v4-pro", "max") as (model, effort, patch_path):
                self.assertEqual(model, "deepseek-v4-pro")
                self.assertEqual(effort, "max")
                patch_data = json.loads(patch_path.read_text(encoding="utf-8"))
                self.assertEqual(patch_data[0]["config"]["model"], "deepseek-v4-pro")
                self.assertEqual(patch_data[0]["config"]["reasoningEffort"], "max")
                self.assertEqual(patch_data[1], {"id": "credentials", "disabled": False})
                self.assertEqual(patch_data[2], {"id": "session-title-llm", "disabled": True})
            self.assertFalse(patch_path.exists())
            self.assertEqual(settings_path.read_bytes(), original)

    def test_current_and_future_model_ids_are_not_blocked(self) -> None:
        self.assertEqual(_normalize_model(""), "deepseek-flash")
        self.assertEqual(_normalize_model("deepseek-future-2027"), "deepseek-future-2027")
        with self.assertRaises(ValueError):
            _normalize_model("--json injected")

    def test_json_events_report_only_final_and_complete_usage(self) -> None:
        events = [
            {"type": "session", "sessionId": "session-test"},
            {"type": "thinking", "text": "private thought"},
            {"type": "status", "phase": "step_end", "usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 5}},
            {"type": "status", "phase": "step_end", "usage": {"inputTokens": 4, "outputTokens": 3}},
            {"type": "status", "phase": "turn_end", "reason": {"kind": "completed"}},
            {"type": "final", "text": "finished"},
        ]
        result = parse_run_events("\n".join(map(json.dumps, events)))
        self.assertEqual(result["assistant_result"], "finished")
        self.assertEqual(result["session_id"], "session-test")
        self.assertEqual(result["usage"], {"inputTokens": 14, "outputTokens": 5})
        self.assertTrue(result["usage_complete"])
        self.assertNotIn("private thought", str(result))
        events.insert(2, {"type": "status", "phase": "step_end"})
        partial = parse_run_events("\n".join(map(json.dumps, events)))
        self.assertFalse(partial["usage_complete"])

    def test_invalid_or_incomplete_stream_is_not_a_success(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "non-JSON"):
            parse_run_events("not a JSON stream")
        result = parse_run_events(json.dumps({"type": "error", "message": "MISSING_CREDENTIAL"}))
        self.assertFalse(result["has_final"])
        self.assertIsNone(result["usage"])
        self.assertEqual(result["errors"], ["MISSING_CREDENTIAL"])


if __name__ == "__main__":
    unittest.main()
