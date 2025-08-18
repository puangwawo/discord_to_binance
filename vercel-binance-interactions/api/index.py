
import os
import json
import math
from typing import Dict, Any, Tuple, Union

from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from binance.spot import Spot as BinanceSpot

load_dotenv()

DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
ALLOWED_SYMBOLS = {s.strip().upper() for s in os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT").split(",") if s.strip()}
BINANCE_BASE_URL = "https://testnet.binance.vision"

app = FastAPI()

def verify_signature(signature: str, timestamp: str, body: bytes) -> bool:
    if not DISCORD_PUBLIC_KEY:
        return False
    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except BadSignatureError:
        return False

def round_step(value: float, step: float) -> float:
    if step == 0:
        return value
    precision = int(round(-math.log10(step))) if step < 1 else 0
    return float(f"{(math.floor(value / step) * step):.{precision}f}")

def sanitize_symbol(symbol: str) -> str:
    return symbol.replace(" ", "").upper()

class BinanceClient:
    def __init__(self) -> None:
        self.client = BinanceSpot(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET, base_url=BINANCE_BASE_URL)
        self.rules: Dict[str, Dict[str, Any]] = {}
        self._load_rules()

    def _load_rules(self) -> None:
        info = self.client.exchange_info()
        for s in info.get("symbols", []):
            symbol = s.get("symbol")
            if not symbol:
                continue
            filters = {f["filterType"]: f for f in s.get("filters", [])}
            lot = filters.get("LOT_SIZE", {})
            tick = filters.get("PRICE_FILTER", {})
            self.rules[symbol] = {
                "stepSize": float(lot.get("stepSize", 0.0)) if lot else 0.0,
                "tickSize": float(tick.get("tickSize", 0.0)) if tick else 0.0,
            }

    def _round_for(self, symbol: str, qty: float, price: Union[float, None] = None) -> Tuple[float, Union[float, None]]:
        r = self.rules.get(symbol, {})
        step = r.get("stepSize", 0.0) or 0.0
        tick = r.get("tickSize", 0.0) or 0.0
        if step:
            qty = round_step(qty, step)
        if price is not None and tick:
            price = round_step(price, tick)
        return qty, price

    def price(self, symbol: str) -> float:
        data = self.client.ticker_price(symbol)
        return float(data["price"])

    def balance(self) -> Dict[str, float]:
        acct = self.client.account()
        out: Dict[str, float] = {}
        for b in acct.get("balances", []):
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            total = free + locked
            if total > 0:
                out[b["asset"]] = total
        return out

    def order_market(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        q, _ = self._round_for(symbol, quantity)
        return self.client.new_order(symbol=symbol, side=side, type="MARKET", quantity=q)

    def order_limit(self, symbol: str, side: str, quantity: float, price: float, tif: str = "GTC") -> Dict[str, Any]:
        q, p = self._round_for(symbol, quantity, price)
        if p is None:
            raise ValueError("price required")
        return self.client.new_order(symbol=symbol, side=side, type="LIMIT", timeInForce=tif, quantity=q, price=f"{p}")

    def order_oco(self, symbol: str, side: str, quantity: float, take_profit: float, stop_price: float, stop_limit: Union[float, None] = None, tif: str = "GTC") -> Dict[str, Any]:
        q, tp = self._round_for(symbol, quantity, take_profit)
        _, sp = self._round_for(symbol, quantity, stop_price)
        if stop_limit is None:
            tick = self.rules.get(symbol, {}).get("tickSize", 0.0)
            stop_limit = (sp or stop_price) - (tick * 2 if tick else 0.0001)
        _, sl = self._round_for(symbol, quantity, stop_limit)
        return self.client.new_oco_order(symbol=symbol, side=side, quantity=q, price=f"{tp}", stopPrice=f"{sp}", stopLimitPrice=f"{sl}", stopLimitTimeInForce=tif)

binance = BinanceClient()

PING = 1
COMMAND = 2
RESPOND_CHANNEL = 4

def json_response(d: dict, status: int = 200) -> Response:
    return Response(content=json.dumps(d), status_code=status, media_type="application/json")

@app.get("/")
def health():
    return {"ok": True}

@app.post("/")
async def interactions(req: Request):
    sig = req.headers.get("X-Signature-Ed25519") or ""
    ts = req.headers.get("X-Signature-Timestamp") or ""
    body = await req.body()
    if not verify_signature(sig, ts, body):
        return Response(status_code=401)
    payload = json.loads(body.decode())
    t = payload.get("type")
    if t == PING:
        return json_response({"type": 1})
    if t != COMMAND:
        return json_response({"type": 4, "data": {"flags": 64, "content": "Unsupported interaction"}})
    data = payload.get("data", {})
    name = data.get("name")
    options = {opt["name"]: opt.get("value") for opt in data.get("options", [])} if data.get("options") else {}

    if name == "price":
        symbol = sanitize_symbol(str(options.get("symbol", "BTCUSDT")))
        if ALLOWED_SYMBOLS and symbol not in ALLOWED_SYMBOLS:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"Symbol `{symbol}` not allowed"}})
        try:
            p = binance.price(symbol)
            return json_response({"type": RESPOND_CHANNEL, "data": {"content": f"**{symbol}** last price: `{p}`"}})
        except Exception as e:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"Error: {e}"}})

    if name == "balance":
        try:
            bal = binance.balance()
            if not bal:
                return json_response({"type": RESPOND_CHANNEL, "data": {"content": "No balances"}})
            lines = [f"**{a}**: `{amt}`" for a, amt in sorted(bal.items())]
            return json_response({"type": RESPOND_CHANNEL, "data": {"content": "Balances:\n" + "\n".join(lines)}})
        except Exception as e:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"Error: {e}"}})

    if name == "buy":
        symbol = sanitize_symbol(str(options.get("symbol", "BTCUSDT")))
        qty = float(options.get("qty", 0))
        order_type = str(options.get("type", "market")).lower()
        if ALLOWED_SYMBOLS and symbol not in ALLOWED_SYMBOLS:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"Symbol `{symbol}` not allowed"}})
        try:
            if order_type == "market":
                resp = binance.order_market(symbol, "BUY", qty)
            else:
                price = float(options.get("price"))
                resp = binance.order_limit(symbol, "BUY", qty, price)
            return json_response({"type": RESPOND_CHANNEL, "data": {"content": f"BUY ok: `{resp}`"}})
        except Exception as e:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"BUY failed: {e}"}})

    if name == "sell":
        symbol = sanitize_symbol(str(options.get("symbol", "BTCUSDT")))
        qty = float(options.get("qty", 0))
        order_type = str(options.get("type", "market")).lower()
        if ALLOWED_SYMBOLS and symbol not in ALLOWED_SYMBOLS:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"Symbol `{symbol}` not allowed"}})
        try:
            if order_type == "market":
                resp = binance.order_market(symbol, "SELL", qty)
            else:
                price = float(options.get("price"))
                resp = binance.order_limit(symbol, "SELL", qty, price)
            return json_response({"type": RESPOND_CHANNEL, "data": {"content": f"SELL ok: `{resp}`"}})
        except Exception as e:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"SELL failed: {e}"}})

    if name == "oco":
        symbol = sanitize_symbol(str(options.get("symbol", "BTCUSDT")))
        qty = float(options.get("qty", 0))
        tp = float(options.get("tp"))
        sp = float(options.get("sp"))
        sl = options.get("sl")
        slf = float(sl) if sl is not None else None
        if ALLOWED_SYMBOLS and symbol not in ALLOWED_SYMBOLS:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"Symbol `{symbol}` not allowed"}})
        try:
            resp = binance.order_oco(symbol, "SELL", qty, tp, sp, slf)
            return json_response({"type": RESPOND_CHANNEL, "data": {"content": f"OCO ok: `{resp}`"}})
        except Exception as e:
            return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": f"OCO failed: {e}"}})

    return json_response({"type": RESPOND_CHANNEL, "data": {"flags": 64, "content": "Unknown command"}})
