#!/usr/bin/env python3
"""
Multi-Pair Paper Trading Bot — Paper Mode with HTML Report
- Pairs: configurable via .env (default: BTCUSDT,XRPUSDT,DOGEUSDT,PEPEUSDT)
- Paper ledger (positions, realized & unrealized PnL)
- REST polling price updates
- Logs trades to CSV
- Generates self-contained HTML report (./public/report.html) with embedded data
- Optional webhook /alert for TradingView (ENABLE_WEBHOOK=true)
- Testnet endpoints supported, but LIVE_TRADING default=false (paper only)
"""
import os, time, hmac, json, hashlib, threading, signal, csv
from dataclasses import dataclass, field, asdict
from typing import Dict, List
import requests
from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv

# ---------- ENV & CONFIG ----------
load_dotenv()
API_KEY     = os.getenv("BINANCE_API_KEY", "")
API_SECRET  = os.getenv("BINANCE_API_SECRET", "")
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"
LIVE_TRADING= os.getenv("LIVE_TRADING", "false").lower() == "true"  # keep false for paper
ENABLE_WEBHOOK = os.getenv("ENABLE_WEBHOOK", "false").lower() == "true"
WEBHOOK_PORT   = int(os.getenv("WEBHOOK_PORT", "8000"))
BASE_QTY       = float(os.getenv("BASE_QTY", "10"))
POLL_SEC       = float(os.getenv("POLL_SEC", "2"))
SYMBOLS        = os.getenv("SYMBOLS", "BTCUSDT,XRPUSDT,DOGEUSDT,PEPEUSDT").replace(" ", "").split(",")

REST_BASE = "https://testnet.binance.vision" if USE_TESTNET else "https://api.binance.com"

session = requests.Session()
retries = Retry(total=5, backoff_factor=0.3, status_forcelist=[429,500,502,503,504])
session.mount("https://", HTTPAdapter(max_retries=retries))

# paths
PUBLIC_DIR = os.path.abspath("./public")
LOGS_DIR = os.path.abspath("./logs")
os.makedirs(PUBLIC_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
TRADES_CSV = os.path.join(LOGS_DIR, "trades.csv")
STATE_JSON = os.path.join(PUBLIC_DIR, "state.json")  # not required by report.html, but nice to have
REPORT_HTML= os.path.join(PUBLIC_DIR, "report.html")

def ts_ms(): return int(time.time()*1000)

# ---------- PAPER LEDGER ----------
@dataclass
class Position:
    qty: float = 0.0
    avg_entry: float = 0.0

@dataclass
class Ledger:
    realized_pnl: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)

    def ensure(self, sym: str):
        if sym not in self.positions:
            self.positions[sym] = Position()

    def buy(self, sym: str, price: float, usdt_notional: float):
        self.ensure(sym)
        p = self.positions[sym]
        qty = (usdt_notional / price) if price > 0 else 0.0
        new_qty = p.qty + qty
        if new_qty <= 0:
            p.qty, p.avg_entry = 0.0, 0.0
        else:
            p.avg_entry = (p.avg_entry * p.qty + price * qty) / new_qty if p.qty > 0 else price
            p.qty = new_qty
        return qty

    def sell(self, sym: str, price: float, usdt_notional: float):
        self.ensure(sym)
        p = self.positions[sym]
        qty = min(p.qty, usdt_notional / price if price > 0 else 0.0)
        if qty <= 0: return 0.0
        pnl = (price - p.avg_entry) * qty
        self.realized_pnl += pnl
        p.qty -= qty
        if p.qty <= 0:
            p.qty, p.avg_entry = 0.0, 0.0
        return qty

    def unrealized(self, sym: str, price: float) -> float:
        self.ensure(sym)
        p = self.positions[sym]
        return (price - p.avg_entry) * p.qty if p.qty > 0 else 0.0

# ---------- EXCHANGE HELPERS (not used if paper-only) ----------
def _signed(params: Dict[str,str]) -> Dict[str,str]:
    if not API_SECRET: raise RuntimeError("Missing API_SECRET.")
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    params["signature"] = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return params

