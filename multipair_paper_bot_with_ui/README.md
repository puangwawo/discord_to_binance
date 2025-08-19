# Multi-Pair Paper Trading Bot — with Live HTML UI

Fitur:
- Paper trading (default): tidak kirim order real
- Multi-pair: BTCUSDT, XRPUSDT, DOGEUSDT, PEPEUSDT
- HTML Dashboard (Flask): http://localhost:8000/
  - Lihat harga, posisi, PnL, Equity
  - Tombol BUY/SELL per simbol + slider strength
  - Pause/Resume polling
- Logs: `./logs/trades.csv`
- State: `./public/state.json` (untuk debug)
- Static report alternatif: `public/report.html` opsional

## Jalankan
```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
# buka http://localhost:8000/
```

## TradingView (opsional)
Kirim alert HTTP POST ke `http://<ip>:8000/alert` dengan body JSON: `{"symbol":"BTCUSDT","side":"buy","strength":1}`
