import requests
import yfinance as yf
import json
import os

TARGET_PRICE = 3146.6  # your alert price
STOCK = "TCS.NS"    # NSE example

ULTRA_MSG_INSTANCE = os.getenv("ULTRA_MSG_INSTANCE")
ULTRA_MSG_TOKEN = os.getenv("ULTRA_MSG_TOKEN")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER")

STATE_FILE = "state.json"

# ----- Load state -----
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"alert_sent": False}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ----- WhatsApp Sender -----
def send_whatsapp_message(message):
    url = f"https://api.ultramsg.com/{ULTRA_MSG_INSTANCE}/messages/chat"
    payload = {
        "token": ULTRA_MSG_TOKEN,
        "to": WHATSAPP_NUMBER,
        "body": message
    }
    r = requests.post(url, json=payload)
    print("WhatsApp Status:", r.text)

# ----- Main Logic -----
def check_stock():
    state = load_state()
    price = yf.Ticker(STOCK).history(period="1m")["Close"].iloc[-1]
    print("Current Price:", price)

    if price >= TARGET_PRICE and not state["alert_sent"]:
        send_whatsapp_message(f"🚨 {STOCK} hit {price} (Target: {TARGET_PRICE})")
        state["alert_sent"] = True
        save_state(state)

    if price < TARGET_PRICE:
        state["alert_sent"] = False
        save_state(state)

check_stock()
