import asyncio
import os
import pytz
import certifi
import requests
import yfinance as yf
from datetime import datetime, time
from flask import Flask
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


from dotenv import load_dotenv
load_dotenv()
# --- ENV LOAD ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

# --- DB & SESSION SETUP ---
client = AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["stock_db"]
collection = db["stocks"]

# Use a session with a real browser Header to avoid Yahoo blocking
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
})

monitoring = False

# --- WEB SERVER FOR RENDER ---
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot is active"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host='0.0.0.0', port=port)

# --- UTILS ---
async def get_stocks():
    return {doc["symbol"]: doc["target"] async for doc in collection.find()}

def is_market_open():
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    if now.weekday() >= 5: return False
    return time(9, 15) <= now.time() <= time(15, 30)

# --- CORE MONITORING ---
async def monitor_loop(app, chat_id):
    global monitoring
    while monitoring:
        try:
            if not is_market_open():
                await asyncio.sleep(600)
                continue
            
            stocks = await get_stocks()
            for sym, target in stocks.items():
                ticker = yf.Ticker(sym, session=session)
                data = ticker.history(period="1d", interval="1m")
                if data.empty: continue
                
                curr = data['Close'].iloc[-1]
                if curr >= target:
                    await app.bot.send_message(chat_id=chat_id, text=f"🚀 *{sym}* hit target ₹{target}!\nCurrent: ₹{curr:.2f}", parse_mode="Markdown")
            
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"Loop Error: {e}")
            await asyncio.sleep(20)

# --- COMMANDS ---
async def start(update, context):
    global monitoring
    if not monitoring:
        monitoring = True
        asyncio.create_task(monitor_loop(context.application, update.effective_chat.id))
        await update.message.reply_text("✅ Monitoring Started.")
    else:
        await update.message.reply_text("⚡ Already running.")

async def status(update, context):
    stocks = await get_stocks()
    if not stocks: return await update.message.reply_text("List is empty.")
    
    msg = "📋 *Status:*\n"
    for s, t in stocks.items():
        try:
            val = yf.Ticker(s, session=session).history(period="1d")['Close'].iloc[-1]
            msg += f"• {s}: ₹{val:.2f} (Target: ₹{t})\n"
        except: msg += f"• {s}: Fetch Error\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def add(update, context):
    try:
        sym, target = context.args[0].upper(), float(context.args[1])
        await collection.update_one({"symbol": sym}, {"$set": {"symbol": sym, "target": target}}, upsert=True)
        await update.message.reply_text(f"Added {sym} @ {target}")
    except: await update.message.reply_text("Usage: /add SYMBOL TARGET")

async def remove(update, context):
    try:
        sym = context.args[0].upper()
        await collection.delete_one({"symbol": sym})
        await update.message.reply_text(f"Removed {sym}")
    except: pass

# --- MAIN ---
if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start() # Start Web Server
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    
    print("Bot starting...")
    app.run_polling(drop_pending_updates=True) # THIS LINE IS CRUCIAL TO STOP CONFLICTS
