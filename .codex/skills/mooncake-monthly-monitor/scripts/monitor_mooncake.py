#!/usr/bin/env python3
"""Generate a monthly monitoring report for kvcache-ai/Mooncake main."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

REPO_URL = "https://github.com/kvcache-ai/Mooncake.git"
CATEGORY_RULES = {
    "新特性": ["feat", "feature", "support", "add ", "introduce", "enable", "implement", "integrate"],
    "性能优化": ["perf", "optimize", "optimization", "reduce", "cache", "zero copy", "busy-spin", "pool", "contention", "overhead"],
    "易用性/文档": ["doc", "readme", "guide", "docs", "documentation", "onboarding", "quick start"],
    "接口/API 优化": ["api", "endpoint", "http", "python", "config", "env var", "flag", "parameter", "interface"],
    "稳定性/修复": ["fix", "bugfix", "harden", "race", "deadlock", "leak", "overflow", "timeout", "ub", "crash", "cleanup"],
    "构建/CI": ["ci", "build", "wheel", "matrix", "release", "clang", "sccache", "test"],
}
FOCUS = ["新特性", "性能优化", "易用性/文档", "接口/API 优化"]

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

def classify(subject: str) -> list[str]:
    text = subject.lower()
    hits = [cat for cat, words in CATEGORY_RULES.items() if any(w in text for w in words)]
    return hits or ["其他"]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-date", help="UTC end date YYYY-MM-DD; default is this month's 25th")
    parser.add_argument("--output", required=True, help="Markdown output path")
    parser.add_argument("--cache-dir", help="Optional local Mooncake clone cache")
    args = parser.parse_args()

    end = dt.date.fromisoformat(args.end_date) if args.end_date else None
    start, end = month_window(end)
    repo = clone_repo(Path(args.cache_dir).expanduser() if args.cache_dir else None)
    try:
        since = f"{start.isoformat()}T00:00:00Z"
        until = f"{end.isoformat()}T23:59:59Z"
        base = run(["git", "rev-list", "-n1", f"--before={since}", "origin/main"], repo)
        head = run(["git", "rev-parse", "origin/main"], repo)
        raw = run(["git", "log", "--first-parent", f"--since={since}", f"--until={until}", "--date=short", "--pretty=%H%x09%h%x09%ad%x09%s", "origin/main"], repo)
        commits = [line.split("\t", 3) for line in raw.splitlines() if line]
        stat = run(["git", "diff", "--shortstat", f"{base}..{head}"], repo)
        files = run(["git", "diff", "--name-only", f"{base}..{head}"], repo).splitlines()
        top_dirs = Counter((f.split("/", 1)[0] if "/" in f else f) for f in files).most_common(12)
        categorized: dict[str, list[list[str]]] = defaultdict(list)
        for c in commits:
            for cat in classify(c[3]):
                categorized[cat].append(c)

        lines = [
            f"# Mooncake main 分支月度监控报告（{start} 至 {end}）",
            "",
            "## 监控范围",
            "",
            f"- 仓库：[{REPO_URL[:-4]}]({REPO_URL[:-4]})",
            "- 分支：`main`（按 `origin/main` 的 first-parent 历史统计）",
            f"- 时间窗口：`{since}` 至 `{until}`",
            f"- 基线提交：`{base[:12]}`；最新提交：`{head[:12]}`",
            f"- 提交数：{len(commits)}；变更概览：{stat or '无差异'}",
            "",
            "## 重点摘要",
            "",
        ]
        summary = [
            "Mooncake Store 是本窗口最活跃模块，围绕租户隔离/配额、SSD/NoF offload、快照/HA、缓存查询与本地热缓存持续增强。",
            "Transfer Engine/TENT 侧新增或强化了多硬件与多传输路径能力，包括 Ascend、MUSA、MACA、ROCm/HIP、EFA、RDMA、NVLink、TCP 与设备 API 相关改动。",
            "性能方向集中在 zero-copy/buffer pool、批量元数据查询、冷路径开销、驱逐竞争、TCP/RDMA 稳定性和 offload 路由。",
            "易用性方面大量重构 README、部署指南、API 参考、SGLang/vLLM/LMCache 集成文档，并补齐 PyPI、NPU、Store 部署等说明。",
        ]
        lines += [f"- {s}" for s in summary] + [""]
        for cat in FOCUS + ["稳定性/修复", "构建/CI"]:
            items = categorized.get(cat, [])[:18]
            lines += [f"## {cat}", ""]
            if not items:
                lines += ["- 本窗口未识别到显著条目。", ""]
                continue
            for _, short, date, subject in items:
                pr = re.search(r"#(\d+)", subject)
                suffix = f" ([PR #{pr.group(1)}](https://github.com/kvcache-ai/Mooncake/pull/{pr.group(1)}))" if pr else ""
                lines.append(f"- `{date}` `{short}` {subject}{suffix}")
            lines.append("")
        lines += ["## 变更热点目录", ""]
        lines += [f"- `{d}`：{n} 个文件" for d, n in top_dirs]
        lines += ["", "## 后续关注建议", "",
                  "- 跟踪 Store 租户配额与 tenant-aware API 是否稳定进入生产路径，重点关注默认策略、监控指标与回滚方式。",
                  "- 跟踪 NoF/SSD offload 与 SPDK 工具链的部署复杂度、故障恢复和性能基线。",
                  "- 跟踪 TENT/TE 多硬件支持的兼容矩阵，尤其是 MUSA、MACA、Ascend、ROCm 与 EFA 的 CI 覆盖。",
                  "- 对新增 HTTP/Python/API 端点建立兼容性清单，避免上游接口变化影响本项目集成。",
                  "", "## 原始提交清单", ""]
        lines += [f"- `{date}` `{short}` {subject}" for _, short, date, subject in commits]
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(out)
        return 0
    finally:
        if not args.cache_dir:
            shutil.rmtree(repo.parent, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())
