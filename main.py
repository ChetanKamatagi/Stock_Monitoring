import asyncio
import os
import pytz
import certifi
import yfinance as yf
from datetime import datetime, time
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from curl_cffi import requests as curl_requests
from flask import Flask
from threading import Thread

# --- Load Environment Variables ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHECK_INTERVAL = 30  # Optimized for performance

# --- Stealth Session for Yahoo Finance ---
# This impersonates a real Chrome browser to bypass Yahoo's bot detection
stock_session = curl_requests.Session(impersonate="chrome")

# --- Database Setup ---
client = AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["stock_db"]
collection = db["stocks"]

# --- Global State ---
monitoring = False

# --- Flask Server for Render Keep-Alive ---
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "✅ Stock Bot is Live and Monitoring!"

def run_web_server():
    # Render provides the PORT variable automatically
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --- Database Helper Functions ---
async def get_all_stocks():
    stocks = {}
    async for doc in collection.find():
        stocks[doc["symbol"]] = doc["target"]
    return stocks

async def add_stock_db(symbol, target):
    await collection.update_one(
        {"symbol": symbol},
        {"$set": {"symbol": symbol, "target": target, "updated_at": datetime.now()}},
        upsert=True
    )

async def remove_stock_db(symbol):
    await collection.delete_one({"symbol": symbol})

# --- Market Logic ---
def is_market_open():
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    if now.weekday() >= 5: return False # Sat & Sun closed
    return time(9, 15) <= now.time() <= time(15, 30)

def is_valid_stock(symbol):
    try:
        ticker = yf.Ticker(symbol, session=stock_session)
        data = ticker.history(period="1d")
        return not data.empty
    except:
        return False

# --- Background Monitor Loop ---
async def monitor_stock(app, chat_id):
    global monitoring
    print("🚀 Background monitoring task started.")
    last_heartbeat = 0
    
    while monitoring:
        try:
            now_unix = asyncio.get_event_loop().time()
            # Hourly Heartbeat log
            if now_unix - last_heartbeat > 3600:
                print(f"💓 Heartbeat: Active at {datetime.now().strftime('%H:%M:%S')}")
                last_heartbeat = now_unix

            if not is_market_open():
                await asyncio.sleep(600) 
                continue

            stocks_to_check = await get_all_stocks()
            if not stocks_to_check:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for symbol, target in stocks_to_check.items():
                try:
                    ticker = yf.Ticker(symbol, session=stock_session)
                    data = ticker.history(period="1d", interval="1m")
                    if data.empty: continue
                    
                    current_price = data['Close'].iloc[-1]
                    if current_price >= target:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=f"🚀 *TARGET HIT!* 🚀\n\n*Stock:* {symbol}\n*Current:* ₹{current_price:.2f}\n*Target:* ₹{target:.2f}",
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    print(f"⚠️ Yahoo Fetch Error ({symbol}): {e}")

        except Exception as e:
            print(f"📡 Loop Exception: {e}. Retrying in 15s...")
            await asyncio.sleep(15)
            continue

        await asyncio.sleep(CHECK_INTERVAL)

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("❌ Your database is empty. Use `/add SYMBOL TARGET` first.", parse_mode="Markdown")
        return

    if not monitoring:
        monitoring = True
        asyncio.create_task(monitor_stock(context.application, update.effective_chat.id))
        await update.message.reply_text("✅ *Monitoring Activated!*", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚡ Monitoring is already running.")

    # Immediate snapshot
    summary_msg = "📋 *Live Snapshot:*\n" + "—" * 15 + "\n"
    for s, t in stocks.items():
        try:
            curr = yf.Ticker(s, session=stock_session).history(period="1d")['Close'].iloc[-1]
            status = "🚀" if curr >= t else "⏳"
            summary_msg += f"{status} *{s}*\n   Curr: ₹{curr:.2f} | Target: ₹{t:.2f}\n\n"
        except:
            summary_msg += f"❌ *{s}*: Error fetching price.\n\n"
    await update.message.reply_text(summary_msg, parse_mode="Markdown")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    monitoring = False
    await update.message.reply_text("🛑 Monitoring stopped.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol, target = context.args[0].upper(), float(context.args[1])
        if not is_valid_stock(symbol):
            await update.message.reply_text(f"❌ Invalid symbol: {symbol}")
            return
        await add_stock_db(symbol, target)
        await update.message.reply_text(f"➕ Added *{symbol}* at target ₹{target}", parse_mode="Markdown")
    except:
        await update.message.reply_text("Usage: `/add SYMBOL TARGET`", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        await remove_stock_db(symbol)
        await update.message.reply_text(f"➖ Removed {symbol}.")
    except:
        await update.message.reply_text("Usage: `/remove SYMBOL`", parse_mode="Markdown")

async def current_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("ℹ️ Your list is empty.")
        return
    msg = "📊 *Live Status:*\n"
    for s, t in stocks.items():
        try:
            curr = yf.Ticker(s, session=stock_session).history(period="1d")['Close'].iloc[-1]
            icon = "📈" if curr >= t else "⏳"
            msg += f"{icon} *{s}*: Curr ₹{curr:.2f}, Target ₹{t:.2f}\n"
        except:
            msg += f"❌ {s}: Data error\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    msg = "📂 *Watchlist:*\n" + "\n".join([f"• {s} (Target: {t})" for s, t in stocks.items()])
    await update.message.reply_text(msg if stocks else "List is empty.", parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = "🤖 *Commands:*\n/add, /remove, /status, /list, /start, /stop"
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- Main ---
def main():
    keep_alive() # Run Flask server
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("update", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("status", current_status))
    app.add_handler(CommandHandler("list", list_stocks))
    app.add_handler(CommandHandler("help", help_command))

    print("Bot is polling...")
    # drop_pending_updates=True fixes the "Conflict" error on Render restarts
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
