#!/usr/bin/env python3
"""Daily debate runner — one TradingAgents run per selected ticker.

Selection: the top N holdings by portfolio weight (default 3) from
portfolio/holdings.json, plus any ticker flagged in the most recent watcher
output (runs/watcher/<date>/<HHMM>.json, newest first).

Each run uses the Phase 1 working config: Anthropic provider, Haiku quick and
deep models, 1 debate round, 1 risk round, analysts market,news, reports saved
under the workspace results/reports/ directory. After each run the ticker's
final rating is appended to portfolio/decisions.log as:
    YYYY-MM-DD | TICKER | Rating | pending
for later scoring by score_decisions.py.

Credential handling: the Anthropic surrogate is fetched in memory via
dynamic_credential_entry("custom.anthropic") and passed ONLY as the child
process's ANTHROPIC_API_KEY environment variable. It is never written to a
file, a log, or git.

Usage:
  python3 portfolio/daily_debate.py                 # top 3 + watcher flags
  python3 portfolio/daily_debate.py --tickers META  # explicit list (smoke test)
  python3 portfolio/daily_debate.py --top 2 --date 2026-11-06
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from common import DECISIONS_PATH, REPO_ROOT, WORKSPACE_ROOT, load_holdings, stale_banner  # noqa: E402

VENV_BIN = WORKSPACE_ROOT / ".venv" / "bin"
MODEL = "claude-haiku-4-5-20251001"


def most_recent_trading_day() -> str:
    """Weekday-only approximation: today if Mon-Fri, else the prior Friday."""
    d = datetime.now(timezone.utc).date()
    while d.weekday() >= 5:  # Saturday/Sunday -> back up to Friday
        d -= timedelta(days=1)
    return d.isoformat()


def latest_watcher_flags():
    runs = sorted((REPO_ROOT / "runs" / "watcher").glob("*/*.json"))
    if not runs:
        return [], None
    newest = runs[-1]
    payload = json.loads(newest.read_text())
    return payload.get("flagged_tickers", []), str(newest)


def extract_rating(ticker: str, trade_date: str) -> str:
    """Pull the final Portfolio Manager rating from the saved report."""
    reports_dir = WORKSPACE_ROOT / "results" / "reports"
    candidates = sorted(reports_dir.glob(f"{ticker}_*"), reverse=True)
    for cand in candidates:
        md = cand / "complete_report.md"
        if md.exists():
            m = re.search(r"\*\*Rating\*\*:\s*([A-Za-z ]+)", md.read_text())
            if m:
                return m.group(1).strip()
    memory_log = WORKSPACE_ROOT / "memory" / "trading_memory.md"
    if memory_log.exists():
        for line in reversed(memory_log.read_text().splitlines()):
            m = re.match(rf"\[{trade_date} \| {ticker} \| ([^|]+) \|", line.strip())
            if m:
                return m.group(1).strip()
    return "UNKNOWN"


def run_one(ticker: str, trade_date: str, surrogate: str) -> str:
    env = dict(os.environ)
    env.update({
        "ANTHROPIC_API_KEY": surrogate,
        "TRADINGAGENTS_LLM_PROVIDER": "anthropic",
        "TRADINGAGENTS_QUICK_THINK_LLM": MODEL,
        "TRADINGAGENTS_DEEP_THINK_LLM": MODEL,
        "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "1",
        "TRADINGAGENTS_MAX_RISK_ROUNDS": "1",
        "TRADINGAGENTS_OUTPUT_LANGUAGE": "English",
        "TRADINGAGENTS_RESULTS_DIR": str(WORKSPACE_ROOT / "results"),
        "TRADINGAGENTS_CACHE_DIR": str(WORKSPACE_ROOT / "cache"),
        "TRADINGAGENTS_MEMORY_LOG_PATH": str(WORKSPACE_ROOT / "memory" / "trading_memory.md"),
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
    })
    if os.environ.get("SEC_EDGAR_USER_AGENT"):
        env["SEC_EDGAR_USER_AGENT"] = os.environ["SEC_EDGAR_USER_AGENT"]
    cmd = [str(VENV_BIN / "tradingagents"), "--ticker", ticker, "--date", trade_date,
           "--analysts", "market,news", "--save", "--no-show"]
    print(f"Running TradingAgents for {ticker} on {trade_date} ...", flush=True)
    proc = subprocess.run(cmd, env=env, cwd=str(WORKSPACE_ROOT),
                          capture_output=True, text=True, timeout=1800)
    log_path = WORKSPACE_ROOT / "results" / f"debate_{ticker}_{trade_date}.log"
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-800:]
        raise SystemExit(f"TradingAgents run for {ticker} failed (exit {proc.returncode}). "
                         f"Log: {log_path}\n{tail}")
    return extract_rating(ticker, trade_date)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=3, help="Top N holdings by weight")
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="Explicit ticker list (overrides top-N + flags)")
    ap.add_argument("--date", default=None,
                    help="Analysis date YYYY-MM-DD (default: most recent trading day)")
    args = ap.parse_args()

    holdings, as_of, warning = load_holdings()
    print(stale_banner(as_of, warning))
    trade_date = args.date or most_recent_trading_day()

    if args.tickers:
        selected = [t.upper() for t in args.tickers]
    else:
        selected = [h["ticker"] for h in holdings[:args.top]]
        flags, watcher_file = latest_watcher_flags()
        for f in flags:
            if f not in selected:
                selected.append(f)
        print(f"Top {args.top} by weight + watcher flags from {watcher_file}: {selected}")

    from dynamic_credentials import dynamic_credential_entry
    surrogate = dynamic_credential_entry("custom.anthropic")["surrogate"]

    for ticker in selected:
        rating = run_one(ticker, trade_date, surrogate)
        with open(DECISIONS_PATH, "a") as fh:
            fh.write(f"{trade_date} | {ticker} | {rating} | pending\n")
        print(f"{ticker}: rating = {rating} (logged to {DECISIONS_PATH})")


if __name__ == "__main__":
    main()