def get_price(symbol: str) -> float:
    r = session.get(f"{REST_BASE}/api/v3/ticker/price", params={"symbol": symbol})
    r.raise_for_status()
    return float(r.json()["price"])

# ---------- WEBHOOK (optional) ----------
import queue
signal_q: "queue.Queue[dict]" = queue.Queue()

def submit_signal(symbol: str, side: str, strength: float = 1.0):
    signal_q.put({"symbol": symbol.upper(), "side": side.lower(), "strength": float(strength), "t": int(time.time())})

def start_webhook():
    from flask import Flask, request, jsonify
    app = Flask(__name__)
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(ok=True, symbols=SYMBOLS, paper=(not LIVE_TRADING))
    @app.route("/alert", methods=["POST"])
    def alert():
        try:
            data = request.get_json(force=True)
            symbol = str(data.get("symbol","")).upper()
            side   = str(data.get("side","")).lower()
            strength = float(data.get("strength", 1))
            if symbol not in SYMBOLS or side not in ("buy","sell"):
                return jsonify(ok=False, error="invalid symbol/side"), 400
            submit_signal(symbol, side, strength)
            return jsonify(ok=True)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 400
    app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False)

# ---------- LOGGING ----------
def ensure_trades_header():
    if not os.path.exists(TRADES_CSV):
        with open(TRADES_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time","symbol","side","qty","price","notional","realized_pnl_after"])

def log_trade(t, symbol, side, qty, price, notional, realized_after):
    ensure_trades_header()
    with open(TRADES_CSV, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([t, symbol, side, f"{qty:.10f}", f"{price:.8f}", f"{notional:.2f}", f"{realized_after:.2f}"])

def write_state_and_report(prices: Dict[str,float], ledger: Ledger):
    # state JSON
    state = {
        "time": int(time.time()),
        "symbols": SYMBOLS,
        "prices": prices,
        "positions": {s: {"qty": ledger.positions.get(s, Position()).qty,
                          "avg_entry": ledger.positions.get(s, Position()).avg_entry}
                      for s in SYMBOLS},
        "realized_pnl": ledger.realized_pnl,
        "unrealized": {s: ledger.unrealized(s, prices.get(s,0.0)) for s in SYMBOLS},
    }
    with open(STATE_JSON, "w") as f:
        json.dump(state, f, indent=2)

    # self-contained HTML (embed JSON inside)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Paper Trading Report</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#0b0f14;color:#e6edf3;margin:0}}
.container{{max-width:1000px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0 0 12px}}
.grid{{display:grid;grid-template-columns:1fr;gap:12px}}
.card{{background:#111826;border:1px solid #1f2836;border-radius:12px;padding:16px;box-shadow:0 2px 10px rgba(0,0,0,.25)}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #243044;text-align:left;font-size:14px}}
th{{color:#9fb3c8;font-weight:600}}
.badge{{display:inline-block;padding:4px 8px;border-radius:999px;background:#233046;color:#9fb3c8;font-size:12px}}
.footer{{opacity:.6;font-size:12px;margin-top:8px}}
.up{{color:#7ce38b}} .down{{color:#ff8a8a}}
pre{{white-space:pre-wrap;background:#0c131d;border:1px solid #1f2836;padding:12px;border-radius:8px;overflow:auto}}
a{{color:#7db7ff;text-decoration:none}}
</style>
</head>
<body>
<div class="container">
  <h1>📈 Paper Trading Report <span class="badge">paper mode</span></h1>
  <div class="grid">
    <div class="card">
      <div>Updated: <strong><span id="updated"></span></strong></div>
      <div>Total Realized PnL: <strong id="rpnl"></strong></div>
      <div>Equity (R+U): <strong id="equity"></strong></div>
    </div>
    <div class="card">
      <h3>Prices & Positions</h3>
      <table id="pp">
        <thead><tr><th>Symbol</th><th>Price</th><th>Qty</th><th>Avg Entry</th><th>UPnL</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="card">
      <h3>How to Add to GitHub</h3>
      <ol>
        <li>Commit this <code>public/report.html</code> file.</li>
        <li>Aktifkan GitHub Pages (Branch: main, Folder: / (root) atau /docs).</li>
        <li>Buka URL GitHub Pages untuk melihat report (static).</li>
      </ol>
      <div class="footer">Note: file ini self-contained, tidak perlu JSON terpisah.</div>
    </div>
  </div>
</div>
<script>
const DATA = {json.dumps(state)};
function fmt(n, d=2){{return Number(n).toFixed(d)}}
function dollars(n){{return (n>=0?'+':'') + fmt(n,2)}}
const updated = new Date(DATA.time*1000).toLocaleString();
document.getElementById('updated').textContent = updated;
document.getElementById('rpnl').textContent = dollars(DATA.realized_pnl);
const tbody = document.querySelector('#pp tbody');
let equity = DATA.realized_pnl;
for (const s of DATA.symbols) {{
  const px = DATA.prices[s] || 0;
  const pos = DATA.positions[s] || {{qty:0, avg_entry:0}};
  const u = (pos.qty>0)? (px - (pos.avg_entry||0)) * pos.qty : 0;
  equity += u;
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><strong>${{s}}</strong></td>
    <td>${{fmt(px,6)}}</td>
    <td>${{fmt(pos.qty,6)}}</td>
    <td>${{fmt(pos.avg_entry||0,6)}}</td>
    <td class="${{u>=0?'up':'down'}}">${{dollars(u)}}</td>`;
  tbody.appendChild(tr);
}}
document.getElementById('equity').textContent = dollars(equity);
</script>
</body>
</html>
"""
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

# ---------- MAIN LOOP ----------
def run():
    print(f"Starting PAPER bot | USE_TESTNET={USE_TESTNET} LIVE_TRADING={LIVE_TRADING}")
    print(f"Symbols: {SYMBOLS} | Poll: {POLL_SEC}s | Base Notional: {BASE_QTY} USDT")
    if ENABLE_WEBHOOK:
        th = threading.Thread(target=start_webhook, daemon=True); th.start()
        print(f"Webhook listening on :{WEBHOOK_PORT}/alert")

    prices = {s: 0.0 for s in SYMBOLS}
    ledger = Ledger()

    stop = False
    def on_sig(sig, frm):
        nonlocal stop
        stop = True
        print("Stopping...")
    signal.signal(signal.SIGINT, on_sig)

    last_report = 0
    while not stop:
        # 1) update prices
        for s in SYMBOLS:
            try: prices[s] = get_price(s)
            except Exception as e: print(f"[WARN] {s} price: {e}")
        # 2) handle signals (if any)
        while not signal_q.empty():
            sig = signal_q.get_nowait()
            s, side, strength = sig["symbol"], sig["side"], sig["strength"]
            px = prices.get(s, 0.0)
            if px <= 0: print(f"[SKIP] no price for {s}"); continue
            notional = max(5.0, BASE_QTY * max(0.1, min(2.0, strength)))
            if side == "buy":
                qty = ledger.buy(s, px, notional)
                log_trade(int(time.time()), s, "buy", qty, px, notional, ledger.realized_pnl)
                print(f"[BUY ] {s} qty={qty:.6f} @ {px:.6f} notional≈{notional:.2f}")
            elif side == "sell":
                qty = ledger.sell(s, px, notional)
                log_trade(int(time.time()), s, "sell", qty, px, notional, ledger.realized_pnl)
                print(f"[SELL] {s} qty={qty:.6f} @ {px:.6f} notional≈{notional:.2f}")
        # 3) write report every ~5s
        now = time.time()
        if now - last_report > 5:
            write_state_and_report(prices, ledger)
            last_report = now
        # 4) brief line
        upnl_total = sum(ledger.unrealized(s, prices.get(s,0.0)) for s in SYMBOLS)
        print(" | ".join([f"{s}:{prices.get(s,0.0):.6f}" for s in SYMBOLS]) + f" || RPNL {ledger.realized_pnl:.2f} UPNL {upnl_total:.2f}")
        time.sleep(POLL_SEC)

if __name__ == "__main__":
    # contoh sinyal manual saat start (opsional):
    # submit_signal("BTCUSDT","buy",1)
    # submit_signal("XRPUSDT","sell",0.7)
    run()
