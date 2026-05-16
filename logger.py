"""
Speichert alle Handelsentscheidungen und P&L-Daten in logs/YYYY-MM-DD.json.
"""

import json
import os
from datetime import date, datetime


def _log_path() -> str:
    os.makedirs("logs", exist_ok=True)
    return os.path.join("logs", f"{date.today()}.json")


def _load_log() -> list:
    path = _log_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_log(entries: list) -> None:
    with open(_log_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def log_decision(decision: dict, executed: bool, reason: str = "") -> None:
    entries = _load_log()
    entry = {
        "timestamp":  datetime.utcnow().isoformat(),
        "symbol":     decision.get("symbol"),
        "action":     decision.get("action"),
        "confidence": decision.get("confidence"),
        "quantity":   decision.get("quantity"),
        "reasoning":  decision.get("reasoning"),
        "executed":   executed,
        "block_reason": reason if not executed else None,
        "pnl_close":  None,
    }
    entries.append(entry)
    _save_log(entries)


def update_pnl(symbol: str, pnl: float) -> None:
    entries = _load_log()
    for e in reversed(entries):
        if e.get("symbol") == symbol and e.get("action") == "BUY" and e.get("pnl_close") is None:
            e["pnl_close"] = round(pnl, 4)
            break
    _save_log(entries)


def daily_summary() -> dict:
    entries = _load_log()
    executed = [e for e in entries if e.get("executed")]
    closed   = [e for e in executed if e.get("pnl_close") is not None]
    total_pnl = sum(e["pnl_close"] for e in closed)
    wins  = sum(1 for e in closed if e["pnl_close"] > 0)
    losses = sum(1 for e in closed if e["pnl_close"] < 0)
    summary = {
        "date":          str(date.today()),
        "trades_executed": len(executed),
        "trades_closed":   len(closed),
        "total_pnl":       round(total_pnl, 2),
        "wins":            wins,
        "losses":          losses,
        "win_rate":        round(wins / len(closed) * 100, 1) if closed else None,
    }
    print(json.dumps(summary, indent=2))
    return summary
