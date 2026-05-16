"""
Prüft jede Claude-Entscheidung gegen die definierten Risikoregeln.
trade_executor.py ruft validate() auf, bevor eine Order platziert wird.
"""

from datetime import datetime, timezone
import pytz
import config


ET = pytz.timezone("America/New_York")


def _market_open_et() -> bool:
    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    open_t  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now_et < close_t


def validate(decision: dict, account: dict, existing_decisions: list) -> tuple[bool, str]:
    """
    Gibt (True, "") zurück wenn die Entscheidung zulässig ist.
    Gibt (False, Grund) zurück wenn sie blockiert wird.
    """
    action     = decision.get("action", "HOLD").upper()
    confidence = float(decision.get("confidence", 0))
    symbol     = decision.get("symbol", "")
    sym_type   = decision.get("_type", "stock")  # wird von trade_executor gesetzt

    if action == "HOLD":
        return True, ""

    # Tagesverlust-Limit
    equity  = float(account.get("equity", 1))
    day_pnl = float(account.get("day_pnl", 0))
    if day_pnl < -(equity * config.RISK["max_daily_loss_pct"] / 100):
        return False, f"Tagesverlust-Limit erreicht ({day_pnl:.2f} USD)"

    if action == "BUY":
        # Confidence-Schwelle
        if confidence < config.RISK["min_confidence"]:
            return False, f"Confidence zu niedrig ({confidence:.0%} < {config.RISK['min_confidence']:.0%})"

        # Marktzeiten für Aktien/ETFs
        if sym_type in ("stock", "etf") and not _market_open_et():
            return False, "Markt geschlossen (nur 09:30–16:00 ET)"

        # Max. Anzahl offener Positionen
        open_buys = sum(1 for d in existing_decisions if d.get("action") == "BUY" and d.get("_executed"))
        if account.get("open_positions", 0) + open_buys >= config.RISK["max_positions"]:
            return False, f"Max. {config.RISK['max_positions']} Positionen erreicht"

        # Mindest-Kapital für Position
        cash          = float(account.get("cash", 0))
        min_position  = equity * config.RISK["max_position_pct"] * 0.5
        if cash < min_position:
            return False, f"Nicht genug Cash ({cash:.2f} < {min_position:.2f} USD)"

    if action == "SELL":
        # SELL nur wenn Position vorhanden (wird in trade_executor geprüft)
        pass

    return True, ""


def calculate_position_size(price: float, equity: float) -> float:
    """Gibt den Dollarbetrag zurück, den wir in diese Position investieren."""
    return min(equity * config.RISK["max_position_pct"], float("inf"))


def calculate_bracket_prices(entry_price: float, side: str = "long") -> tuple[float, float]:
    """Berechnet Stop-Loss- und Take-Profit-Preise."""
    sl_pct = config.RISK["stop_loss_pct"] / 100
    tp_pct = config.RISK["take_profit_pct"] / 100
    if side == "long":
        stop_loss   = round(entry_price * (1 - sl_pct), 4)
        take_profit = round(entry_price * (1 + tp_pct), 4)
    else:
        stop_loss   = round(entry_price * (1 + sl_pct), 4)
        take_profit = round(entry_price * (1 - tp_pct), 4)
    return stop_loss, take_profit
