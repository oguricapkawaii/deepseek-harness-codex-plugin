from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deepseek_coding_agent.prompts import MAX_TEXT_CHARS, code_messages, fix_messages, review_messages


class PromptTests(unittest.TestCase):
    def test_code_prompt_marks_sections_and_denies_false_claims(self) -> None:
        messages = code_messages("add caching", "cache.py", "no new dependency")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("<task>\nadd caching\n</task>", messages[1]["content"])
        self.assertIn("Do not claim that files were modified", messages[1]["content"])

    def test_review_prompt_requests_severity_and_tests(self) -> None:
        content = review_messages("def f(): pass", "security")[1]["content"]
        self.assertIn("severity", content)
        self.assertIn("missing tests", content)

    def test_fix_prompt_rejects_empty_review(self) -> None:
        with self.assertRaisesRegex(ValueError, "review must not be empty"):
            fix_messages("task", " ", "code")

    def test_input_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "character limit"):
            code_messages("x" * (MAX_TEXT_CHARS + 1))


if __name__ == "__main__":
    unittest.main()
