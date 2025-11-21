import os
print("DEBUG TOKEN:", os.getenv("TELEGRAM_BOT_TOKEN"))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

print("Got the Telegram token", TOKEN)