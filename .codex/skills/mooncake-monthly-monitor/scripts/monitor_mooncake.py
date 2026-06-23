#!/usr/bin/env python3
"""Generate a monthly monitoring report for kvcache-ai/Mooncake main."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

REPO_URL = "https://github.com/kvcache-ai/Mooncake.git"
REPORT_SECTIONS = ["新特性", "性能优化", "易用性/文档", "接口/API 优化", "后续关注建议"]
SMALL_FIX_RE = re.compile(r"\b(fix|bugfix|typo|cleanup|lint|format|flaky)\b", re.IGNORECASE)


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def month_window(end_date: dt.date | None) -> tuple[dt.date, dt.date]:
    if end_date is None:
        today = dt.datetime.now(dt.timezone.utc).date()
        end_date = dt.date(today.year, today.month, 25)
    month = end_date.month - 1 or 12
    year = end_date.year - (1 if end_date.month == 1 else 0)
    return dt.date(year, month, 25), end_date


def clone_repo(cache_dir: Path | None) -> Path:
    if cache_dir:
        repo = cache_dir
        if (repo / ".git").exists():
            run(["git", "fetch", "--prune", "origin"], repo)
        else:
            repo.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "clone", "--filter=blob:none", REPO_URL, str(repo)])
        return repo
    tmp = Path(tempfile.mkdtemp(prefix="mooncake-monitor-")) / "Mooncake"
    run(["git", "clone", "--filter=blob:none", REPO_URL, str(tmp)])
    return tmp


def rev_before(repo: Path, timestamp: str) -> str:
    return run(["git", "rev-list", "-n1", f"--before={timestamp}", "origin/main"], repo)


def collect_commits(repo: Path, since: str, until: str) -> list[dict[str, str]]:
    raw = run(
        [
            "git",
            "log",
            "--first-parent",
            f"--since={since}",
            f"--until={until}",
            "--date=short",
            "--pretty=%H%x09%h%x09%ad%x09%s",
            "origin/main",
        ],
        repo,
    )
    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        if not line:
            continue
        full, short, date, subject = line.split("\t", 3)
        body = run(["git", "show", "-s", "--format=%b", full], repo)
        stat = run(["git", "show", "--stat", "--oneline", "--format=", full], repo)
        names = run(["git", "show", "--name-only", "--format=", full], repo).splitlines()
        pr = re.search(r"#(\d+)", subject)
        commits.append(
            {
                "hash": full,
                "short": short,
                "date": date,
                "subject": subject,
                "body": body[:2000],
                "stat": stat[:3000],
                "files": "\n".join(names[:80]),
                "pr": pr.group(1) if pr else "",
            }
        )
    return commits


def compact_change_log(commits: list[dict[str, str]], max_chars: int = 45000) -> str:
    chunks: list[str] = []
    for c in commits:
        maybe_small = "yes" if SMALL_FIX_RE.search(c["subject"]) else "no"
        chunks.append(
            textwrap.dedent(
                f"""
                - {c['date']} {c['short']} {c['subject']}
                  PR: {c['pr'] or 'unknown'}; likely_small_fix: {maybe_small}
                  Body:
                {textwrap.indent(c['body'] or '(empty)', '    ')}
                  Files:
                {textwrap.indent(c['files'] or '(none)', '    ')}
                  Stat:
                {textwrap.indent(c['stat'] or '(none)', '    ')}
                """
            ).strip()
        )
        if sum(len(x) for x in chunks) > max_chars:
            chunks.append("\n[truncated: remaining commits omitted from model context]")
            break
    return "\n\n".join(chunks)


def openai_analyze(model: str, prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    payload = {
        "model": model,
        "input": prompt,
        "instructions": "你是资深开源项目技术分析师。只输出中文 Markdown，不要编造提交中不存在的信息。",
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API request failed: {exc.code} {detail}") from exc
    text = data.get("output_text")
    if text:
        return text.strip()
    pieces: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                pieces.append(content.get("text", ""))
    return "\n".join(pieces).strip()


def heuristic_report(commits: list[dict[str, str]]) -> str:
    important = [c for c in commits if not SMALL_FIX_RE.search(c["subject"])]
    buckets = {
        "新特性": ["feat", "support", "add", "introduce", "enable", "integrate"],
        "性能优化": ["perf", "optimize", "reduce", "cache", "zero copy", "pool", "overhead"],
        "易用性/文档": ["doc", "readme", "guide", "quick start", "onboarding"],
        "接口/API 优化": ["api", "endpoint", "http", "python", "config", "env", "flag", "interface"],
    }
    lines = ["## 重点摘要", "", "- 未配置 `OPENAI_API_KEY`，以下为基于提交正文、文件列表和 diffstat 的自动归纳；建议配置 GPT 分析以获得更高质量总结。", ""]
    for title, keys in buckets.items():
        lines += [f"## {title}", ""]
        matched = [c for c in important if any(k in c["subject"].lower() or k in c["files"].lower() for k in keys)][:8]
        if not matched:
            lines += ["- 本窗口未识别到显著条目。", ""]
            continue
        for c in matched:
            pr = f" ([PR #{c['pr']}](https://github.com/kvcache-ai/Mooncake/pull/{c['pr']}))" if c["pr"] else ""
            touched = ", ".join(dict.fromkeys([f.split('/', 1)[0] for f in c["files"].splitlines() if f][:3]))
            lines.append(f"- `{c['date']}` `{c['short']}` {c['subject']}{pr}。主要触达：{touched or '未列出文件'}。")
        lines.append("")
    lines += ["## 后续关注建议", "", "- 对上述功能/API/性能类变更进行集成验证，低优先级小修复可不作为月报重点。", ""]
    return "\n".join(lines)


def build_prompt(start: dt.date, end: dt.date, commits: list[dict[str, str]], stat: str, top_dirs: list[tuple[str, int]]) -> str:
    return f"""
