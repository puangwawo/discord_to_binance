# Multi-Pair Paper Trading Bot (with HTML Report)

Fitur:
- Paper trading (default) — tidak kirim order real
- Multi-pair: BTCUSDT, XRPUSDT, DOGEUSDT, PEPEUSDT (ubah via `.env`)
- Log trade ke CSV: `./logs/trades.csv`
- Snapshot state ke JSON: `./public/state.json`
- Auto-generate report HTML: `./public/report.html` (self-contained, mudah dibuka)
- Optional: Webhook `/alert` untuk TradingView (`ENABLE_WEBHOOK=true`)

## Jalankan
```bash
pip install -r requirements.txt
cp .env.example .env  # edit bila perlu
python bot.py
```

## Lihat Report
- File: `public/report.html` → bisa dibuka langsung (double click)
- Untuk GitHub Pages, commit file ini dan aktifkan Pages (branch main).

## Kirim Sinyal Manual (opsional)
Uncomment contoh di akhir `bot.py`:
```python
# submit_signal("BTCUSDT","buy",1)
# submit_signal("XRPUSDT","sell",0.7)
```

## Catatan
- Mode paper trading by default (`LIVE_TRADING=false`).
- Kalau mau testnet real order, set `LIVE_TRADING=true` dan isi API key testnet.
