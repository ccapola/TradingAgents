#!/usr/bin/env python3
"""Regenerate portfolio/holdings.json from a Portfolio Tracker dashboard dump.

How to refresh the snapshot:
  1. Call the portfolio-tracker artifact action `getdashboard` (scope
     "combined") and save the returned JSON payload to a file.
  2. Run:  python3 portfolio/update_holdings.py --input <dashboard.json>

The output aggregates positions by ticker across accounts, ranks holdings by
combined portfolio weight, and records the tracker's as-of timestamp loudly.
Nothing in this layer invents holdings numbers: if the tracker is stale,
downstream scripts print a STALE HOLDINGS warning instead.
"""
import argparse
import json
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find_dashboard(obj):
    """Accept either the raw dashboard payload or a wrapper containing it."""
    if isinstance(obj, dict):
        if "holdings" in obj and "asOf" in obj:
            return obj
        for value in obj.values():
            found = find_dashboard(value)
            if found is not None:
                return found
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to a getdashboard JSON dump")
    ap.add_argument("--output", default=str(HERE / "holdings.json"))
    args = ap.parse_args()

    raw = json.load(open(args.input))
    data = find_dashboard(raw)
    if data is None:
        raise SystemExit("No dashboard payload (holdings + asOf) found in input file.")

    by_ticker: "OrderedDict[str, dict]" = OrderedDict()
    for row in data["holdings"]:
        sym = row["symbol"]
        agg = by_ticker.setdefault(sym, {
            "ticker": sym, "shares": 0.0, "market_value": 0.0,
            "cost_basis": 0.0, "weight_percent": 0.0, "accounts": [],
        })
        agg["shares"] += row["shares"]
        agg["market_value"] += row["marketValue"]
        agg["cost_basis"] += row["costBasis"]
        agg["weight_percent"] += row["weight"]
        agg["accounts"].append({
            "account": row["account"], "shares": row["shares"],
            "avg_cost": row["avgCost"], "price_at_snapshot": row["price"],
            "market_value": row["marketValue"], "weight_percent": row["weight"],
            "funding_type": row.get("fundingType"),
        })

    holdings = sorted(by_ticker.values(),
                        key=lambda h: h["weight_percent"], reverse=True)
    for h in holdings:
        h["shares"] = round(h["shares"], 6)
        h["market_value"] = round(h["market_value"], 2)
        h["cost_basis"] = round(h["cost_basis"], 2)
        h["weight_percent"] = round(h["weight_percent"], 2)
        h["avg_cost"] = round(h["cost_basis"] / h["shares"], 4) if h["shares"] else None

    snapshot = {
        "source": "Portfolio Tracker artifact (portfolio-tracker), getdashboard action, scope=combined",
        "as_of": data["asOf"],
        "stale_after_days": 7,
        "totals": data.get("totals", {}),
        "holdings": holdings,
    }
    Path(args.output).write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Wrote {args.output}: {len(holdings)} tickers, as_of {data['asOf']}, "
          f"total value ${snapshot['totals'].get('value')}")


if __name__ == "__main__":
    main()
