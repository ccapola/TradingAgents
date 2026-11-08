#!/usr/bin/env python3
"""Score logged TradingAgents decisions against actual prices.

Reads portfolio/decisions.log lines:
    YYYY-MM-DD | TICKER | Rating | pending

For decisions at least 5 trading days old, uses yfinance daily closes:
  start = close on the decision date (or the last close on/before it)
  end   = close 5 trading days after the decision date
  move  = (end - start) / start

Verdict rules:
  Buy / Overweight   -> correct if the price rose   (move > 0)
  Sell / Underweight -> correct if the price fell   (move < 0)
  Hold               -> correct if |move| < 1 percent
  anything else      -> left pending, noted as unrecognized

Scored lines are rewritten in place with status "correct"/"incorrect" and a
detail suffix. Decisions younger than 5 trading days stay pending. Prices
come from Yahoo Finance (free); nothing here places or simulates a trade for
real — it only grades past research calls.
"""
import sys
from datetime import date
from pathlib import Path

import yfinance as yf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import DECISIONS_PATH  # noqa: E402

HOLD_BAND_PERCENT = 1.0
MIN_AGE_TRADING_DAYS = 5


def closes_from(ticker: str, start: date):
    hist = yf.Ticker(ticker).history(start=start.isoformat(),
                                     end=(date.today()).isoformat(), auto_adjust=False)
    if hist is None or hist.empty:
        return []
    return [(idx.date(), float(row)) for idx, row in hist["Close"].dropna().items()]


def verdict(rating: str, move_percent: float) -> str:
    r = rating.strip().lower()
    if r in ("buy", "overweight"):
        return "correct" if move_percent > 0 else "incorrect"
    if r in ("sell", "underweight"):
        return "correct" if move_percent < 0 else "incorrect"
    if r == "hold":
        return "correct" if abs(move_percent) < HOLD_BAND_PERCENT else "incorrect"
    return "unrecognized"


def main() -> None:
    if not DECISIONS_PATH.exists():
        raise SystemExit(f"No decision log at {DECISIONS_PATH}")
    lines = DECISIONS_PATH.read_text().splitlines()
    out_lines, scored = [], 0
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4 or parts[3] != "pending":
            out_lines.append(line)
            continue
        d_str, ticker, rating = parts[0], parts[1].upper(), parts[2]
        decision_date = date.fromisoformat(d_str)
        series = closes_from(ticker, decision_date)
        # index of the decision-date close: last close on/before the date
        idx = None
        for i, (d, _) in enumerate(series):
            if d <= decision_date:
                idx = i
        if idx is None or len(series) <= idx + MIN_AGE_TRADING_DAYS:
            out_lines.append(line)  # not yet 5 trading days of data after it
            continue
        start_price = series[idx][1]
        end_date, end_price = series[idx + MIN_AGE_TRADING_DAYS]
        move = (end_price - start_price) / start_price * 100.0
        v = verdict(rating, move)
        if v == "unrecognized":
            out_lines.append(line)
            print(f"{d_str} {ticker} {rating}: unrecognized rating, left pending")
            continue
        detail = f"scored {end_date.isoformat()}: {move:+.2f}% over 5 trading days"
        out_lines.append(f"{d_str} | {ticker} | {rating} | {v} ({detail})")
        scored += 1
        print(f"{d_str} {ticker} {rating}: {v} ({detail})")
    DECISIONS_PATH.write_text("\n".join(out_lines) + "\n")
    print(f"Scored {scored} decision(s); log at {DECISIONS_PATH}")


if __name__ == "__main__":
    main()
