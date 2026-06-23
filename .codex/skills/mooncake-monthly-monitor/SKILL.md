---
name: mooncake-monthly-monitor
description: Generate a monthly Markdown monitoring report for kvcache-ai/Mooncake main-branch changes, especially new features, performance optimizations, usability improvements, and interface/API changes. Use when asked to manually run, automate, or review Mooncake monthly project monitoring.
---

# Mooncake Monthly Monitor

## Workflow

1. Run `scripts/monitor_mooncake.py` from this skill directory, or use it from a repo workflow.
2. Use the default monthly window for scheduled runs: previous month day 25 00:00:00 UTC through current month day 25 23:59:59 UTC.
3. For an ad-hoc run before day 25, use `--end-date <today>` to summarize changes available up to the current main HEAD.
4. Review the generated Markdown report and commit it to the host repository.
5. If email notification is requested, prefer the host repository workflow secrets documented in the workflow. Do not hard-code credentials.

## Script

`./scripts/monitor_mooncake.py` clones or updates `https://github.com/kvcache-ai/Mooncake`, inspects `origin/main`, classifies commit subjects into monitoring categories, adds diff statistics, and writes a Markdown report.

Useful example:

```bash
python .codex/skills/mooncake-monthly-monitor/scripts/monitor_mooncake.py \
  --end-date 2026-06-23 \
  --output reports/mooncake/mooncake-main-2026-05-25-to-2026-06-23.md
```
