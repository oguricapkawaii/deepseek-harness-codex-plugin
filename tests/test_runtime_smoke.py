"""Opt-in integration: real Harness, local fake Messages server, no paid API calls.

HARNESS_RUN_INTEGRATION=1 python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deepseek_coding_agent.harness import HarnessLayout, list_models, run_harness
from deepseek_coding_agent.history import export_history


@unittest.skipUnless(os.environ.get("HARNESS_RUN_INTEGRATION") == "1", "opt-in real-runtime test")
class RuntimeSmoke(unittest.TestCase):
    def test_model_max_usage_saved_credentials_and_resume(self) -> None:
        requests = []
        auth_headers = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(body)
                auth_headers.append(self.headers.get("x-api-key"))
                number = len(requests)
                events = [
                    ("message_start", {"type": "message_start", "message": {
                        "id": f"msg_{number}", "type": "message", "role": "assistant",
                        "model": body["model"], "content": [], "stop_reason": None,
                        "usage": {"input_tokens": 10, "output_tokens": 0, "cache_read_input_tokens": 4},
                    }}),
                    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": f"MOCK_OK_{number}"}}),
                    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}}),
                    ("message_stop", {"type": "message_stop"}),
                ]
                payload = "".join(f"event: {kind}\ndata: {json.dumps(data)}\n\n" for kind, data in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        layout = HarnessLayout.from_env()
        with tempfile.TemporaryDirectory(prefix="harness-bridge-test-") as temporary:
            parent = Path(temporary)
            data = parent / "home"
            profile = data / "profiles" / "headless"
            profile.mkdir(parents=True)
            (profile / "package.json").write_text(json.dumps({
                "name": "dsh-profile-headless", "private": True, "dependencies": {},
                "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]}},
            }))
            (profile / "cordis.patch.yml").write_text("[]")
            workspace = parent / "workspace"
            workspace.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = {
                "DEEPSEEK_HARNESS_HOME": str(layout.install_home),
                "DEEPSEEK_HARNESS_DATA_HOME": str(data),
                "DEEPSEEK_API_KEY": "bridge-local-test-key",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "DEEPSEEK_HARNESS_ALLOWED_ROOTS": str(workspace),
            }
            try:
                with patch.dict(os.environ, env):
                    catalog = asyncio.run(list_models())
                    self.assertIn("deepseek-flash", [entry["id"] for entry in catalog["models"]])
                    first = asyncio.run(run_harness(str(workspace), "Reply with a short confirmation. Do not use tools.", 90))
                    self.assertNotIn("history_error", first, {"result": first, "files": [str(p.relative_to(data)) for p in data.rglob("*") if p.is_file()]})
                    self.assertTrue(first["ok"], first)
                    self.assertEqual(first["assistant_result"], "MOCK_OK_1")
                    self.assertEqual(first["runtime_selection"]["model"], "deepseek-flash")
                    self.assertEqual(first["runtime_selection"]["reasoning_effort"], "max")
                    self.assertTrue(first["usage_complete"])
                    self.assertEqual(first["usage"]["outputTokens"], 2)
                    credential_path = data / ".credentials.yaml"
                    credential_path.write_text("version: 1\nrefs:\n  DEEPSEEK_API_KEY: bridge-saved-test-key\n")
                    credential_path.chmod(0o600)
                    credential_bytes = credential_path.read_bytes()
                    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                        second = asyncio.run(run_harness(str(workspace), "Continue with another short confirmation. Do not use tools.", 90, session_id=first["session_id"]))
                    self.assertEqual(credential_path.read_bytes(), credential_bytes)
                    self.assertTrue(second["ok"], second)
                    self.assertEqual(second["session_id"], first["session_id"])
                    self.assertEqual(second["assistant_result"], "MOCK_OK_2")
                    exported = asyncio.run(export_history(first["session_id"]))
                    self.assertIn("MOCK_OK_1", exported["markdown"])
                    self.assertIn("MOCK_OK_2", exported["markdown"])
                    other = parent / "other"
                    other.mkdir()
                    with patch.dict(os.environ, {"DEEPSEEK_HARNESS_ALLOWED_ROOTS": str(parent)}):
                        with self.assertRaisesRegex(ValueError, "different workspace"):
                            asyncio.run(run_harness(str(other), "Do not run", 90, session_id=first["session_id"]))
                self.assertEqual(len(requests), 2, "No auxiliary title requests should run")
                self.assertEqual(requests[0]["model"], "deepseek-flash")
                self.assertEqual(requests[0]["output_config"]["effort"], "max")
                self.assertEqual(auth_headers, ["bridge-local-test-key", "bridge-saved-test-key"])
                self.assertIn("MOCK_OK_1", json.dumps(requests[1]["messages"]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
