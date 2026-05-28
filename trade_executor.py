"""
Liest decisions/YYYY-MM-DD.json, prüft jede Entscheidung über risk_manager
und platziert die entsprechenden Orders über die Alpaca Paper API.
"""

import os
import json
from datetime import date
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

import risk_manager
import logger

load_dotenv()

API_KEY    = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")


def _get_symbol_type(symbol: str) -> str:
    import config
    if symbol in config.WATCHLIST["crypto"] or "/" in symbol:
        return "crypto"
    if symbol in config.WATCHLIST["etfs"]:
        return "etf"
    return "stock"


def _alpaca_symbol(symbol: str) -> str:
    """Alpaca Crypto: BTC/USD → BTCUSD"""
    return symbol.replace("/", "")


def _place_buy(client: TradingClient, decision: dict, account: dict, dry_run: bool) -> dict:
    symbol     = decision["symbol"]
    sym_type   = _get_symbol_type(symbol)
    price      = float(decision.get("current_price", 0))
    equity     = float(account.get("equity", 1000))

    if price <= 0:
        return {"status": "skipped", "reason": "Kein gültiger Preis"}

    position_usd = risk_manager.calculate_position_size(price, equity)
    qty          = round(position_usd / price, 4)
    if qty <= 0:
        return {"status": "skipped", "reason": "Berechnete Menge = 0"}

    stop_price, limit_price = risk_manager.calculate_bracket_prices(price)

    tif = TimeInForce.GTC if sym_type == "crypto" else TimeInForce.DAY

    if dry_run:
        return {
            "status":      "dry_run",
            "symbol":      symbol,
            "qty":         qty,
            "stop_price":  stop_price,
            "limit_price": limit_price,
        }

    try:
        if sym_type == "crypto":
            # Alpaca doesn't support bracket orders for crypto
            order = client.submit_order(
                MarketOrderRequest(
                    symbol=_alpaca_symbol(symbol),
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=tif,
                )
            )
        else:
            order = client.submit_order(
                MarketOrderRequest(
                    symbol=_alpaca_symbol(symbol),
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=tif,
                    order_class=OrderClass.BRACKET,
                    take_profit=TakeProfitRequest(limit_price=limit_price),
                    stop_loss=StopLossRequest(stop_price=stop_price),
                )
            )
        return {"status": "submitted", "order_id": str(order.id), "qty": qty}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _place_sell(client: TradingClient, symbol: str, dry_run: bool) -> dict:
    if dry_run:
        return {"status": "dry_run", "symbol": symbol, "action": "SELL"}
    try:
        client.close_position(_alpaca_symbol(symbol))
        return {"status": "submitted", "action": "SELL"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def execute(dry_run: bool = False) -> list:
    decisions_path = os.path.join("decisions", f"{date.today()}.json")
    if not os.path.exists(decisions_path):
        print(f"[executor] Keine Entscheidungsdatei: {decisions_path}")
        return []

    with open(decisions_path, encoding="utf-8") as f:
        payload = json.load(f)

    decisions = payload.get("decisions", [])
    if not decisions:
        print("[executor] Keine Entscheidungen in der Datei.")
        return []

    client  = TradingClient(API_KEY, SECRET_KEY, paper=True)
    account_obj = client.get_account()
    positions   = {p.symbol: p for p in client.get_all_positions()}
    account = {
        "equity":         float(account_obj.equity),
        "cash":           float(account_obj.cash),
        "day_pnl":        sum(float(p.unrealized_intraday_pl) for p in positions.values()),
        "open_positions": len(positions),
    }

    results = []
    for dec in decisions:
        action  = dec.get("action", "HOLD").upper()
        symbol  = dec.get("symbol", "")
        sym_type = _get_symbol_type(symbol)
        dec["_type"] = sym_type

        # Aktuellen Preis aus data/ nachladen
        data_path = os.path.join("data", f"{date.today()}.json")
        if os.path.exists(data_path):
            with open(data_path, encoding="utf-8") as df:
                market_data = json.load(df)
            sym_info = market_data.get("symbols", {}).get(symbol, {})
            dec["current_price"] = sym_info.get("current_price", 0)

        # Risikoprüfung
        valid, reason = risk_manager.validate(dec, account, results)
        if not valid:
            result = {"symbol": symbol, "action": action, "status": "blocked", "reason": reason}
            print(f"[executor] BLOCKIERT {symbol}: {reason}")
            logger.log_decision(dec, executed=False, reason=reason)
            results.append({**dec, "_executed": False})
            continue

        if action == "HOLD":
            print(f"[executor] HOLD {symbol} — keine Aktion")
            logger.log_decision(dec, executed=False, reason="HOLD")
            results.append({**dec, "_executed": False})
            continue

        if action == "BUY":
            result = _place_buy(client, dec, account, dry_run)
            print(f"[executor] BUY {symbol}: {result['status']}")

        elif action == "SELL":
            if _alpaca_symbol(symbol) not in positions and symbol not in positions:
                result = {"status": "skipped", "reason": "Keine Position vorhanden"}
                print(f"[executor] SELL {symbol}: übersprungen (keine Position)")
            else:
                result = _place_sell(client, symbol, dry_run)
                print(f"[executor] SELL {symbol}: {result['status']}")
        else:
            result = {"status": "unknown_action"}

        logger.log_decision(dec, executed=(result.get("status") == "submitted"), reason=result.get("reason", ""))
        results.append({**dec, "_executed": result.get("status") == "submitted", "_result": result})

    return results


def close_all(dry_run: bool = False) -> None:
    """Schließt alle Aktien- und ETF-Positionen vor Marktschluss; Krypto bleibt offen."""
    client    = TradingClient(API_KEY, SECRET_KEY, paper=True)
    positions = client.get_all_positions()
    if not positions:
        print("[executor] Keine offenen Positionen zum Schließen.")
        return

    equity_pos = [p for p in positions if str(p.asset_class).lower() != "crypto"]
    crypto_pos = [p for p in positions if str(p.asset_class).lower() == "crypto"]

    print(f"[executor] Positionen gesamt: {len(positions)} "
          f"(Aktien/ETFs: {len(equity_pos)}, Krypto offen: {len(crypto_pos)})")

    if not equity_pos:
        print("[executor] Keine Aktien-/ETF-Positionen zum Schließen.")
        return

    if dry_run:
        for p in equity_pos:
            print(f"  dry_run: würde {p.symbol} schließen "
                  f"(unreal. P&L: ${float(p.unrealized_pl):+.2f})")
        return

    total_pnl = 0.0
    closed    = 0
    print("\n--- Positionen schließen ---")
    for p in equity_pos:
        symbol  = p.symbol
        qty     = float(p.qty)
        avg_in  = float(p.avg_entry_price)
        cur     = float(p.current_price)
        pnl     = float(p.unrealized_pl)
        pnl_pct = float(p.unrealized_plpc) * 100
        try:
            client.close_position(symbol, ClosePositionRequest(percentage="100"))
            print(f"  GESCHLOSSEN {symbol:6s}  Qty: {qty:8.4f}  "
                  f"Avg-In: ${avg_in:9.2f}  Kurs: ${cur:9.2f}  "
                  f"P&L: ${pnl:+8.2f}  ({pnl_pct:+.2f}%)")
            total_pnl += pnl
            closed += 1
        except Exception as exc:
            print(f"  FEHLER    {symbol:6s}: {exc}")

    account = client.get_account()
    equity  = float(account.equity)
    cash    = float(account.cash)

    print(f"\n--- Abschluss-Bericht ---")
    print(f"  Geschlossen:        {closed}/{len(equity_pos)} Positionen")
    print(f"  Krypto offen:       {len(crypto_pos)} Positionen")
    print(f"  Gesamt P&L (heute): ${total_pnl:+.2f}")
    print(f"  Equity (Konto):     ${equity:,.2f}")
    print(f"  Verfügbares Cash:   ${cash:,.2f}")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    execute(dry_run=dry)
