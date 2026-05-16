"""
Einstiegspunkt für alle Claude Code Routines.

Modi:
  fetch           — Marktdaten holen und data/DATUM.json schreiben
  execute         — decisions/DATUM.json lesen und Orders platzieren
  execute-dry     — wie execute, aber keine echten Orders (Test)
  close           — alle offenen Positionen vor Marktschluss schließen
  report          — Tagesbericht ausgeben
  test-connection — Alpaca-Verbindung und Kontostand prüfen
"""

import argparse
import json
import os
from dotenv import load_dotenv

load_dotenv()


def cmd_fetch():
    import data_fetcher
    data = data_fetcher.fetch_all()
    print(f"Marktdaten für {len(data['symbols'])} Symbole gespeichert.")


def cmd_execute(dry_run: bool = False):
    import trade_executor
    results = trade_executor.execute(dry_run=dry_run)
    executed = sum(1 for r in results if r.get("_executed"))
    print(f"Ausgeführt: {executed}/{len(results)} Entscheidungen.")


def cmd_close():
    import trade_executor
    trade_executor.close_all()


def cmd_report():
    import logger
    logger.daily_summary()


def cmd_test_connection():
    from alpaca.trading.client import TradingClient
    api_key    = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        print("FEHLER: API Keys fehlen. Bitte .env ausfüllen (Vorlage: .env.template)")
        return
    client  = TradingClient(api_key, secret_key, paper=True)
    account = client.get_account()
    print(f"Verbindung OK!")
    print(f"  Kapital (Equity):  ${float(account.equity):,.2f}")
    print(f"  Verfügbares Cash:  ${float(account.cash):,.2f}")
    print(f"  Account-Status:    {account.status}")
    positions = client.get_all_positions()
    print(f"  Offene Positionen: {len(positions)}")


MODES = {
    "fetch":           cmd_fetch,
    "execute":         lambda: cmd_execute(dry_run=False),
    "execute-dry":     lambda: cmd_execute(dry_run=True),
    "close":           cmd_close,
    "report":          cmd_report,
    "test-connection": cmd_test_connection,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trading Bot — Claude Code + Alpaca")
    parser.add_argument("--mode", choices=list(MODES.keys()), required=True,
                        help="Welcher Schritt soll ausgeführt werden?")
    args = parser.parse_args()

    print(f"\n=== Trading Bot | Modus: {args.mode} ===\n")
    MODES[args.mode]()
    print(f"\n=== Fertig ===\n")
