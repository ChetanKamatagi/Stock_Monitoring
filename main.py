import os
print("DEBUG TOKEN:", os.getenv("TELEGRAM_BOT_TOKEN"))
TELEGRAM_BOT_TOKEN="${{shared.TELEGRAM_BOT_TOKEN}}"

print("Got the Telegram token", TELEGRAM_BOT_TOKEN)