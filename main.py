import asyncio
import os
import json
import pytz
import certifi
import yfinance as yf
from datetime import datetime, time
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Load Environment Variables ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHECK_INTERVAL = 30

# --- Database Setup ---
# tlsCAFile=certifi.where() ensures SSL handshakes work on all systems
client = AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["stock_db"]
collection = db["stocks"]

# --- Global State ---
monitoring = False

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

# --- Market logic ---
def is_market_open():
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    if now.weekday() >= 5: # Saturday & Sunday
        return False
    # NSE Market hours
    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= now.time() <= market_close

def is_valid_stock(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1d")
        return not data.empty
    except:
        return False

# --- Background Monitor Loop ---
async def monitor_stock(app, chat_id):
    global monitoring
    print("🚀 Background monitoring task started.")
    last_heartbeat = 0  # To track hourly console logs
    
    while monitoring:
        try:
            current_time_unix = asyncio.get_event_loop().time()
            
            # --- Heartbeat Logic (Every 1 hour) ---
            if current_time_unix - last_heartbeat > 3600:
                print(f"💓 Heartbeat: Bot is active at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                last_heartbeat = current_time_unix

            if not is_market_open():
                # Sleep longer if market is closed, but check again in 10 mins
                await asyncio.sleep(600) 
                continue

            stocks_to_check = await get_all_stocks()
            if not stocks_to_check:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for symbol, target in stocks_to_check.items():
                try:
                    ticker = yf.Ticker(symbol)
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
                    print(f"⚠️ Error fetching {symbol}: {e}")

        except Exception as e:
            # Handles ConnectTimeout, Network drops, etc.
            print(f"📡 Network/Loop Error: {e}. Retrying in 15s...")
            await asyncio.sleep(15)
            continue

        await asyncio.sleep(CHECK_INTERVAL)
# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    
    # 1. Basic check for existing stocks
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("❌ Your database is empty. Use `/add SYMBOL TARGET` first.", parse_mode="Markdown")
        return

    # 2. Prevent duplicate monitor tasks
    if monitoring:
        await update.message.reply_text("⚡ Monitoring is already active and running in the background.")
        return

    # 3. Start the background loop
    monitoring = True
    asyncio.create_task(monitor_stock(context.application, update.effective_chat.id))
    
    # 4. Immediate Status Report
    await update.message.reply_text("✅ *Monitoring Started!* Fetching current market snapshot...")
    
    summary_msg = "📋 *Initial Portfolio Snapshot:*\n" + "—" * 20 + "\n"
    
    for symbol, target in stocks.items():
        try:
            ticker = yf.Ticker(symbol)
            # Fetching 1-day history to get the latest closing price
            data = ticker.history(period="1d")
            if not data.empty:
                current_price = data['Close'].iloc[-1]
                # Logic to show if price is already above target
                status = "🚀" if current_price >= target else "⏳"
                summary_msg += f"{status} *{symbol}*\n   Current: ₹{current_price:.2f}\n   Target: ₹{target:.2f}\n\n"
            else:
                summary_msg += f"⚠️ *{symbol}*: No data found.\n\n"
        except Exception as e:
            summary_msg += f"❌ *{symbol}*: Error fetching price.\n\n"

    await update.message.reply_text(summary_msg, parse_mode="Markdown")

    
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    monitoring = False
    await update.message.reply_text("🛑 Monitoring stopped.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        target = float(context.args[1])
        
        await update.message.reply_text(f"🔍 Validating {symbol}...")
        if not is_valid_stock(symbol):
            await update.message.reply_text(f"❌ {symbol} is not a valid symbol on Yahoo Finance.")
            return

        await add_stock_db(symbol, target)
        await update.message.reply_text(f"➕ Added *{symbol}* with target *₹{target}*", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/add SYMBOL TARGET` (e.g., `/add RELIANCE.NS 2500`)", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        await remove_stock_db(symbol)
        await update.message.reply_text(f"➖ Removed {symbol} from monitoring.")
    except IndexError:
        await update.message.reply_text("Usage: `/remove SYMBOL`", parse_mode="Markdown")

async def update_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reuses add logic because of upsert=True
    await add(update, context)

async def current_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("ℹ️ Your monitoring list is empty.")
        return

    await update.message.reply_text("📊 Fetching latest prices...")
    msg = "📋 *Live Stock Status*\n" + "—" * 15 + "\n"
    
    for symbol, target in stocks.items():
        try:
            data = yf.Ticker(symbol).history(period="1d", interval="1m")
            current = data['Close'].iloc[-1] if not data.empty else "N/A"
            diff = target - current if isinstance(current, float) else 0
            
            status_icon = "📈" if isinstance(current, float) and current >= target else "⏳"
            msg += f"{status_icon} *{symbol}*\n   Current: ₹{current:.2f}\n   Target: ₹{target:.2f}\n"
            if diff > 0:
                msg += f"   _Needs ₹{diff:.2f} more to hit target_\n\n"
            else:
                msg += "   🚀 *Target Reached!*\n\n"
        except:
            msg += f"❌ {symbol}: Error fetching data\n\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("ℹ️ List is empty.")
        return
    msg = "📂 *Monitored Symbols:*\n"
    for s, t in stocks.items():
        msg += f"• {s} (Target: {t})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Stock Bot Help*\n\n"
        "/add SYMBOL TARGET - Add/Update stock\n"
        "/remove SYMBOL - Delete stock\n"
        "/status - Show prices vs targets\n"
        "/list - List all saved stocks\n"
        "/start - Start background alerts\n"
        "/stop - Pause background alerts"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- Main Entry Point ---
def main():
    if not TOKEN or not MONGO_URI:
        print("Missing environment variables. Check your .env file.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("update", update_target))
    app.add_handler(CommandHandler("status", current_status))
    app.add_handler(CommandHandler("list", list_stocks))
    app.add_handler(CommandHandler("help", help_command))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()import asyncio
import os
import json
import pytz
import certifi
import yfinance as yf
from datetime import datetime, time
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Load Environment Variables ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHECK_INTERVAL = 30

# --- Database Setup ---
# tlsCAFile=certifi.where() ensures SSL handshakes work on all systems
client = AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["stock_db"]
collection = db["stocks"]

# --- Global State ---
monitoring = False

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

# --- Market logic ---
def is_market_open():
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    if now.weekday() >= 5: # Saturday & Sunday
        return False
    # NSE Market hours
    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= now.time() <= market_close

def is_valid_stock(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1d")
        return not data.empty
    except:
        return False

# --- Background Monitor Loop ---
async def monitor_stock(app, chat_id):
    global monitoring
    print("🚀 Background monitoring task started.")
    last_heartbeat = 0  # To track hourly console logs
    
    while monitoring:
        try:
            current_time_unix = asyncio.get_event_loop().time()
            
            # --- Heartbeat Logic (Every 1 hour) ---
            if current_time_unix - last_heartbeat > 3600:
                print(f"💓 Heartbeat: Bot is active at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                last_heartbeat = current_time_unix

            if not is_market_open():
                # Sleep longer if market is closed, but check again in 10 mins
                await asyncio.sleep(600) 
                continue

            stocks_to_check = await get_all_stocks()
            if not stocks_to_check:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for symbol, target in stocks_to_check.items():
                try:
                    ticker = yf.Ticker(symbol)
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
                    print(f"⚠️ Error fetching {symbol}: {e}")

        except Exception as e:
            # Handles ConnectTimeout, Network drops, etc.
            print(f"📡 Network/Loop Error: {e}. Retrying in 15s...")
            await asyncio.sleep(15)
            continue

        await asyncio.sleep(CHECK_INTERVAL)
# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    
    # 1. Basic check for existing stocks
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("❌ Your database is empty. Use `/add SYMBOL TARGET` first.", parse_mode="Markdown")
        return

    # 2. Prevent duplicate monitor tasks
    if monitoring:
        await update.message.reply_text("⚡ Monitoring is already active and running in the background.")
        return

    # 3. Start the background loop
    monitoring = True
    asyncio.create_task(monitor_stock(context.application, update.effective_chat.id))
    
    # 4. Immediate Status Report
    await update.message.reply_text("✅ *Monitoring Started!* Fetching current market snapshot...")
    
    summary_msg = "📋 *Initial Portfolio Snapshot:*\n" + "—" * 20 + "\n"
    
    for symbol, target in stocks.items():
        try:
            ticker = yf.Ticker(symbol)
            # Fetching 1-day history to get the latest closing price
            data = ticker.history(period="1d")
            if not data.empty:
                current_price = data['Close'].iloc[-1]
                # Logic to show if price is already above target
                status = "🚀" if current_price >= target else "⏳"
                summary_msg += f"{status} *{symbol}*\n   Current: ₹{current_price:.2f}\n   Target: ₹{target:.2f}\n\n"
            else:
                summary_msg += f"⚠️ *{symbol}*: No data found.\n\n"
        except Exception as e:
            summary_msg += f"❌ *{symbol}*: Error fetching price.\n\n"

    await update.message.reply_text(summary_msg, parse_mode="Markdown")

    
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    monitoring = False
    await update.message.reply_text("🛑 Monitoring stopped.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        target = float(context.args[1])
        
        await update.message.reply_text(f"🔍 Validating {symbol}...")
        if not is_valid_stock(symbol):
            await update.message.reply_text(f"❌ {symbol} is not a valid symbol on Yahoo Finance.")
            return

        await add_stock_db(symbol, target)
        await update.message.reply_text(f"➕ Added *{symbol}* with target *₹{target}*", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/add SYMBOL TARGET` (e.g., `/add RELIANCE.NS 2500`)", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        await remove_stock_db(symbol)
        await update.message.reply_text(f"➖ Removed {symbol} from monitoring.")
    except IndexError:
        await update.message.reply_text("Usage: `/remove SYMBOL`", parse_mode="Markdown")

async def update_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reuses add logic because of upsert=True
    await add(update, context)

async def current_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("ℹ️ Your monitoring list is empty.")
        return

    await update.message.reply_text("📊 Fetching latest prices...")
    msg = "📋 *Live Stock Status*\n" + "—" * 15 + "\n"
    
    for symbol, target in stocks.items():
        try:
            data = yf.Ticker(symbol).history(period="1d", interval="1m")
            current = data['Close'].iloc[-1] if not data.empty else "N/A"
            diff = target - current if isinstance(current, float) else 0
            
            status_icon = "📈" if isinstance(current, float) and current >= target else "⏳"
            msg += f"{status_icon} *{symbol}*\n   Current: ₹{current:.2f}\n   Target: ₹{target:.2f}\n"
            if diff > 0:
                msg += f"   _Needs ₹{diff:.2f} more to hit target_\n\n"
            else:
                msg += "   🚀 *Target Reached!*\n\n"
        except:
            msg += f"❌ {symbol}: Error fetching data\n\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def list_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.message.reply_text("ℹ️ List is empty.")
        return
    msg = "📂 *Monitored Symbols:*\n"
    for s, t in stocks.items():
        msg += f"• {s} (Target: {t})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Stock Bot Help*\n\n"
        "/add SYMBOL TARGET - Add/Update stock\n"
        "/remove SYMBOL - Delete stock\n"
        "/status - Show prices vs targets\n"
        "/list - List all saved stocks\n"
        "/start - Start background alerts\n"
        "/stop - Pause background alerts"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# --- Main Entry Point ---
def main():
    if not TOKEN or not MONGO_URI:
        print("Missing environment variables. Check your .env file.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("update", update_target))
    app.add_handler(CommandHandler("status", current_status))
    app.add_handler(CommandHandler("list", list_stocks))
    app.add_handler(CommandHandler("help", help_command))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
