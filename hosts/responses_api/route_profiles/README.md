# Route profiles for `deck_runner.py`

Each file maps a tier (`workhorse`, `frontier`) to `{model, effort, api_base}` and is merged over the runner's defaults with
`--authors` or `--reviewers`. An `api_base` of `cli:claude` or `cli:codex` runs that tier on the user's subscription through the
Claude Code CLI or the Codex CLI (`cli_host.py` for author sessions, `subscription_cli.py` for single-shot reviews); no API key is
read or passed for those routes.

| Profile | Command |
|---|---|
| A. Every stage on Claude Opus 5.5 @ high (Claude subscription) | `deck_runner.py projects/<p> --session S --authors hosts/responses_api/route_profiles/authors_opus.json --reviewers hosts/responses_api/route_profiles/reviewers_opus.json` |
| B. GPT-6 Sol @ high frontier, GPT-6 Luna @ high workhorse, Sol @ high reviewer (ChatGPT subscription) | `deck_runner.py projects/<p> --session S --authors hosts/responses_api/route_profiles/authors_codex.json --reviewers hosts/responses_api/route_profiles/reviewers_codex.json` |

Notes:
- Solution, planner and template stages always use the `frontier` author; the planner's effort is `--planner-effort` (default high).
- Profile A reviews Opus pages with Opus. The runner's default keeps the reviewer in another model family than the author; mixing
  (`--authors authors_opus.json --reviewers reviewers_codex.json`, or the reverse) restores that and still uses subscriptions only.
- `--max-parallel 0` (the default) starts every ready page, and every independent repair within a round, at once.
  Templates and planning finish first; without templates, the chrome anchor still precedes its dependent pages.
  Review-dependent repair rounds remain sequential. A positive `--max-parallel N` explicitly limits concurrency.
  Subscription allowance and provider capacity are shared; starting all jobs does not guarantee unchanged per-call latency.
- `--max-turns` is Claude's own turn limit; for Codex it is a ceiling on tool calls enforced by a watchdog.
