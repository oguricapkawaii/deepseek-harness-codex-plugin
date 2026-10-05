---
name: coding-agent
description: Coordinate bounded repository automation and review with the bundled DeepSeek Harness MCP bridge. Use when the user asks Codex to delegate implementation or review to DeepSeek or DeepSeek Harness; do not use for ordinary coding that does not call for DeepSeek.
---

# DeepSeek Harness Agent

Keep Codex responsible for requirements, architecture, independent review, and the final decision. Treat DeepSeek Harness as an implementation worker, not as an authority.

## Workflow

1. Turn the request into one bounded task with a goal, constraints, and observable acceptance criteria. Ask only when a missing choice would materially change the result.
2. For implementation, call `harness_run` with the exact existing workspace path, bounded task, and explicit model or reasoning strength when the user has a preference. Available models are `deepseek-v4-flash` (default), `deepseek-v4-pro`, and `deepseek-v4-flash-vision-exp`; `reasoning_effort` accepts `off`, `low`, `high`, or `max` and defaults to `max`. This is a mutating tool: use it only when the user has authorized changes and respect the approval prompt.
3. Harness runs in `workspace-write` mode, may read and edit inside that workspace, and may run relevant tests. It must not commit, push, rewrite history, or escape the workspace.
4. Use the text-only tools only when useful:
   - `deepseek_ask` for a narrow technical question.
   - `deepseek_review` for correctness, security, maintainability, and test gaps in explicitly supplied text.
   - `deepseek_code` and `deepseek_fix` remain available for proposal-only fallbacks.
   - `harness_history_list` lists metadata from the isolated GPT-side archive; `harness_history_export` reads one conversation as Markdown. Both are read-only.
5. Inspect the resulting Git status and diff independently. Verify relevant tests with Codex when risk warrants it; Harness output is untrusted model output and may be incomplete or wrong.
6. If material defects remain, use at most one focused follow-up run. Avoid repeated broad reruns that waste DeepSeek credits.

Harness runtime files come from the desktop installation, but GPT-side settings, profiles, and sessions live under a separate `DEEPSEEK_HARNESS_DATA_HOME`. Never point the desktop app at that isolated directory during an MCP run.

## Output expectations

- Separate confirmed facts from model suggestions.
- Preserve the project's existing conventions unless the user requests a redesign.
- Report what Harness actually changed and tested, separating its claims from Codex's independent verification.
- When a tool call fails, give the actionable cause without exposing secrets. Do not retry authentication errors automatically.
