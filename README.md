# DeepSeek Harness Codex Plugin

An unofficial local Codex plugin that delegates bounded coding tasks to an
isolated [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
runtime, then lets Codex inspect the result and conversation history.

The workflow is:

`requirements -> Harness reads/edits/tests -> Codex reviews -> optional repair`

The current `main` branch supports macOS and Windows. The original Windows-only
implementation is preserved in the `v0.4.0-windows` tag.

## Features

- Runs Harness inside one explicitly selected workspace with `workspace-write`.
- Keeps GPT/Codex sessions in a data directory separate from the desktop app.
- Selects a model per task: `deepseek-v4-flash`, `deepseek-v4-pro`, or
  `deepseek-v4-flash-vision-exp`.
- Selects reasoning effort per task: `off`, `low`, `high`, or `max` (default).
- Lists and exports the isolated Harness history without opening that data
  directory in the desktop app.
- Includes direct text-only ask, code, review, and fix tools for users who also
  provide `DEEPSEEK_API_KEY`.

MCP tools: `harness_run`, `harness_history_list`, `harness_history_export`,
`deepseek_ask`, `deepseek_code`, `deepseek_review`, and `deepseek_fix`.

## Requirements

- Python 3.10 or newer.
- A local DeepSeek Harness installation.
- A dedicated Harness data directory with an authenticated `headless` profile.

Defaults:

| Platform | Harness application | Isolated GPT/Codex data |
| --- | --- | --- |
| macOS | `/Applications/DeepSeek Harness.app` | `~/Documents/DeepSeekHarness-GPT` |
| Windows | `E:\DeepSeekHarness-win32-x64-0.1.1-rc.1` | `E:\DeepSeekHarness-GPT` |

Any default can be overridden with the environment variables described below.

## Install

Clone the repository, enter it, and create the plugin-local virtual environment:

```sh
python3 scripts/setup.py
```

On Windows, `python scripts/setup.py` is usually the equivalent command.

Register the folder as a local Codex plugin, or add the MCP server manually.
The bundled `.mcp.json` uses `python3` for macOS. On Windows, use the
`v0.4.0-windows` tag or change that command to `python`. For a user-level Codex
MCP entry, copy `codex-mcp.toml.example`, replace every `<PLUGIN_ROOT>` with this
repository's absolute path, and use the platform-appropriate virtual-environment
Python path.

Start a new Codex chat after changing plugin or MCP configuration so the tools
and skill reload.

Example request:

> Use DeepSeek Harness with deepseek-v4-pro and max reasoning in
> /absolute/project/path to implement the task, then review its changes.

## Configuration

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_HARNESS_HOME` | Harness application/install directory |
| `DEEPSEEK_HARNESS_DATA_HOME` | Dedicated GPT/Codex settings, profiles, and sessions |
| `DEEPSEEK_HARNESS_NODE` | Override the bundled Node executable |
| `DEEPSEEK_HARNESS_CLI` | Override the Harness CLI entry point |
| `DEEPSEEK_HARNESS_ALLOWED_ROOTS` | Optional target-workspace allowlist (`:` on macOS, `;` on Windows) |
| `DEEPSEEK_API_KEY` | Optional; only needed by the four direct text tools |
| `DEEPSEEK_BASE_URL` | Direct text API base URL; HTTPS required |
| `DEEPSEEK_MODEL` | Default model for direct text tools |
| `DEEPSEEK_TIMEOUT_SECONDS` | Direct text API timeout |
| `DEEPSEEK_MAX_TOKENS` | Direct text API output-token limit |

The Harness automation tools use Harness's own credential store. They do not
copy a key into this repository.

## History and isolation

Keep the desktop Harness app on its normal data directory. Do not point it at
`DEEPSEEK_HARNESS_DATA_HOME` while an MCP task is running; two processes opening
the same session store can interrupt a run or damage transient state.

Use `harness_history_list` to find Codex-side Harness sessions and
`harness_history_export` to export one as Markdown. The history remains available
even when the desktop app uses a different data directory.

## Safety

The bridge refuses to use a filesystem/drive root, the user home directory, the
Harness installation, the isolated data directory, or the plugin itself as a
task workspace. Its task prompt also forbids commits, pushes, history rewrites,
broad deletion, and credential access.

Never commit an API key, `.env`, Harness credential store, session directory, or
the isolated data directory. Review the selected workspace and the generated
diff before accepting model changes.

## Checks

```sh
.venv/bin/python scripts/doctor.py
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `.venv\Scripts\python.exe` instead. The doctor and unit tests do
not call a model. macOS support, the seven-tool MCP handshake, history export,
and one `deepseek-v4-flash`/`max` connectivity request were verified on the
original development machine. Windows v0.5.0 compatibility is retained in code
but has not been re-tested on that machine.

## License

[MIT](LICENSE). This project is not affiliated with or endorsed by DeepSeek or
OpenAI.
