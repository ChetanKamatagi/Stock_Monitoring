import asyncio
import os
from datetime import datetime, time

import pytz
import yfinance as yf
import asyncpg
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

print("The App has been started")
# --- Config ---
TOKEN = "8377657688:AAGLA9_wowQN3prT_9m563AdPoes44mTKkM"
DATABASE_URL = "postgresql://postgres:KLXeUHmnQTEdzcVFttkUQEVnwVZmZsqr@postgres.railway.internal:5432/railway"
CHECK_INTERVAL = 60  # seconds between price checks

if not TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN not set")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL not set")

# --- Global variables ---
monitoring = False
db_pool = None

# --- Database setup ---
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS monitored_stocks (
                symbol TEXT PRIMARY KEY,
                target NUMERIC
            )
        """)

# --- Helper functions ---
async def get_all_stocks():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT symbol, target FROM monitored_stocks")
        return {row['symbol']: float(row['target']) for row in rows}

async def add_stock(symbol, target):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO monitored_stocks(symbol, target)
            VALUES($1, $2)
            ON CONFLICT(symbol) DO UPDATE SET target = $2
        """, symbol, target)

async def remove_stock(symbol):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM monitored_stocks WHERE symbol=$1", symbol)

async def update_stock(symbol, target):
    await add_stock(symbol, target)

async def is_valid_stock(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1d", interval="1m")
        if data.empty:
            return False
        return True
    except Exception:
        return False

def is_market_open():
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(tz)
    weekday = now.weekday()
    if weekday >= 5:  # Saturday or Sunday
        return False
    market_open = time(9, 15)
    market_close = time(15, 30)
    return market_open <= now.time() <= market_close

# --- Monitor loop ---
async def monitor_stock(app, chat_id):
    global monitoring
    while monitoring:
        if not is_market_open():
            await app.bot.send_message(chat_id=chat_id, text="❌ Market is closed. Cannot monitor now.")
            await asyncio.sleep(CHECK_INTERVAL * 2)
            continue

        stocks = await get_all_stocks()
        for symbol, target in stocks.items():
            try:
                data = yf.Ticker(symbol).history(period="1d", interval="1m")
                if data.empty:
                    continue
                price = data['Close'].iloc[-1]
                if price >= target:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=f"🚀 {symbol} has reached the target price: {price} (Target: {target})"
                    )
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    if monitoring:
        await update.effective_message.reply_text("⚡ Monitoring is already running.")
        return

    stocks = await get_all_stocks()
    if not stocks:
        await update.effective_message.reply_text("❌ No stocks to monitor. Use /add first.")
        return

    if not is_market_open():
        await update.effective_message.reply_text("❌ Market is closed. Cannot monitor now.")
        return

    monitoring = True
    await update.effective_message.reply_text("✅ Started monitoring your stocks!")

    # Show current price
    for symbol, target in stocks.items():
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if data.empty:
                continue
            price = data['Close'].iloc[-1]
            name = ticker.info.get('shortName', 'N/A')
            await update.effective_message.reply_text(
                f"📈 {symbol} ({name}) -> Current: {price}, Target: {target}"
            )
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error fetching {symbol}: {e}")

    asyncio.create_task(monitor_stock(context.application, update.effective_chat.id))

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring
    if monitoring:
        monitoring = False
        await update.effective_message.reply_text("🛑 Stopped monitoring stocks.")
    else:
        await update.effective_message.reply_text("⚠ Monitoring is not running.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        target = float(context.args[1])
        if not await is_valid_stock(symbol):
            await update.effective_message.reply_text(f"❌ {symbol} is invalid. Cannot add.")
            return
        await add_stock(symbol, target)
        await update.effective_message.reply_text(f"➕ Added {symbol} with target {target}")
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /add SYMBOL TARGET")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        await remove_stock(symbol)
        await update.effective_message.reply_text(f"➖ Removed {symbol}")
    except IndexError:
        await update.effective_message.reply_text("Usage: /remove SYMBOL")

async def update_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        target = float(context.args[1])
        await update_stock(symbol, target)
        await update.effective_message.reply_text(f"🔄 Updated {symbol} target to {target}")
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /update SYMBOL TARGET")

async def list_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.effective_message.reply_text("ℹ No stocks monitored.")
        return
    msg = "📊 Currently monitored stocks:\n"
    for symbol, target in stocks.items():
        msg += f"{symbol} -> Target: {target}\n"
    await update.effective_message.reply_text(msg)

async def current_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stocks = await get_all_stocks()
    if not stocks:
        await update.effective_message.reply_text("ℹ No stocks monitored.")
        return
    msg = "📊 Current status:\n"
    for symbol, target in stocks.items():
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if data.empty:
                msg += f"{symbol} -> No data\n"
                continue
            price = data['Close'].iloc[-1]
            name = ticker.info.get('shortName', 'N/A')
            msg += f"{symbol} ({name}) -> Current: {price}, Target: {target}\n"
        except:
            msg += f"{symbol} -> Error fetching data\n"
    await update.effective_message.reply_text(msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "/start - Start monitoring stocks\n"
        "/stop - Stop monitoring stocks\n"
        "/add SYMBOL TARGET - Add stock\n"
        "/remove SYMBOL - Remove stock\n"
        "/update SYMBOL TARGET - Update target\n"
        "/list - List monitored stocks\n"
        "/status - Show current prices of monitored stocks\n"
        "/help - Show this message"
    )
    await update.effective_message.reply_text(help_text)

# --- Main ---
async def main():
    await init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("update", update_target))
    app.add_handler(CommandHandler("list", list_stocks))
    app.add_handler(CommandHandler("status", current_status))
    app.add_handler(CommandHandler("help", help_command))

    # app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
