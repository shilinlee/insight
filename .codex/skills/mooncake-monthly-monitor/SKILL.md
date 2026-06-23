---
name: mooncake-monthly-monitor
description: Generate a monthly Markdown monitoring report for kvcache-ai/Mooncake main-branch changes, especially new features, performance optimizations, usability improvements, and interface/API changes. Use when asked to manually run, automate, or review Mooncake monthly project monitoring.
---

# Mooncake Monthly Monitor

## Workflow

1. Run `scripts/monitor_mooncake.py` from this skill directory, or use it from a repo workflow.
2. Use the default monthly window for scheduled runs: previous month day 25 00:00:00 UTC through current month day 25 23:59:59 UTC.
3. For an ad-hoc run before day 25, use `--end-date <today>` to summarize changes available up to the requested date.
4. The script first pulls the exact one-month commit window from `origin/main`, then asks GPT to analyze commit bodies, touched files, and diff statistics into the report sections below. If `OPENAI_API_KEY` is absent, it falls back to a clearly marked heuristic summary instead of hard-coded content.
5. Review the generated Markdown report and commit it to a feature branch. The GitHub workflow opens a pull request instead of pushing generated reports directly to `main`.
6. If email notification is requested, prefer the host repository workflow secrets documented in the workflow. Do not hard-code credentials.

## Report format

The GPT-generated body should use these sections and prioritize substantive changes over raw commit-title lists or small bugfix noise:

- `重点摘要`
- `新特性`
- `性能优化`
- `易用性/文档`
- `接口/API 优化`
- `后续关注建议`

The wrapper script also adds monitoring metadata, hotspot directories, and an appendix with the raw commits in the selected window.

## Script

`./scripts/monitor_mooncake.py` clones or updates `https://github.com/kvcache-ai/Mooncake`, inspects `origin/main`, collects commits in the selected one-month window, sends commit context to GPT, and writes a Markdown report.

Useful example:

```bash
OPENAI_API_KEY=... python .codex/skills/mooncake-monthly-monitor/scripts/monitor_mooncake.py \
  --end-date 2026-06-23 \
  --output reports/mooncake/mooncake-main-2026-05-25-to-2026-06-23.md
```

Use `--require-openai` in CI if a missing or failing GPT analysis should fail the workflow instead of producing a fallback report.
