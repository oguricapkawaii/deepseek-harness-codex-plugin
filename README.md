# DeepSeek Harness Codex Plugin

An unofficial local Codex plugin that delegates bounded coding tasks to an
isolated [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
runtime, then lets Codex inspect the result and conversation history.

The workflow is:

`requirements -> Harness reads/edits/tests -> Codex reviews -> optional repair`

Version **0.6.0** targets Harness **0.2.1-rc.2**. macOS is integration-tested;
Windows retains its launcher code but has not been regression-tested for this
release. The original Windows-only implementation remains in `v0.4.0-windows`,
and the previous bridge is preserved in `v0.5.0`.

## Features

- Runs Harness inside one explicitly selected workspace with `workspace-write`.
- Keeps GPT/Codex sessions in a data directory separate from the desktop app.
- Reads the installed model catalog with `harness_models`. Defaults to
  `deepseek-flash` (DeepSeek-V4.1-Flash on 0.2.1-rc.2); Pro uses
  `deepseek-v4-pro`. Explicit future/custom ids go to the runtime for validation,
  without a bridge update. Discovery is advisory and does not prove account
  access. Old Flash/vision-exp prompts should use the new catalog's id; the
  bridge never silently substitutes models.
- Selects reasoning effort per task: `off`, `low`, `high`, or `max` (default).
- Lists and exports the isolated Harness history without opening that data
  directory in the desktop app.
- Continues a conversation using its `session_id` and the same workspace.
- Parses public headless `--json` events for completion and root-step token/cache
  counts. Reads the saved request header to verify runtime model selection.
- Includes direct text-only ask, code, review, and fix tools for users who also
  provide `DEEPSEEK_API_KEY`.

MCP tools: `harness_models`, `harness_run`, `harness_history_list`, `harness_history_export`,
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
The bundled `.mcp.json` uses `python3` for macOS. On Windows, change that command
to `python` (the historical Windows tag targets the older Harness). For a user-level Codex
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
copy a key into this repository. Harness 0.2.1 disables stored credentials in
headless by default; this bridge explicitly re-enables the credentials service
in the isolated home. Its stored API key takes precedence over environment
fallbacks. Desktop account OAuth is not enabled by this bridge. The four direct
text tools still require `DEEPSEEK_API_KEY`; their `reasoning_effort` supports
`off / low / high / max`, with max as the thinking-mode default.

Each run writes a private temporary profile patch, then removes it. It no
longer passes a temporary `settings.yaml` path, which does not configure the
new runtime's profile-based settings. Auxiliary model-generated session titles
are disabled to avoid an additional request.

## History and isolation

Keep the desktop Harness app on its normal data directory. Do not point it at
`DEEPSEEK_HARNESS_DATA_HOME` while an MCP task is running; two processes opening
the same session store can interrupt a run or damage transient state.

Use `harness_history_list` to find Codex-side Harness sessions and
`harness_history_export` to export one as Markdown. The history remains available
even when the desktop app uses a different data directory.

The reader recognizes legacy filenames and `session.v4.jsonl[.zstd]`, preferring
the newest generation when migrated backups coexist. Reading does not perform
an on-disk migration; resumption is owned by Harness and may require its
supported history migration. A misspelled id or workspace mismatch fails.

Example prompts (replace the workspace with an existing absolute path):

```text
先调用 harness_models 确认模型，再调用 harness_run。
在 /absolute/project/path 完成……
model 使用 deepseek-flash，reasoning_effort 使用 max。
完成后检查 diff 和测试结果，并报告 session_id 与根 Agent Token 用量。
```

```text
继续上次 Harness 任务，使用返回的 session_id 和原工作区。
保留原模型及 max 强度，修复以下问题……，然后检查测试结果。
```

Token totals are provider-reported root-agent step usage, including retries
when reported. `usage_complete=false` marks missing step samples. They exclude
auxiliary/subagent calls and are **not a full bill**. No currency estimate is
invented. The saved request header confirms the runtime-selected model and
effort, not the provider's physical backend/version.

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

On Windows, use `.venv\Scripts\python.exe` instead. The doctor checks runtime
metadata, help and history, not live credential validity or model connectivity.

An opt-in integration test launches the real installed Harness against a local
fake Messages API. It verifies model/effort dispatch, token accounting, isolated
saved credentials, session continuation, workspace rejection, and history
export without contacting a paid model:

```sh
HARNESS_RUN_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -v
```

The desktop executable remains the runtime carrier. This release uses its
documented headless flags (`--json`, `--session-id`); it does not install a
second SDK runtime. Version/catalog discovery and history reading still depend
on shipped module/layout compatibility. Test after future Harness upgrades.
[Official release notes](https://github.com/deepseek-ai/deepseek-harness/releases)
describe the 0.2.1 credential and model changes.

## License

[MIT](LICENSE). This project is not affiliated with or endorsed by DeepSeek or
OpenAI.
