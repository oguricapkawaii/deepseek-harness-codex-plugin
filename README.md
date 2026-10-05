# DeepSeek Harness Codex Plugin (Windows v0.4.0)

A local Codex plugin that connects Codex to an isolated DeepSeek Harness instance:

`requirements -> Harness reads/edits/tests -> Codex reviews the diff -> optional focused repair`

The bundled MCP server exposes `harness_run` for one-shot repository automation plus the existing text-only `deepseek_ask`, `deepseek_code`, `deepseek_review`, and `deepseek_fix` tools. `harness_run` launches the E-drive DeepSeek Harness headless profile in the selected workspace with `workspace-write` sandboxing and telemetry disabled. It uses a separate data home, supports per-task model selection, and never writes the desktop app's session archive.

Available Harness models are `deepseek-v4-flash` (default), `deepseek-v4-pro`, and `deepseek-v4-flash-vision-exp`. Each run also accepts `reasoning_effort`: `off`, `low`, `high`, or `max`; the plugin defaults to `max`. Use `harness_history_list` to find GPT-side sessions and `harness_history_export` to render one as Markdown without opening the desktop app against that data directory.

## Setup on Windows

1. In this directory, run `python scripts/setup.py`.
2. Ensure DeepSeek Harness is installed at `E:\DeepSeekHarness-win32-x64-0.1.1-rc.1` and the isolated GPT data home exists at `E:\DeepSeekHarness-GPT` with `profiles\headless`.
3. The isolated data home's Harness-managed credential store is used by `harness_run`; no key is copied into this plugin. Set `DEEPSEEK_API_KEY` only if you also want the direct text-only tools.
4. Optional settings:
   - `DEEPSEEK_MODEL` defaults to `deepseek-flash`.
   - `DEEPSEEK_BASE_URL` defaults to `https://api.deepseek.com` and must use HTTPS.
   - `DEEPSEEK_TIMEOUT_SECONDS` defaults to `180`.
   - `DEEPSEEK_MAX_TOKENS` defaults to `8192`.
   - `DEEPSEEK_HARNESS_HOME` overrides the read-only Harness installation/runtime directory.
   - `DEEPSEEK_HARNESS_DATA_HOME` overrides the isolated GPT-side settings, profiles, and session directory.
   - `DEEPSEEK_HARNESS_NODE` and `DEEPSEEK_HARNESS_CLI` override the bundled runtime paths.
   - `DEEPSEEK_HARNESS_ALLOWED_ROOTS` is an optional semicolon-separated Windows allowlist for target workspaces.
5. Register or install this folder as a local Codex plugin, then start a new chat so tools and skills reload.

Never put the API key in `.mcp.json`, source code, or a committed `.env` file.

Do not configure the desktop Harness app to use `E:\DeepSeekHarness-GPT` while an MCP task is running. The desktop app should keep using its original installation/data directory.

## Local checks

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src scripts tests
```

The test suite and headless `--help` smoke test do not make a DeepSeek model request, so they spend no model credits and transmit no project data.