请基于下面 Mooncake main 分支在指定 1 个月时间窗内的提交、提交正文、文件列表和 diffstat，生成月度监控报告正文。

要求：
- 不是罗列 commit 标题，而是总结“改动内容”和对使用/集成/性能的影响。
- 可以忽略琐碎 bugfix、拼写、CI 噪声；但影响稳定性、接口行为、性能或部署的修复要纳入相关章节。
- 按以下 Markdown 章节输出，章节名必须一致：{', '.join(REPORT_SECTIONS)}。
- 每个要点尽量引用关键 PR/短 hash，格式如 `[PR #123](https://github.com/kvcache-ai/Mooncake/pull/123)` 或 ``abc1234``。
- 中文输出，简洁但信息密度高。

窗口：{start} 至 {end}
总体 diffstat：{stat or '无差异'}
热点目录：{top_dirs}

提交上下文：
{compact_change_log(commits)}
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-date", help="UTC end date YYYY-MM-DD; default is this month's 25th")
    parser.add_argument("--output", required=True, help="Markdown output path")
    parser.add_argument("--cache-dir", help="Optional local Mooncake clone cache")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), help="OpenAI model used for analysis")
    parser.add_argument("--require-openai", action="store_true", help="Fail instead of using heuristic fallback when OpenAI is unavailable")
    args = parser.parse_args()

    end_arg = dt.date.fromisoformat(args.end_date) if args.end_date else None
    start, end = month_window(end_arg)
    repo = clone_repo(Path(args.cache_dir).expanduser() if args.cache_dir else None)
    try:
        since = f"{start.isoformat()}T00:00:00Z"
        until = f"{end.isoformat()}T23:59:59Z"
        base = rev_before(repo, since)
        head = rev_before(repo, until)
        commits = collect_commits(repo, since, until)
        stat = run(["git", "diff", "--shortstat", f"{base}..{head}"], repo)
        files = run(["git", "diff", "--name-only", f"{base}..{head}"], repo).splitlines()
        top_dirs = Counter((f.split("/", 1)[0] if "/" in f else f) for f in files).most_common(12)

        prompt = build_prompt(start, end, commits, stat, top_dirs)
        try:
            analysis = openai_analyze(args.model, prompt)
            analysis_note = f"- 分析方式：OpenAI `{args.model}` 基于窗口内提交正文、文件列表与 diffstat 归纳"
        except Exception as exc:
            if args.require_openai:
                raise
            analysis = heuristic_report(commits)
            analysis_note = f"- 分析方式：启发式 fallback（OpenAI 分析不可用：{exc}）"

        lines = [
            f"# Mooncake main 分支月度监控报告（{start} 至 {end}）",
            "",
            "## 监控范围",
            "",
            f"- 仓库：[{REPO_URL[:-4]}]({REPO_URL[:-4]})",
            "- 分支：`main`（按 `origin/main` 的 first-parent 历史统计）",
            f"- 时间窗口：`{since}` 至 `{until}`",
            f"- 基线提交：`{base[:12]}`；窗口内最新提交：`{head[:12]}`",
            f"- 提交数：{len(commits)}；变更概览：{stat or '无差异'}",
            analysis_note,
            "",
            analysis,
            "",
            "## 变更热点目录",
            "",
        ]
        lines += [f"- `{d}`：{n} 个文件" for d, n in top_dirs] or ["- 无文件变更。"]
        lines += ["", "## 附录：窗口内提交清单", ""]
        for c in commits:
            pr = f" ([PR #{c['pr']}](https://github.com/kvcache-ai/Mooncake/pull/{c['pr']}))" if c["pr"] else ""
            lines.append(f"- `{c['date']}` `{c['short']}` {c['subject']}{pr}")
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(out)
        return 0
    finally:
        if not args.cache_dir:
            shutil.rmtree(repo.parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
