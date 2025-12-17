# Stock Monitoring Telegram Bot

This is a Python-based Telegram bot that actively monitors specified stock prices and sends you an alert when a stock reaches its target price. It uses `yfinance` to fetch real-time stock data and `python-telegram-bot` to interact with the Telegram API.

The bot is configured to operate only during the National Stock Exchange of India (NSE) market hours (9:17 AM to 5:30 PM, Monday to Friday, IST).

## Features

- **Real-time Price Monitoring**: Checks stock prices at regular intervals.
- **Target Price Alerts**: Sends a Telegram message when a stock's price crosses the user-defined target.
- **Persistent Watchlist**: Your list of monitored stocks is saved in `stocks.json` and reloaded on restart.
- **Market Hours Awareness**: Automatically pauses monitoring when the market is closed.
- **Interactive Commands**: Easily manage your watchlist directly from Telegram.
- **Stock Validation**: Checks if a stock symbol is valid before adding it to the watchlist.

## Getting Started

Follow these instructions to get your own instance of the bot running.

### Prerequisites

- Python 3.x
- A Telegram Bot Token. You can get one by talking to the [BotFather](https://t.me/BotFather) on Telegram.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/chetankamatagi/stock_monitoring.git
    cd stock_monitoring
    ```

2.  **Install the required packages:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure the Bot Token:**
    Open the `main.py` file and replace the placeholder value for `TOKEN` with your own Telegram bot token:
    ```python
    # --- Config ---
    TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN_HERE' 
    ```

## Usage

### Running the Bot

Once you have configured your bot token, run the main script:

```bash
python main.py
```

The bot will start polling for messages. You can now interact with it on Telegram.

### Available Commands

Here are the commands you can use to interact with the bot:

-   **/start**: Starts the monitoring process for the stocks in your watchlist.
-   **/stop**: Stops the monitoring process.
-   **/add `SYMBOL` `TARGET`**: Adds a stock to your watchlist with a target price.
    -   *Example*: `/add RELIANCE.NS 3000`
-   **/remove `SYMBOL`**: Removes a stock from your watchlist.
    -   *Example*: `/remove RELIANCE.NS`
-   **/update `SYMBOL` `NEW_TARGET`**: Updates the target price for an existing stock in your watchlist.
    -   *Example*: `/update RELIANCE.NS 3100`
-   **/list**: Shows all the stocks and their target prices currently in your watchlist.
-   **/status**: Displays the current market price for each stock in your watchlist alongside its target.
-   **/help**: Shows a help message with all available commands.
