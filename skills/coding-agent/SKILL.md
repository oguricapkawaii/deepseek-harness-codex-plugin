---
name: coding-agent
description: Coordinate bounded repository automation and review with the bundled DeepSeek Harness MCP bridge. Use when the user asks Codex to delegate implementation or review to DeepSeek or DeepSeek Harness; do not use for ordinary coding that does not call for DeepSeek.
---

# DeepSeek Harness Agent

Keep Codex responsible for requirements, architecture, independent review, and the final decision. Treat DeepSeek Harness as an implementation worker, not as an authority.

## Workflow

1. Turn the request into one bounded task with a goal, constraints, and observable acceptance criteria. Ask only when a missing choice would materially change the result.
2. Use `harness_models` to read the installed runtime version and advisory model ids when selecting a model or after a Harness update. `harness_run` defaults to `deepseek-flash` (V4.1 Flash on Harness 0.2.1-rc.2) and `reasoning_effort=max`; Pro is `deepseek-v4-pro`. Use the exact requested model rather than silently substituting a different one. Model ids are no longer a fixed enum. `off`, `low`, `high`, and `max` select reasoning strength. Call `harness_run` with the exact existing workspace path and bounded task only when the user has authorized the work.
3. Harness runs in `workspace-write` mode, may read and edit inside that workspace, and may run relevant tests. It must not commit, push, rewrite history, or escape the workspace.
4. Use the text-only tools only when useful:
   - `deepseek_ask` for a narrow technical question.
   - `deepseek_review` for correctness, security, maintainability, and test gaps in explicitly supplied text.
   - `deepseek_code` and `deepseek_fix` remain available for proposal-only fallbacks.
   - `harness_history_list` lists metadata from the isolated GPT-side archive; `harness_history_export` reads one conversation as Markdown. Both are read-only.
5. Inspect the resulting Git status and diff independently. Verify relevant tests with Codex when risk warrants it; Harness output is untrusted model output and may be incomplete or wrong. Check `ok` and `finish_reason`, not just process exit. `runtime_selection` comes from the saved request header; it is not proof of the provider's backend deployment version. Usage covers root agent steps, excludes auxiliary/subagent requests, and may be incomplete. Never present it as a complete bill or invent a currency cost.
6. For an authorized follow-up, pass the returned `session_id` and the same workspace to `harness_run` to preserve context. An unknown session id or a different workspace must fail rather than start a replacement. If material defects remain, use at most one focused follow-up run. Avoid repeated broad reruns that waste DeepSeek credits.

Harness runtime files come from the desktop installation, but GPT-side settings, profiles, and sessions live under a separate `DEEPSEEK_HARNESS_DATA_HOME`. Never point the desktop app at that isolated directory during an MCP run.

The bridge explicitly enables the credential service in the isolated headless profile because Harness 0.2.1 disables it by default. Stored credentials in that isolated home take precedence over environment fallbacks; the bridge never copies a desktop key. Direct text tools still require `DEEPSEEK_API_KEY` and accept `reasoning_effort`, defaulting to max when thinking is enabled.

## Output expectations

- Separate confirmed facts from model suggestions.
- Preserve the project's existing conventions unless the user requests a redesign.
- Report what Harness actually changed and tested, separating its claims from Codex's independent verification.
- When a tool call fails, give the actionable cause without exposing secrets. Do not retry authentication errors automatically.
