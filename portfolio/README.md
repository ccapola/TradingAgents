# TradingAgents Portfolio Layer (Phase 2)

Built Nov 7, 2026 on branch `feat/portfolio-layer` (stacked on
`fix/anthropic-x-api-key`, which carries the Anthropic `x-api-key` adapter —
that adapter must stay in the tree for any run to authenticate).

**Cadence (locked by Cooper, Nov 7 2026): tiered.** An hourly cheap watcher
with no AI in it, plus one daily deep debate on the top holdings after the
close. Paid Unusual Whales is scratched — every data source below is free.

## The pieces

### 1. Holdings feed — `holdings.json` + `update_holdings.py` + `common.py`

Holdings come from Cooper's **Portfolio Tracker** (the `portfolio-tracker`
artifact, `getdashboard` action, combined scope). The tracker stores positions
server-side; its dashboard returns ticker, shares, price, market value,
weight, and an as-of timestamp per position.

- `holdings.json` is the snapshot this layer consumes: positions aggregated by
  ticker across the individual and Roth accounts, ranked by combined weight.
  Current snapshot: as-of **2026-11-06T20:39:47Z**, 8 tickers, $28,076.81 total
  — META 53.88%, AMZN 16.56%, MU 9.08%, BE 7.89%, NVDA 7.17%, GOOG 2.96%,
  NFLX 1.92%, MSTX 0.53%.
- Refresh: call `getdashboard` on the tracker, save the JSON, then run
  `python3 portfolio/update_holdings.py --input <dashboard.json>`.
- Guardrail: every script prints the snapshot as-of. If the snapshot is older
  than 7 days, output carries a **STALE HOLDINGS WARNING**; if the file is
  missing, scripts stop with a clear error. This layer never invents holdings
  numbers.

### 2. Hourly watcher — `watcher.py`

No LLM calls, no cost. Data: **Yahoo Finance via yfinance** (free).

For each holding it records the latest price and day change, checks the
nearest options expiry for contracts whose traded volume exceeds their open
interest, and counts headlines published in the last 48 hours. A ticker is
flagged if any rule fires:

- absolute day move ≥ 3%
- any options contract with volume > open interest
- ≥ 3 fresh headlines

Outputs land in `runs/watcher/<YYYY-MM-DD>/<HHMM>.json` (full detail) and
`<HHMM>.md` (digest listing only the flags, or "no flags"). When the market
is closed, prices are the most recent trading day's close and the digest says
so — it never presents a stale close as a live quote. Note the options rule
is sensitive by design: on a liquid Friday chain it fires for most big names,
so treat an options-only flag as "worth a glance," not an alarm.

### 3. Daily debate — `daily_debate.py`

Runs the full TradingAgents pipeline (analysts → bull/bear debate → trader →
risk → portfolio manager) once per selected ticker: the **top 3 holdings by
weight** plus **any ticker flagged by the most recent watcher run**, for the
most recent trading day. Same working config as the verified Phase 1 proof
run: Anthropic, Haiku quick + deep (`claude-haiku-4-5-20251001`), 1 debate
round, 1 risk round, analysts `market,news`, reports saved under the
workspace `results/reports/`.

Each finished run appends one line to `decisions.log`:
`YYYY-MM-DD | TICKER | Rating | pending`.

The Anthropic credential is fetched in memory as a surrogate from the
registered `custom.anthropic` connection and passed only as the child
process's `ANTHROPIC_API_KEY`. It is never written to a file, a log, or git.

### 4. Scorer — `score_decisions.py`

Grades the decision log against actual prices (Yahoo Finance, free). For a
decision at least 5 trading days old: close on the decision date vs the close
5 trading days later.

- Buy / Overweight → correct if price rose
- Sell / Underweight → correct if price fell
- Hold → correct if the move was under 1%

Scored lines are rewritten in place with the verdict and the measured move.
Test result (Nov 7, 2026): the Phase 1 SPY proof call (2026-09-23,
Underweight) scored **correct**, −0.67% over 5 trading days.

### 5. Scheduling — `SCHEDULING.md`

Exact cron specs for the parent agent to register (this layer does not create
jobs itself): watcher hourly on market days, daily debate after the close,
digests delivered to the TradingAgents side chat.

## Hard lines

- **Research only.** This system produces second opinions and a scored track
  record. It is never a trade trigger.
- **No Robinhood connection anywhere.** Nothing here reads or touches a
  brokerage account; holdings come from the Portfolio Tracker snapshot.
- **No code that can place a trade.** There is no order path in this layer at
  all. Any real-world trade remains Cooper's own per-trade decision.
- **Every call is logged and scored.** A debate verdict that is not in
  `decisions.log` does not count.
- **Free data only.** Yahoo Finance prices/options/news and the Portfolio
  Tracker. Paid Unusual Whales is scratched by Cooper's decision.
