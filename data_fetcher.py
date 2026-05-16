"""
Fetcht Marktdaten von Alpaca und speichert sie als data/YYYY-MM-DD.json.
Claude Code liest diese Datei und schreibt Handelsentscheidungen nach decisions/.
"""

import os
import json
import requests
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

import config

load_dotenv()

API_KEY    = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")


def _calculate_rsi(closes: list, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _calculate_sma(closes: list, period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _volume_ratio(volumes: list, period: int = 20) -> float | None:
    if len(volumes) < period + 1:
        return None
    avg_vol = sum(volumes[-period - 1:-1]) / period
    if avg_vol == 0:
        return None
    return round(volumes[-1] / avg_vol, 2)


def _get_news(symbols: list) -> dict:
    """Holt die letzten 3 News-Headlines pro Symbol von Alpaca."""
    headers = {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": SECRET_KEY,
    }
    news_by_symbol: dict = {s: [] for s in symbols}
    # Crypto-Symbole ohne Slash für die News-API
    clean = [s.replace("/", "") for s in symbols]
    try:
        resp = requests.get(
            config.ALPACA["news_url"],
            headers=headers,
            params={"symbols": ",".join(clean), "limit": 30},
            timeout=10,
        )
        if resp.status_code == 200:
            for article in resp.json().get("news", []):
                for sym in article.get("symbols", []):
                    canonical = sym if "/" not in sym else sym
                    # Mappe BTCUSD → BTC/USD
                    for ws in symbols:
                        if ws.replace("/", "") == sym or ws == sym:
                            if len(news_by_symbol[ws]) < 3:
                                news_by_symbol[ws].append(article.get("headline", ""))
    except Exception as exc:
        print(f"[news] Fehler beim Abrufen: {exc}")
    return news_by_symbol


def fetch_all() -> dict:
    trading  = TradingClient(API_KEY, SECRET_KEY, paper=True)
    stock_dc = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    crypto_dc = CryptoHistoricalDataClient(API_KEY, SECRET_KEY)

    account   = trading.get_account()
    positions = {p.symbol: p for p in trading.get_all_positions()}

    equity    = float(account.equity)
    cash      = float(account.cash)
    day_pnl   = sum(float(p.unrealized_intraday_pl) for p in positions.values())

    all_symbols = (
        config.WATCHLIST["stocks"]
        + config.WATCHLIST["etfs"]
        + config.WATCHLIST["crypto"]
    )
    news = _get_news(all_symbols)

    start = datetime.utcnow() - timedelta(days=config.BARS_LOOKBACK_DAYS)

    symbol_data: dict = {}

    # --- Aktien + ETFs ---
    stock_symbols = config.WATCHLIST["stocks"] + config.WATCHLIST["etfs"]
    if stock_symbols:
        try:
            bars_resp = stock_dc.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=stock_symbols,
                    timeframe=TimeFrame.Day,
                    start=start,
                    feed="iex",
                )
            ).data
        except Exception as exc:
            print(f"[stocks] Fehler beim Abrufen der Bars: {exc}")
            bars_resp = {}

        for sym in stock_symbols:
            bars = bars_resp.get(sym, [])
            if not bars:
                continue
            closes  = [float(b.close)  for b in bars]
            volumes = [float(b.volume) for b in bars]
            pos     = positions.get(sym)
            symbol_data[sym] = {
                "type":           "etf" if sym in config.WATCHLIST["etfs"] else "stock",
                "current_price":  closes[-1],
                "change_pct":     round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else None,
                "rsi_14":         _calculate_rsi(closes),
                "sma_20":         _calculate_sma(closes, 20),
                "sma_50":         _calculate_sma(closes, 50),
                "volume_ratio":   _volume_ratio(volumes),
                "news":           news.get(sym, []),
                "position": {
                    "qty":              float(pos.qty) if pos else 0,
                    "avg_entry_price":  float(pos.avg_entry_price) if pos else None,
                    "unrealized_pnl":   float(pos.unrealized_pl) if pos else None,
                } if pos else None,
            }

    # --- Krypto ---
    for sym in config.WATCHLIST["crypto"]:
        try:
            bars_resp = crypto_dc.get_crypto_bars(
                CryptoBarsRequest(
                    symbol_or_symbols=sym,
                    timeframe=TimeFrame.Day,
                    start=start,
                )
            ).data
            bars = bars_resp.get(sym, [])
        except Exception as exc:
            print(f"[crypto] Fehler für {sym}: {exc}")
            bars = []

        if not bars:
            continue
        closes  = [float(b.close)  for b in bars]
        volumes = [float(b.volume) for b in bars]
        clean_sym = sym.replace("/", "")
        pos = positions.get(clean_sym)
        symbol_data[sym] = {
            "type":           "crypto",
            "current_price":  closes[-1],
            "change_pct":     round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else None,
            "rsi_14":         _calculate_rsi(closes),
            "sma_20":         _calculate_sma(closes, 20),
            "sma_50":         _calculate_sma(closes, 50),
            "volume_ratio":   _volume_ratio(volumes),
            "news":           news.get(sym, []),
            "position": {
                "qty":             float(pos.qty) if pos else 0,
                "avg_entry_price": float(pos.avg_entry_price) if pos else None,
                "unrealized_pnl":  float(pos.unrealized_pl) if pos else None,
            } if pos else None,
        }

    payload = {
        "_instructions": (
            "Analysiere die Marktdaten unten. Für jedes Symbol: bewerte RSI (unter 30 = überverkauft/BUY-Signal, "
            "über 70 = überkauft/SELL-Signal), SMA-Trend (Preis > SMA20 > SMA50 = bullish), Volumen (ratio > 1.5 = starkes Signal), "
            "und News-Sentiment. Berücksichtige offene Positionen. Schreibe Entscheidungen in decisions/<DATUM>.json "
            "im Format _decision_format. Crypto läuft 24/7, Stocks/ETFs nur während Marktzeiten 09:30-16:00 ET."
        ),
        "_decision_format": {
            "decisions": [
                {
                    "symbol": "SYMBOL",
                    "action": "BUY oder SELL oder HOLD",
                    "confidence": 0.0,
                    "quantity": 1,
                    "reasoning": "Kurze Begründung auf Deutsch",
                    "stop_loss_pct": 3.0,
                    "take_profit_pct": 6.0,
                }
            ]
        },
        "_risk_rules": config.RISK,
        "date": str(date.today()),
        "timestamp": datetime.utcnow().isoformat(),
        "account": {
            "equity":       round(equity, 2),
            "cash":         round(cash, 2),
            "day_pnl":      round(day_pnl, 2),
            "open_positions": len(positions),
        },
        "symbols": symbol_data,
    }

    out_path = os.path.join("data", f"{date.today()}.json")
    os.makedirs("data", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"[data_fetcher] Gespeichert: {out_path} ({len(symbol_data)} Symbole)")
    return payload


if __name__ == "__main__":
    fetch_all()
