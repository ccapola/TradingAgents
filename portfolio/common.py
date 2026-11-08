"""Shared helpers for the TradingAgents portfolio layer.

Holdings come from portfolio/holdings.json, a snapshot of Cooper's Portfolio
Tracker (see update_holdings.py). Every consumer must surface the snapshot's
as-of date, and must warn loudly — never silently proceed — when the snapshot
is missing or older than its stale_after_days budget.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
WORKSPACE_ROOT = REPO_ROOT.parent
HOLDINGS_PATH = HERE / "holdings.json"
DECISIONS_PATH = HERE / "decisions.log"


def load_holdings():
    """Return (holdings_list, as_of_iso, stale_warning_or_None).

    holdings_list is ranked by portfolio weight, heaviest first.
    Raises SystemExit with a clear message if the snapshot is missing —
    scripts in this layer never invent holdings numbers.
    """
    if not HOLDINGS_PATH.exists():
        raise SystemExit(
            "HOLDINGS DATA MISSING: portfolio/holdings.json does not exist. "
            "Refresh it with update_holdings.py from a Portfolio Tracker "
            "getdashboard dump before running this script."
        )
    snap = json.loads(HOLDINGS_PATH.read_text())
    as_of_raw = snap.get("as_of")
    warning = None
    if not as_of_raw:
        warning = "STALE HOLDINGS WARNING: snapshot has no as-of timestamp."
    else:
        as_of = datetime.fromisoformat(as_of_raw.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - as_of).days
        budget = snap.get("stale_after_days", 7)
        if age_days > budget:
            warning = (f"STALE HOLDINGS WARNING: snapshot as-of {as_of_raw} is "
                       f"{age_days} days old (budget {budget}). Refresh from the "
                       f"Portfolio Tracker before trusting weights.")
    holdings = sorted(snap.get("holdings", []),
                      key=lambda h: h.get("weight_percent", 0), reverse=True)
    return holdings, as_of_raw, warning


def stale_banner(as_of_raw, warning):
    """One-line provenance banner every script prints at the top of its output."""
    base = f"Holdings source: Portfolio Tracker snapshot as-of {as_of_raw}"
    return f"{base}\n{warning}" if warning else base
