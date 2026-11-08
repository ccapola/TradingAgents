#!/usr/bin/env python3
"""Hourly watcher — cheap, deterministic, NO LLM calls, costs nothing.

Data source: Yahoo Finance via yfinance (free). Runs over every holding in
portfolio/holdings.json (Portfolio Tracker snapshot).

Flag rules (deterministic, a ticker is flagged if ANY rule fires):
  1. Day move: absolute day change >= 3 percent (last close vs prior close).
  2. Options: on the nearest listed expiry, any contract whose traded volume
     exceeds its open interest (volume > open interest, volume >= 1).
  3. News: 3 or more fresh headlines (published within the last 48 hours).

Outputs:
  runs/watcher/<YYYY-MM-DD>/<HHMM>.json  — full per-ticker detail
  runs/watcher/<YYYY-MM-DD>/<HHMM>.md    — short digest listing ONLY the flags
                                           (or "no flags")

Honesty rules: every output carries the holdings snapshot as-of and a data
note. When the market is closed (weekend/holiday), yfinance returns the most
recent trading day's close; the digest labels that date instead of pretending
the data is live. If holdings are stale or missing, that is printed, never
papered over.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import REPO_ROOT, load_holdings, stale_banner  # noqa: E402

DAY_MOVE_THRESHOLD = 3.0       # percent
NEWS_FRESH_HOURS = 48
NEWS_FLAG_COUNT = 3
MAX_FLAGGED_CONTRACTS_LISTED = 10


def last_two_closes(ticker_obj):
    hist = ticker_obj.history(period="7d", auto_adjust=False)
    if hist is None or len(hist) < 2:
        return None, None, None
    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return None, None, None
    last_date = closes.index[-1].date().isoformat()
    last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
    return last, (last - prev) / prev * 100.0, last_date


def flagged_options(ticker_obj):
    """Contracts on the nearest expiry whose volume exceeds open interest."""
    flagged = []
    try:
        expiries = ticker_obj.options
        if not expiries:
            return flagged, None
        expiry = expiries[0]
        chain = ticker_obj.option_chain(expiry)
        for kind, df in (("call", chain.calls), ("put", chain.puts)):
            for _, row in df.iterrows():
                vol, oi = row.get("volume"), row.get("openInterest")
                if vol is not None and oi is not None and vol == vol and oi == oi:
                    if vol >= 1 and vol > oi:
                        flagged.append({
                            "type": kind, "contract": row.get("contractSymbol"),
                            "strike": float(row.get("strike", 0)) or None,
                            "volume": int(vol), "open_interest": int(oi),
                            "expiry": expiry,
                        })
        return flagged, expiry
    except Exception as exc:  # options data is best-effort; record, don't crash
        return flagged, f"options check failed: {exc}"


def fresh_news_count(ticker_obj, now):
    count = 0
    try:
        for item in ticker_obj.news or []:
            published = None
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, dict) and content.get("pubDate"):
                published = datetime.fromisoformat(
                    content["pubDate"].replace("Z", "+00:00"))
            elif isinstance(item, dict) and item.get("providerPublishTime"):
                published = datetime.fromtimestamp(
                    item["providerPublishTime"], tz=timezone.utc)
            if published and now - published <= timedelta(hours=NEWS_FRESH_HOURS):
                count += 1
    except Exception:
        pass
    return count


def main() -> None:
    holdings, as_of, warning = load_holdings()
    now = datetime.now(timezone.utc)
    tickers = [h["ticker"] for h in holdings]

    results = []
    data_dates = set()
    for sym in tickers:
        t = yf.Ticker(sym)
        price, day_change, data_date = last_two_closes(t)
        if data_date:
            data_dates.add(data_date)
        opt_flagged, opt_note = flagged_options(t)
        news_count = fresh_news_count(t, now)

        reasons = []
        if day_change is not None and abs(day_change) >= DAY_MOVE_THRESHOLD:
            reasons.append(f"day move {day_change:+.2f}%")
        if opt_flagged:
            reasons.append(f"{len(opt_flagged)} options contract(s) with volume > open interest")
        if news_count >= NEWS_FLAG_COUNT:
            reasons.append(f"{news_count} fresh headlines in {NEWS_FRESH_HOURS}h")

        results.append({
            "ticker": sym,
            "weight_percent": next(h["weight_percent"] for h in holdings
                                   if h["ticker"] == sym),
            "price": price, "day_change_percent": day_change,
            "data_date": data_date,
            "options_flagged_contracts": opt_flagged[:MAX_FLAGGED_CONTRACTS_LISTED],
            "options_flagged_count": len(opt_flagged),
            "options_note": opt_note if isinstance(opt_note, str) and "failed" in str(opt_note) else None,
            "options_expiry_checked": opt_note if not (isinstance(opt_note, str) and "failed" in str(opt_note)) else None,
            "fresh_news_count": news_count,
            "flagged": bool(reasons), "flag_reasons": reasons,
        })

    flagged = [r for r in results if r["flagged"]]
    market_note = (
        f"Price data is as of the most recent trading day close "
        f"({', '.join(sorted(data_dates)) if data_dates else 'unknown'}). "
        f"If the market is closed, this is the last close, not a live quote."
    )

    out_dir = REPO_ROOT / "runs" / "watcher" / now.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%H%M")
    payload = {
        "run_at_utc": now.isoformat(), "holdings_as_of": as_of,
        "holdings_warning": warning, "market_note": market_note,
        "flag_rules": {
            "day_move_percent": DAY_MOVE_THRESHOLD,
            "options": "nearest-expiry contract volume > open interest",
            "news": f">= {NEWS_FLAG_COUNT} headlines in {NEWS_FRESH_HOURS}h",
        },
        "tickers": results,
        "flagged_tickers": [r["ticker"] for r in flagged],
    }
    (out_dir / f"{stamp}.json").write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        f"# Watcher digest — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        stale_banner(as_of, warning),
        market_note,
        "",
    ]
    if flagged:
        lines.append(f"## Flags ({len(flagged)})")
        for r in flagged:
            price = f"${r['price']:.2f}" if r["price"] else "n/a"
            move = f"{r['day_change_percent']:+.2f}%" if r["day_change_percent"] is not None else "n/a"
            lines.append(f"- **{r['ticker']}** ({price}, {move} on {r['data_date']}): "
                         + "; ".join(r["flag_reasons"]))
    else:
        lines.append("## no flags")
    lines.append("")
    lines.append(f"Checked {len(results)} holdings. Research only — not a trade signal.")
    (out_dir / f"{stamp}.md").write_text("\n".join(lines) + "\n")

    print(f"Watcher done: {len(results)} tickers, flags: "
          f"{[r['ticker'] for r in flagged] or 'none'}")
    print(f"Wrote {out_dir / (stamp + '.json')} and {out_dir / (stamp + '.md')}")


if __name__ == "__main__":
    main()
