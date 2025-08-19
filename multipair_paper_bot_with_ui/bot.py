#!/usr/bin/env python3
"""
Multi-Pair Paper Trading Bot — with Live HTML UI (Flask)
- Paper trading default (LIVE_TRADING=false)
- Multi-pair via .env: BTCUSDT,XRPUSDT,DOGEUSDT,PEPEUSDT
- Logs trades to CSV, writes state.json, and serves a live dashboard at http://localhost:<WEBHOOK_PORT>/
- Endpoints:
    GET  /            -> dashboard UI
    GET  /api/state   -> current state (prices, positions, PnL)
    POST /alert       -> accept TradingView alerts ({symbol, side, strength})
    POST /api/signal  -> manual signal from UI ({symbol, side, strength})
    POST /api/pause   -> toggle pause ({paused: true/false})
"""
import os, time, hmac, json, hashlib, threading, signal, csv
from dataclasses import dataclass, field
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
ENABLE_WEBHOOK = os.getenv("ENABLE_WEBHOOK", "true").lower() == "true"  # enable so UI lives
WEBHOOK_PORT   = int(os.getenv("WEBHOOK_PORT", "8000"))
BASE_QTY       = float(os.getenv("BASE_QTY", "10"))
POLL_SEC       = float(os.getenv("POLL_SEC", "2"))
SYMBOLS        = os.getenv("SYMBOLS", "BTCUSDT,XRPUSDT,DOGEUSDT,PEPEUSDT").replace(" ", "").split(",")

REST_BASE = "https://testnet.binance.vision" if USE_TESTNET else "https://api.binance.com"

session = requests.Session()
retries = Retry(total=5, backoff_factor=0.3, status_forcelist=[429,500,502,503,504])
session.mount("https://", HTTPAdapter(max_retries=retries))

# paths
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "public"))
LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "logs"))
os.makedirs(PUBLIC_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
TRADES_CSV = os.path.join(LOGS_DIR, "trades.csv")
STATE_JSON = os.path.join(PUBLIC_DIR, "state.json")

# runtime flags
paused = False

def ts_ms(): return int(time.time()*1000)

# ---------- PAPER LEDGER ----------
from dataclasses import dataclass, field
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

# ---------- EXCHANGE HELPERS (price polling) ----------
def get_price(symbol: str) -> float:
    r = session.get(f"{REST_BASE}/api/v3/ticker/price", params={"symbol": symbol})
    r.raise_for_status()
    return float(r.json()["price"])

# ---------- WEBHOOK / UI SERVER ----------
import queue
signal_q: "queue.Queue[dict]" = queue.Queue()

def submit_signal(symbol: str, side: str, strength: float = 1.0):
    signal_q.put({"symbol": symbol.upper(), "side": side.lower(), "strength": float(strength), "t": int(time.time())})

def start_server(state_ref):
    from flask import Flask, request, jsonify, send_from_directory
    app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")

    @app.get("/")
    def index():
        return send_from_directory(PUBLIC_DIR, "index.html")

    @app.get("/api/state")
    def api_state():
        # read current state directly from state_ref
        return jsonify(state_ref())

    @app.post("/api/signal")
    def api_signal():
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

    @app.post("/api/pause")
    def api_pause():
        nonlocal paused
        try:
            data = request.get_json(force=True)
            new_state = bool(data.get("paused", False))
            paused = new_state
            return jsonify(ok=True, paused=paused)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 400

    @app.post("/alert")
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

    print(f"Dashboard ready at http://localhost:{WEBHOOK_PORT}")
    app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False, use_reloader=False)

# ---------- LOGGING ----------
def ensure_trades_header(path):
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["time","symbol","side","qty","price","notional","realized_pnl_after"])

def log_trade(path, t, symbol, side, qty, price, notional, realized_after):
    ensure_trades_header(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([t, symbol, side, f"{qty:.10f}", f"{price:.8f}", f"{notional:.2f}", f"{realized_after:.2f}"])

# ---------- STATE SNAPSHOT ----------
def build_state(prices, ledger):
    return {
        "time": int(time.time()),
        "symbols": SYMBOLS,
        "prices": prices,
        "positions": {s: {"qty": ledger.positions.get(s, Position()).qty,
                          "avg_entry": ledger.positions.get(s, Position()).avg_entry}
                      for s in SYMBOLS},
        "realized_pnl": ledger.realized_pnl,
        "unrealized": {s: ledger.unrealized(s, prices.get(s,0.0)) for s in SYMBOLS},
        "paused": paused
    }

def write_state_file(prices, ledger):
    state = build_state(prices, ledger)
    with open(STATE_JSON, "w") as f:
        json.dump(state, f, indent=2)
    return state

# ---------- MAIN LOOP ----------
def run():
    global paused
    print(f"Starting PAPER bot | USE_TESTNET={USE_TESTNET} LIVE_TRADING={LIVE_TRADING}")
    print(f"Symbols: {SYMBOLS} | Poll: {POLL_SEC}s | Base Notional: {BASE_QTY} USDT")

    prices = {s: 0.0 for s in SYMBOLS}
    ledger = Ledger()
    last_state = {}

    # spawn server
    def state_ref():
        return last_state or build_state(prices, ledger)

    if ENABLE_WEBHOOK:
        th = threading.Thread(target=start_server, args=(state_ref,), daemon=True)
        th.start()

    stop = False
    def on_sig(sig, frm):
        nonlocal stop
        stop = True
        print("Stopping...")
    signal.signal(signal.SIGINT, on_sig)

    last_write = 0
    while not stop:
        # 1) update prices
        if not paused:
            for s in SYMBOLS:
                try: prices[s] = get_price(s)
                except Exception as e: print(f"[WARN] {s} price: {e}")
        # 2) handle queued signals
        while not signal_q.empty():
            sig = signal_q.get_nowait()
            s, side, strength = sig["symbol"], sig["side"], sig["strength"]
            px = prices.get(s, 0.0)
            if px <= 0: print(f"[SKIP] no price for {s}"); continue
            notional = max(5.0, BASE_QTY * max(0.1, min(2.0, strength)))
            if side == "buy":
                qty = ledger.buy(s, px, notional)
                log_trade(TRADES_CSV, int(time.time()), s, "buy", qty, px, notional, ledger.realized_pnl)
                print(f"[BUY ] {s} qty={qty:.6f} @ {px:.6f} notional≈{notional:.2f}")
            elif side == "sell":
                qty = ledger.sell(s, px, notional)
                log_trade(TRADES_CSV, int(time.time()), s, "sell", qty, px, notional, ledger.realized_pnl)
                print(f"[SELL] {s} qty={qty:.6f} @ {px:.6f} notional≈{notional:.2f}")
        # 3) write state & serve
        now = time.time()
        if now - last_write > 1.5:
            last_state = write_state_file(prices, ledger)
            last_write = now
        # 4) brief status
        upnl_total = sum(ledger.unrealized(s, prices.get(s,0.0)) for s in SYMBOLS)
        print(("PAUSED | " if paused else "") + " | ".join([f"{s}:{prices.get(s,0.0):.6f}" for s in SYMBOLS]) + f" || RPNL {ledger.realized_pnl:.2f} UPNL {upnl_total:.2f}")
        time.sleep(POLL_SEC)

if __name__ == "__main__":
    run()
