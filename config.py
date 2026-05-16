WATCHLIST = {
    "stocks": ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN"],
    "etfs":   ["SPY", "QQQ", "ARKK"],
    "crypto": ["BTC/USD", "ETH/USD"],
}

RISK = {
    "max_position_pct": 0.20,       # Max 20% des Kapitals pro Position
    "max_positions": 4,             # Max 4 offene Positionen gleichzeitig
    "stop_loss_pct": 3.0,           # Stop-Loss bei -3%
    "take_profit_pct": 6.0,         # Take-Profit bei +6%
    "max_daily_loss_pct": 5.0,      # Bot stoppt bei -5% Tagesverlust
    "min_confidence": 0.65,         # Claude muss mindestens 65% sicher sein
}

ALPACA = {
    "paper_base_url": "https://paper-api.alpaca.markets",
    "data_base_url":  "https://data.alpaca.markets",
    "news_url":       "https://data.alpaca.markets/v1beta1/news",
}

BARS_LOOKBACK_DAYS = 60   # Tage historische Daten für Indikatoren
