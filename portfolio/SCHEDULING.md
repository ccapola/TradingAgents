# Scheduling Spec — TradingAgents Portfolio Layer

For the parent agent to register as cron jobs. This layer does not create
jobs itself. Both jobs deliver their digest to the TradingAgents side chat:
**chat_id `8d9724ad-f985-4d7f-9067-8fac37eef969`**.

Working directory for both commands:
`~/workspace/trading-agents-portfolio/TradingAgents`
Python: `~/workspace/trading-agents-portfolio/.venv/bin/python`

## Job 1 — Hourly watcher (market hours)

- **Schedule:** Mon–Fri, once per hour at ~35 minutes past the hour,
  10:35 through 16:35 America/New_York (covers the 9:30–16:00 ET session;
  the 16:35 run reads the close).
- **Command:**
  ```text
  ~/workspace/trading-agents-portfolio/.venv/bin/python portfolio/watcher.py
  ```
- **Cost:** none (no LLM calls; Yahoo Finance via yfinance).
- **Deliverable:** the newest `runs/watcher/<date>/<HHMM>.md` digest —
  flags only, or "no flags" — sent to the side chat above. If the digest
  carries a STALE HOLDINGS warning, say so in the delivery, do not hide it.

## Job 2 — Daily debate (after the close)

- **Schedule:** Mon–Fri at ~16:45 America/New_York (after the 16:00 close).
- **Environment:** `SEC_EDGAR_USER_AGENT` must be set in the job environment
  (same value used for the Phase 1 proof run). The Anthropic surrogate is
  fetched in memory by the script itself; no key is stored anywhere.
- **Command:**
  ```text
  ~/workspace/trading-agents-portfolio/.venv/bin/python portfolio/daily_debate.py
  ```
  (Defaults: top 3 holdings by weight + any ticker flagged in the latest
  watcher output, analysis date = most recent trading day.)
- **Deliverable:** for each ticker debated, its final rating and the path to
  its saved report under `~/workspace/trading-agents-portfolio/results/reports/`,
  sent to the side chat above. Also note the new lines appended to
  `portfolio/decisions.log`.

## Job 3 — Weekly scoring (housekeeping)

- **Schedule:** Mondays at ~09:00 America/New_York.
- **Command:**
  ```text
  ~/workspace/trading-agents-portfolio/.venv/bin/python portfolio/score_decisions.py
  ```
- **Deliverable:** the newly scored lines (ticker, rating, verdict, measured
  5-trading-day move) sent to the side chat above. Silent if nothing was
  newly scored.

## Notes

- Holdings snapshot freshness: before the Monday scoring run, refresh
  `portfolio/holdings.json` from the Portfolio Tracker (`getdashboard`,
  combined) via `portfolio/update_holdings.py`. The scripts warn when the
  snapshot is older than 7 days; they never invent holdings.
- All times are America/New_York. On market holidays the watcher will simply
  re-read the prior close; its digest labels the data date, so a holiday run
  is harmless but noisy — the parent may skip US market holidays.
