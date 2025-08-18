
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

headers = {"Authorization": f"Bot {BOT_TOKEN}"}
url = f"https://discord.com/api/v10/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands"

commands = [
    {
        "name": "price",
        "description": "Get last price",
        "options": [{"name": "symbol", "description": "e.g. BTCUSDT", "type": 3, "required": True}],
        "type": 1
    },
    {"name": "balance", "description": "Show non-zero balances", "type": 1},
    {
        "name": "buy", "description": "Buy on Binance Spot Testnet", "type": 1,
        "options": [
            {"name": "symbol", "description": "e.g. BTCUSDT", "type": 3, "required": True},
            {"name": "qty", "description": "Quantity", "type": 10, "required": True},
            {"name": "type", "description": "market or limit", "type": 3, "required": True, "choices": [{"name": "market", "value": "market"}, {"name": "limit", "value": "limit"}]},
            {"name": "price", "description": "Price if limit", "type": 10, "required": False}
        ]
    },
    {
        "name": "sell", "description": "Sell on Binance Spot Testnet", "type": 1,
        "options": [
            {"name": "symbol", "description": "e.g. BTCUSDT", "type": 3, "required": True},
            {"name": "qty", "description": "Quantity", "type": 10, "required": True},
            {"name": "type", "description": "market or limit", "type": 3, "required": True, "choices": [{"name": "market", "value": "market"}, {"name": "limit", "value": "limit"}]},
            {"name": "price", "description": "Price if limit", "type": 10, "required": False}
        ]
    },
    {
        "name": "oco", "description": "OCO take-profit/stop-loss sell", "type": 1,
        "options": [
            {"name": "symbol", "description": "e.g. BTCUSDT", "type": 3, "required": True},
            {"name": "qty", "description": "Quantity", "type": 10, "required": True},
            {"name": "tp", "description": "Take Profit price", "type": 10, "required": True},
            {"name": "sp", "description": "Stop Price", "type": 10, "required": True},
            {"name": "sl", "description": "Stop Limit (optional)", "type": 10, "required": False}
        ]
    }
]

def main():
    with httpx.Client(timeout=30) as client:
        for cmd in commands:
            r = client.post(url, headers=headers, json=cmd)
            r.raise_for_status()
            print("Registered:", cmd["name"])

if __name__ == "__main__":
    if not BOT_TOKEN or not APPLICATION_ID or not GUILD_ID:
        raise RuntimeError("Missing env: DISCORD_BOT_TOKEN, DISCORD_APPLICATION_ID, GUILD_ID")
    main()
