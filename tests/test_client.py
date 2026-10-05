from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepseek_coding_agent.client import DeepSeekClient, Settings


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="proposal"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_is_structured(self) -> None:
        completions = FakeCompletions()
        fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        settings = Settings(api_key="test", model="deepseek-flash", max_tokens=100)
        result = await DeepSeekClient(settings, fake).complete([{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "proposal")
        self.assertEqual(result["usage"]["total_tokens"], 30)
        self.assertEqual(completions.kwargs["extra_body"]["thinking"]["type"], "enabled")

    def test_missing_key_is_actionable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY is not set"):
                Settings.from_env()

    def test_non_https_base_url_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "test", "DEEPSEEK_BASE_URL": "http://example.com"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "must use HTTPS"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
