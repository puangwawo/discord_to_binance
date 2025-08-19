#!/usr/bin/env python3
"""
Flask backend to place TESTNET orders and send Telegram notifications.
- Keeps API keys SECRET on the server (do NOT put secrets in index.xhtml).
- Endpoints:
  POST /api/order  JSON: {symbol, side, quoteOrderQty, tpPct?, slPct?}
    -> places MARKET order on Binance Testnet and sends a Telegram message on open/close.
- Env:
  BINANCE_API_KEY, BINANCE_API_SECRET, USE_TESTNET=true, LIVE_TRADING=true/false
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""
import os, time, hmac, hashlib, json
from typing import Dict
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY","")
API_SECRET = os.getenv("BINANCE_API_SECRET","")
USE_TESTNET = os.getenv("USE_TESTNET","true").lower()=="true"
LIVE_TRADING = os.getenv("LIVE_TRADING","true").lower()=="true"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN","")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

REST_BASE = "https://testnet.binance.vision" if USE_TESTNET else "https://api.binance.com"

app = Flask(__name__)
CORS(app)

session = requests.Session()

def ts_ms(): return int(time.time()*1000)

def sign(params: Dict[str,str]) -> Dict[str,str]:
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params

def tg_send(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        session.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception:
        pass

def market_order(symbol: str, side: str, quoteOrderQty: float):
    if not LIVE_TRADING:
        return {"status":"simulated", "symbol":symbol, "side":side, "quoteOrderQty":quoteOrderQty}
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Missing API keys")
    params = {"symbol":symbol, "side":side.upper(), "type":"MARKET",
              "quoteOrderQty": quoteOrderQty, "timestamp": ts_ms()}
    headers = {"X-MBX-APIKEY": API_KEY}
    r = session.post(f"{REST_BASE}/api/v3/order", params=sign(params), headers=headers)
    if r.status_code >= 400:
        return {"status":"error", "detail": r.text, "code": r.status_code}
    return r.json()

@app.post("/api/order")
def api_order():
    try:
        data = request.get_json(force=True)
        symbol = str(data.get("symbol","")).upper()
        side = str(data.get("side","")).upper()
        q = float(data.get("quoteOrderQty", 10))
        tp = data.get("tpPct"); sl = data.get("slPct")
        resp = market_order(symbol, side, q)
        msg = f"📣 {symbol} {side} ~qUSDT={q} @TESTNET"
        if tp is not None and sl is not None:
            msg += f" | TP {float(tp)*100:.2f}%, SL {float(sl)*100:.2f}%"
        tg_send(msg)
        return jsonify({"ok":True, "binance": resp})
    except Exception as e:
        return jsonify({"ok":False, "error": str(e)}), 400

@app.get("/api/ping")
def ping():
    return jsonify({"ok":True, "testnet": USE_TESTNET, "live": LIVE_TRADING})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")), debug=False)
