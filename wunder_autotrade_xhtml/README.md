# Wunder Auto Trader — XHTML + Flask backend

This project provides:
- `index.xhtml`: client-side **paper trading** + auto-trade based on the Pine logic:
  - EMA(50/200) trend, engulfing candle, 20SMA volume spike (×1.2)
  - TP/SL configurable (default TP 1%, SL 2%)
  - Optionally sends live TESTNET orders to a backend URL
- `server.py`: Flask backend to place **Binance Testnet** orders and send **Telegram** messages (open/close).

## Quick Start (Backend)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # fill your keys here (DO NOT commit .env)
python server.py
```
The server listens on `http://localhost:8080`. Test:
```bash
curl -X POST http://localhost:8080/api/order -H "Content-Type: application/json"   -d '{"symbol":"BTCUSDT","side":"BUY","quoteOrderQty":10}'
```

## Frontend (XHTML)
Open `index.xhtml` in your browser. Configure:
- Symbols, Interval
- Base USDT, Strength
- TP% and SL%
- (Optional) tick **Live orders** and set Backend URL to your deployed backend `/api/order` endpoint

The frontend will:
- Poll klines (Binance public API), compute Pine-like signals, and **auto trade** in paper mode.
- When *Live orders* is enabled, it will also POST to the backend for real TESTNET orders.

## Security
NEVER put secrets in `index.xhtml` or any public repo. Keep API keys in `.env` on the backend only.

## Telegram
Set `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Backend sends a message on each order.
