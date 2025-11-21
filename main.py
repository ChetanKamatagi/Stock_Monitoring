import asyncio
import json
import os
from datetime import datetime, time

import pytz
import yfinance as yf
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Config ---
TOKEN = '8377657688:AAGLA9_wowQN3prT_9m563AdPoes44mTKkM'
CHECK_INTERVAL = 60  # seconds between price checks
DATA_FILE = "stocks.json"  # persistent storage

# --- Global variables ---
monitored_stocks = {}  # {symbol: target_price}
monitoring = False


# --- Persistence functions ---
def load_stocks():
    global monitored_stocks
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            monitored_stocks = json.load(f)
    else:
        monitored_stocks = {}

def save_stocks():
    with open(DATA_FILE, "w") as f:
        json.dump(monitored_stocks, f, indent=4)

# --- Check if NSE market is open ---
def is_market_open():
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    weekday = now.weekday()  # Monday=0, Sunday=6
    if weekday >= 5:  # Saturday or Sunday
        return False
    market_open = time(9, 17)
    market_close = time(17, 30)
    return market_open <= now.time() <= market_close

# --- Validate stock symbol ---
def is_valid_stock(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1d", interval="1m")
        if data.empty:
            return False
        return True
    except Exception:
        return False

# --- Monitor stocks ---
async def monitor_stock(app, chat_id):
    global monitoring
    while monitoring:
        if not is_market_open():
            await app.bot.send_message(chat_id=chat_id, text="❌ Market is closed. Cannot monitor now.")
            await asyncio.sleep(CHECK_INTERVAL * 2)
            continue

        for symbol, target in list(monitored_stocks.items()):
            try:
                data = yf.Ticker(symbol).history(period="1d", interval="1m")
                if data.empty:
                    continue
                price = data['Close'].iloc[-1]
                print(f"{symbol}: Current price = {price}")
                if price >= target:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=f"🚀 {symbol} has reached the target price: ${price} (Target: {target})"
                    )
                    # Optionally remove after hitting target
                    # monitored_stocks.pop(symbol)
                    # save_stocks()
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    if monitoring:
        await update.effective_message.reply_text("⚡ Monitoring is already running.")
        return

    if not monitored_stocks:
        await update.effective_message.reply_text("❌ No stocks to monitor. Use /add first.")
        return

    if not is_market_open():
        await update.effective_message.reply_text("❌ Market is closed. Cannot monitor now.")
        return

    monitoring = True
    await update.effective_message.reply_text("✅ Started monitoring your stocks!")
    for symbol in monitored_stocks:
        try:
            data = yf.Ticker(symbol).history(period="1d", interval="1m")
            if data.empty:
                continue
            price = data['Close'].iloc[-1]
            await update.effective_message.reply_text(
                f"📈 {symbol}: Current price = {price} (Target: {monitored_stocks[symbol]})"
            )
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error fetching {symbol}: {e}")

    asyncio.create_task(monitor_stock(context.application, update.effective_chat.id))

# --- /stop ---
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    if monitoring:
        monitoring = False
        await update.effective_message.reply_text("🛑 Stopped monitoring stocks.")
    else:
        await update.effective_message.reply_text("⚠ Monitoring is not running.")

# --- /add ---
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        target = float(context.args[1])

        if not is_valid_stock(symbol):
            await update.effective_message.reply_text(f"❌ {symbol} is an invalid stock symbol. Cannot add.")
            return

        monitored_stocks[symbol] = target
        save_stocks()
        await update.effective_message.reply_text(f"➕ Added {symbol} with target price {target}")
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /add SYMBOL TARGET (e.g., /add TMPV 360)")

# --- /remove ---
async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        if symbol in monitored_stocks:
            monitored_stocks.pop(symbol)
            save_stocks()
            await update.effective_message.reply_text(f"➖ Removed {symbol} from monitoring.")
        else:
            await update.effective_message.reply_text(f"{symbol} is not in monitoring list.")
    except IndexError:
        await update.effective_message.reply_text("Usage: /remove SYMBOL (e.g., /remove TMPV)")

# --- /update ---
async def update_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        new_target = float(context.args[1])
        if symbol in monitored_stocks:
            monitored_stocks[symbol] = new_target
            save_stocks()
            await update.effective_message.reply_text(f"🔄 Updated {symbol} target price to {new_target}")
        else:
            await update.effective_message.reply_text(f"{symbol} is not in monitoring list. Use /add first.")
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /update SYMBOL NEW_TARGET (e.g., /update TMPV 370)")

# --- /status ---
async def current_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not monitored_stocks:
        await update.effective_message.reply_text("ℹ No stocks are being monitored.")
        return

    msg = "📊 Current status of monitored stocks:\n\n"
    for symbol in monitored_stocks:
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if data.empty:
                msg += f"{symbol} - No data available\n"
                continue
            price = data['Close'].iloc[-1]
            full_name = ticker.info.get('shortName', 'N/A')
            target = monitored_stocks[symbol]
            msg += f"🐂 {symbol} ({full_name}) -> Current: {price:.2f}, Target: {target}\n"
        except Exception as e:
            msg += f"{symbol} - Error fetching data\n"

    await update.effective_message.reply_text(msg)

# --- /list ---
async def list_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if monitored_stocks:
        msg = "📊 Currently monitoring:\n"
        for symbol, target in monitored_stocks.items():
            msg += f"{symbol} -> {target}\n"
    else:
        msg = "ℹ No stocks are being monitored."
    await update.effective_message.reply_text(msg)

# --- /help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 Stock Monitor Bot Commands:\n\n"
        "/start - Start monitoring stocks\n"
        "/stop - Stop monitoring stocks\n"
        "/add SYMBOL TARGET - Add a stock (e.g., /add TMPV 360)\n"
        "/remove SYMBOL - Remove a stock (e.g., /remove TMPV)\n"
        "/update SYMBOL TARGET - Update stock target (e.g., /update TMPV 370)\n"
        "/list - List all monitored stocks\n"
        "/status - Check the current status of the monitored stocks\n"
        "/help - Show this help message\n\n"
        "✅ Stocks are saved and persist even if the bot restarts."
    )
    await update.effective_message.reply_text(help_text)

# --- Main ---
def main():
    load_stocks()  # Load saved stocks

    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("update", update_target))
    app.add_handler(CommandHandler("status", current_status))
    app.add_handler(CommandHandler("list", list_stocks))
    app.add_handler(CommandHandler("help", help_command))

    app.run_polling()

if __name__ == "__main__":
    main()
