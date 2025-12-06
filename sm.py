import asyncio
import logging
import json
import ccxt.async_support as ccxt
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from datetime import datetime, timezone, timedelta
import platform
import time

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load configuration
def load_config():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        mexc_config = config.get('mexc', {})
        telegram_config = config.get('telegram', {})
        if not mexc_config.get('api_key') or not mexc_config.get('api_secret'):
            raise ValueError("Missing api_key or api_secret in mexc config")
        if not telegram_config.get('token') or not telegram_config.get('chat_id'):
            raise ValueError("Missing token or chat_id in telegram config")
        load_trade_history()
        return config
    except Exception as e:
        logging.error(f"Error loading config: {e}")
        return {'mexc': {'api_key': '', 'api_secret': ''}, 'telegram': {'token': '', 'chat_id': ''}, 'target_symbol': ''}

# Save configuration
def save_config(config):
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

# Load trade history from file
def load_trade_history():
    global trade_history
    try:
        with open('trade_history.json', 'r') as f:
            trade_history = json.load(f)
    except FileNotFoundError:
        trade_history = []

# Save trade history to file
def save_trade_history():
    with open('trade_history.json', 'w') as f:
        json.dump(trade_history, f, indent=4)

config = load_config()
TELEGRAM_TOKEN = config['telegram']['token']
CHAT_ID = config['telegram']['chat_id']
TAKE_PROFIT_PCT = config.get('parameters', {}).get('tp', 200)  # Default to 200%
STOP_LOSS_PCT = config.get('parameters', {}).get('sl', 10)
MARGIN_PCT = config.get('parameters', {}).get('margin', 50)
TRAILING_PCT = 10  # Trailing SL is 10% below highest price
MAX_CONCURRENT_TRADES = 3  # Allow up to 3 concurrent trades

# Initialize MEXC exchange
exchange = ccxt.mexc({
    'apiKey': config['mexc']['api_key'],
    'secret': config['mexc']['api_secret'],
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.set_sandbox_mode(False)

# Initialize Telegram application
application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = application.bot

# Global variables
is_running = False
active_trades = {}  # Dictionary to store multiple trades: {symbol: {'entry_price': float, 'amount': float, 'highest_price': float}}
trade_history = []
session_start_balance = 0.0
valid_symbols = set()  # Available trading pairs
ws_lock = asyncio.Lock()  # Lock for thread-safe symbol processing
target_symbol = config.get('target_symbol', '')  # Target coin to snipe
last_alert_time = {}  # Track last Telegram alert time for each symbol

# Telegram menu functions
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Start Bot", callback_data='start_bot'), InlineKeyboardButton("🛑 Stop Bot", callback_data='stop_bot')],
        [InlineKeyboardButton("💰 Balance", callback_data='balance'), InlineKeyboardButton("📡 Status", callback_data='status')],
        [InlineKeyboardButton("⚙️ Config", callback_data='config'), InlineKeyboardButton("📊 Trades", callback_data='trades')],
        [InlineKeyboardButton("🔧 Settings", callback_data='settings'), InlineKeyboardButton("🎯 Set Target Coin", callback_data='set_target_coin')],
        [InlineKeyboardButton("🆘 Help", callback_data='help')],
    ])

def get_config_menu():
    config = load_config()
    params = config.get("parameters", {})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"TP: {params.get('tp', 200)}%", callback_data='set_tp'), 
         InlineKeyboardButton(f"SL: {params.get('sl', 10)}%", callback_data='set_sl')],
        [InlineKeyboardButton(f"Margin: {params.get('margin', 50)}%", callback_data='set_margin')],
        [InlineKeyboardButton("🔄 Refresh", callback_data='config'), 
         InlineKeyboardButton("⬅️ Back", callback_data='menu')],
    ])

def get_settings_menu():
    config = load_config()
    params = config.get("parameters", {})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"TP: {params.get('tp', 200)}%", callback_data='set_tp'),
         InlineKeyboardButton(f"SL: {params.get('sl', 10)}%", callback_data='set_sl')],
        [InlineKeyboardButton(f"Margin: {params.get('margin', 50)}%", callback_data='set_margin')],
        [InlineKeyboardButton(f"⏱️ Time: {params.get('listing_time', 'Not set')}", callback_data='set_time')],
        [InlineKeyboardButton("⬅️ Back to Config", callback_data='menu')],
    ])

def get_tp_menu():
    buttons = [[InlineKeyboardButton(f"{i}%", callback_data=f'set_tp_{i}') for i in range(1, 6)],
               [InlineKeyboardButton(f"{i}%", callback_data=f'set_tp_{i}') for i in range(6, 11)],
               [InlineKeyboardButton(f"{i}%", callback_data=f'set_tp_{i}') for i in range(11, 16)],
               [InlineKeyboardButton(f"{i}%", callback_data=f'set_tp_{i}') for i in range(16, 21)],
               [InlineKeyboardButton(f"200%", callback_data='set_tp_200')],
               [InlineKeyboardButton("⬅️ Back to Settings", callback_data='settings')]]
    return InlineKeyboardMarkup(buttons)

def get_sl_menu():
    buttons = [[InlineKeyboardButton(f"{i}%", callback_data=f'set_sl_{i}') for i in range(1, 6)],
               [InlineKeyboardButton(f"{i}%", callback_data=f'set_sl_{i}') for i in range(6, 11)],
               [InlineKeyboardButton(f"{i}%", callback_data=f'set_sl_{i}') for i in range(11, 16)],
               [InlineKeyboardButton(f"{i}%", callback_data=f'set_sl_{i}') for i in range(16, 21)],
               [InlineKeyboardButton("⬅️ Back to Settings", callback_data='settings')]]
    return InlineKeyboardMarkup(buttons)

def get_margin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("25%", callback_data='set_margin_25'),
         InlineKeyboardButton("50%", callback_data='set_margin_50'),
         InlineKeyboardButton("75%", callback_data='set_margin_75'),
         InlineKeyboardButton("100%", callback_data='set_margin_100')],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data='settings')],
    ])

def get_time_menu():
    buttons = [
        [InlineKeyboardButton("12:00", callback_data='set_time_12:00'), InlineKeyboardButton("13:00", callback_data='set_time_13:00')],
        [InlineKeyboardButton("14:00", callback_data='set_time_14:00'), InlineKeyboardButton("15:00", callback_data='set_time_15:00')],
        [InlineKeyboardButton("16:00", callback_data='set_time_16:00'), InlineKeyboardButton("17:00", callback_data='set_time_17:00')],
        [InlineKeyboardButton("⬅️ Back to Settings", callback_data='settings')]
    ]
    return InlineKeyboardMarkup(buttons)

def get_coin_selection_keyboard():
    return ReplyKeyboardMarkup([
        ['ZBOT/USDT', 'HYPERX/USDT'],
        ['DOGE2/USDT', 'Clear Target'],
        ['Cancel']
    ], one_time_keyboard=True, resize_keyboard=True)

async def handle_message(update: Update, context):
    if update.message and update.message.chat and str(update.message.chat.id) == CHAT_ID:
        text = update.message.text
        if text == "/menu":
            await update.message.reply_text("Main Menu:", reply_markup=get_main_menu())
        elif text == 'Clear Target':
            await clear_target_coin(update, context)
        elif text == 'Cancel':
            await update.message.reply_text("Cancelled. Use /menu to return.", reply_markup=ReplyKeyboardRemove())
        elif text.endswith('/USDT'):
            await set_target_coin(text, update, context)
        elif text not in ["/start", "/stop", "/balance", "/status", "/showconfig", "/set", "/clear", "/help"]:
            await update.message.reply_text("Unknown command or invalid coin! Use the menu below:", reply_markup=get_main_menu())
    else:
        logging.warning(f"Unauthorized access attempt from chat ID: {update.message.chat.id if update.message and update.message.chat else 'Unknown'}")
        if update.message:
            await update.message.reply_text("Unauthorized access. Please check your chat ID.")

from random import randint

async def handle_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    logging.info(f"Button pressed: {data}")

    if data == 'start_bot':
        await start_bot(update, context)
    elif data == 'stop_bot':
        await stop_bot(update, context)
    elif data == 'balance':
        await send_balance(update, context)
    elif data == 'status':
        await send_status(update, context)
    elif data == 'config':
        new_text = "Configuration Menu:"
        new_markup = get_config_menu()
        await query.edit_message_text(f"{new_text}\n\n🆔 {randint(1000, 9999)}", reply_markup=new_markup)
    elif data == 'settings':
        new_text = "Settings Menu:"
        new_markup = get_settings_menu()
        await query.edit_message_text(f"{new_text}\n\n🆔 {randint(1000, 9999)}", reply_markup=new_markup)
    elif data == 'trades':
        await send_trades(update, context)
    elif data == 'help':
        await send_help(update, context)
    elif data == 'set_target_coin':
        await query.message.reply_text("Select a coin to snipe or type /set coin <symbol>:", reply_markup=get_coin_selection_keyboard())
    elif data.startswith('set_'):
        param = data.replace('set_', '')
        config = load_config()
        params = config.get("parameters", {})

        if param == 'tp':
            await query.edit_message_text(f"Select Take-Profit %:\n\n🆔 {randint(1000,9999)}", reply_markup=get_tp_menu())
        elif param == 'sl':
            await query.edit_message_text(f"Select Stop-Loss %:\n\n🆔 {randint(1000,9999)}", reply_markup=get_sl_menu())
        elif param == 'margin':
            await query.edit_message_text(f"Select Margin %:\n\n🆔 {randint(1000,9999)}", reply_markup=get_margin_menu())
        elif param == 'time':
            await query.edit_message_text(f"Select Listing Time:\n\n🆔 {randint(1000,9999)}", reply_markup=get_time_menu())
        elif param.startswith('tp_'):
            tp_value = int(param.split('_')[1])
            global TAKE_PROFIT_PCT
            TAKE_PROFIT_PCT = tp_value
            params['tp'] = tp_value
            config['parameters'] = params
            save_config(config)
            await query.edit_message_text(f"Take-Profit set to {tp_value}%\n\n🆔 {randint(1000,9999)}", reply_markup=get_settings_menu())
        elif param.startswith('sl_'):
            sl_value = int(param.split('_')[1])
            global STOP_LOSS_PCT
            STOP_LOSS_PCT = sl_value
            params['sl'] = sl_value
            config['parameters'] = params
            save_config(config)
            await query.edit_message_text(f"Stop-Loss set to {sl_value}%\n\n🆔 {randint(1000,9999)}", reply_markup=get_settings_menu())
        elif param.startswith('margin_'):
            margin_value = int(param.split('_')[1])
            global MARGIN_PCT
            MARGIN_PCT = margin_value
            params['margin'] = margin_value
            config['parameters'] = params
            save_config(config)
            await query.edit_message_text(f"Margin set to {margin_value}%\n\n🆔 {randint(1000,9999)}", reply_markup=get_settings_menu())
        elif param.startswith('time_'):
            time_value = param.split('_')[1]
            try:
                datetime.strptime(time_value, "%H:%M")
                params['listing_time'] = time_value
                config['parameters'] = params
                save_config(config)
                await query.edit_message_text(f"⏱️ Listing time set to {time_value}\n\n🆔 {randint(1000,9999)}", reply_markup=get_settings_menu())
                logging.info(f"Parameter time set to {time_value} and saved to config")
            except ValueError:
                await query.edit_message_text("Invalid time format! Use HH:MM like 13:00\n\n🆔 {randint(1000,9999)}", reply_markup=get_settings_menu())
        else:
            instruction = f"Use /set {param} <value> to change this parameter."
            await query.edit_message_text(instruction + f"\n\n🆔 {randint(1000,9999)}", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data='config')],
                [InlineKeyboardButton("⬅️ Back", callback_data='menu')]
            ]))
    elif data == 'menu':
        new_text = "Main Menu:"
        new_markup = get_main_menu()
        await query.edit_message_text(f"{new_text}\n\n🆔 {randint(1000,9999)}", reply_markup=new_markup)

async def set_target_coin(symbol, update, context):
    global target_symbol
    if not symbol.endswith('/USDT'):
        await update.message.reply_text("Invalid symbol! Must end with /USDT (e.g., ZBOT/USDT).", reply_markup=ReplyKeyboardRemove())
        return
    try:
        markets = await exchange.load_markets()
        if symbol not in markets:
            await update.message.reply_text(
                f"Symbol {symbol} not found on MEXC. Try another coin or check listing status.\nUse /clear to reset target.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        config = load_config()
        config['target_symbol'] = symbol
        save_config(config)
        target_symbol = symbol
        message = f"""
✅ Watching: {symbol}
🔍 Waiting for pair to go live on MEXC...
🎯 Auto-sniping will execute the moment price becomes available!
        """
        await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
        logging.info(f"Target coin set to {symbol}")
    except Exception as e:
        logging.error(f"Error validating symbol {symbol}: {e}")
        await update.message.reply_text(
            f"Error checking {symbol} on MEXC: {e}\nUse /clear to reset target.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

async def clear_target_coin(update, context):
    global target_symbol
    config = load_config()
    config['target_symbol'] = ''
    save_config(config)
    target_symbol = ''
    await update.message.reply_text("🟥 Target coin cleared. Bot will monitor all new listings.", reply_markup=ReplyKeyboardRemove())
    logging.info("Target coin cleared")

async def sync_time():
    for attempt in range(3):
        try:
            server_time = await exchange.fetch_time()
            local_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            offset = server_time - local_time + 100  # Add 100ms buffer for latency
            exchange.nonce = lambda: int(datetime.now(timezone.utc).timestamp() * 1000) + offset
            logging.info(f"Time synchronized with MEXC server. Offset: {offset}ms")
            return
        except Exception as e:
            logging.error(f"Error syncing time with MEXC (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(1)
    logging.error("Failed to sync time with MEXC after 3 attempts")
    await send_signal("⚠️ Failed to sync time with MEXC server. Check system clock or MEXC API status.")

async def start_bot(update: Update, context):
    global is_running, session_start_balance
    if not is_running:
        is_running = True
        await sync_time()
        usdt_balance = await get_balance('USDT')
        session_start_balance = usdt_balance
        start_message = f"""
✅ SNIPER BOT ACTIVATED ✅

💰 Account Overview:
   ├─ Starting Balance: {usdt_balance:.2f} USDT
   ├─ Margin: {MARGIN_PCT}%
   └─ Risk Level: Moderate

⚙️ Settings:
   ├─ Take-Profit: {TAKE_PROFIT_PCT}% (Trailing SL: {TRAILING_PCT}%)
   ├─ Stop-Loss: {STOP_LOSS_PCT}% (Initial)
   └─ Listing Time: {config.get('parameters', {}).get('listing_time', 'Not set')}

🎯 Target Coin: {target_symbol if target_symbol else 'All new listings'}

📅 Date: {datetime.now().strftime("%Y-%m-%d")}
🕒 Time: {get_current_ist_time()} IST | {get_current_utc_time()} UTC
        """
        if update.callback_query:
            query = update.callback_query
            await query.edit_message_text(start_message, reply_markup=get_main_menu())
        else:
            await update.message.reply_text(start_message, reply_markup=get_main_menu())
        await send_signal(start_message)
        logging.info("Bot started.")
        asyncio.create_task(scheduled_sniper())  # Start scheduled sniper
    else:
        message = "Bot is already running!"
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=get_main_menu())
        else:
            await update.message.reply_text(message, reply_markup=get_main_menu())

async def stop_bot(update: Update, context):
    global is_running, active_trades, target_symbol
    if is_running:
        start_balance = session_start_balance
        if active_trades:
            await sync_time()
            for symbol in list(active_trades.keys()):
                try:
                    balance = await exchange.fetch_balance()
                    base_currency = symbol.split('/')[0]
                    amount = balance['free'].get(base_currency, 0.0)
                    if amount > 0:
                        order = await place_market_sell_order(symbol, amount)
                        if order and order['status'] == 'closed':
                            logging.info(f"Closed position for {symbol}: {amount} units")
                            await send_signal(f"🔔 Closed position for {symbol}: {amount} units on bot stop")
                        else:
                            logging.error(f"Failed to close position for {symbol}")
                    del active_trades[symbol]
                except Exception as e:
                    logging.error(f"Error closing position for {symbol}: {e}")
        usdt_balance = await get_balance('USDT')
        net_pl_usdt = usdt_balance - start_balance
        net_pl_pct = (net_pl_usdt / start_balance) * 100 if start_balance > 0 else -100.00
        stop_message = f"""
🚫 BOT DEACTIVATED 🚫  
📊 Session Report:  
   ├─ Start Balance: {start_balance:.2f} USDT  
   ├─ End Balance: {usdt_balance:.2f} USDT  
   ├─ Net P/L: {net_pl_pct:.2f}% ({net_pl_usdt:.2f} USDT)  
   └─ Trades: {len(trade_history)}  
📅 Date: {datetime.now().strftime("%Y-%m-%d")}  
🕒 Time: {get_current_ist_time()} IST | {get_current_utc_time()} UTC  
📋 Summary: Session ended
        """
        await reset_global_states()
        config = load_config()
        config['target_symbol'] = ''
        save_config(config)
        target_symbol = ''
        if update.callback_query:
            query = update.callback_query
            await query.edit_message_text(stop_message, reply_markup=get_main_menu())
        else:
            await update.message.reply_text(stop_message, reply_markup=get_main_menu())
        await send_signal(stop_message)
        logging.info("Bot stopped.")
    else:
        message = "Bot is already stopped!"
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=get_main_menu())
        else:
            await update.message.reply_text(message, reply_markup=get_main_menu())

async def send_balance(update: Update, context):
    try:
        await sync_time()
        balance = await exchange.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0.0)
        active_coins = ""
        for symbol in active_trades:
            base_currency = symbol.split('/')[0]
            coin_balance = balance['total'].get(base_currency, 0.0)
            active_coins += f"   ├─ {base_currency}: {coin_balance:.4f}\n"
        message = f"""
💰 ACCOUNT BALANCE 💰

📈 Current Balance:
   ├─ USDT: {usdt_balance:.2f}
{active_coins if active_coins else '   ├─ Active Coin: None'}
   └─ Total Trades: {len(trade_history)}

⚙️ Settings:
   ├─ Take-Profit: {TAKE_PROFIT_PCT}% (Trailing SL: {TRAILING_PCT}%)
   ├─ Stop-Loss: {STOP_LOSS_PCT}% (Initial)
   ├─ Margin: {MARGIN_PCT}%
   └─ Listing Time: {config.get('parameters', {}).get('listing_time', 'Not set')}

📊 Active Trades: {', '.join(active_trades.keys()) if active_trades else 'None'}

🎯 Target Coin: {target_symbol if target_symbol else 'All new listings'}

📅 Date: {datetime.now().strftime("%Y-%m-%d")}
🕒 Time: {get_current_ist_time()} IST | {get_current_utc_time()} UTC
"""
        if update.callback_query:
            query = update.callback_query
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data='menu')]])
            if query.message.text != message or str(query.message.reply_markup) != str(back_markup):
                await query.edit_message_text(message, reply_markup=back_markup)
        else:
            await update.message.reply_text(message, reply_markup=get_main_menu())
    except Exception as e:
        logging.error(f"Error fetching balance: {e}")
        message = "Sorry, I couldn't fetch your balance. Please check your API credentials."
        if update.callback_query:
            query = update.callback_query
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data='menu')]])
            if query.message.text != message or str(query.message.reply_markup) != str(back_markup):
                await query.edit_message_text(message, reply_markup=back_markup)
        else:
            await update.message.reply_text(message, reply_markup=get_main_menu())

async def send_status(update: Update, context):
    status_message = f"""
📡 BOT STATUS UPDATE 📡

{'✅ Running' if is_running else '❌ Stopped'}
📊 Active Trades: {', '.join(active_trades.keys()) if active_trades else 'None'}
⚙️ Take-Profit: {TAKE_PROFIT_PCT}% (Trailing SL: {TRAILING_PCT}%)
⚙️ Stop-Loss: {STOP_LOSS_PCT}% (Initial)
⚙️ Margin: {MARGIN_PCT}%
⚙️ Listing Time: {config.get('parameters', {}).get('listing_time', 'Not set')}
🎯 Target Coin: {target_symbol if target_symbol else 'None'}
📅 Date: {datetime.now().strftime("%Y-%m-%d")}
🕒 Time: {get_current_ist_time()} IST | {get_current_utc_time()} UTC
"""
    if update.callback_query:
        query = update.callback_query
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data='menu')]])
        try:
            current_text = query.message.text or ""
            current_markup = query.message.reply_markup
            markup_changed = (
                current_markup is None or
                current_markup.to_dict() != back_markup.to_dict()
            )
            if current_text.strip() != status_message.strip() or markup_changed:
                await query.edit_message_text(status_message, reply_markup=back_markup)
        except telegram.error.BadRequest as e:
            if "Message is not modified" in str(e):
                logging.info("Skipped editing status message: content unchanged")
            else:
                logging.error(f"Failed to edit status message: {e}")
    else:
        await update.message.reply_text(status_message, reply_markup=get_main_menu())

async def send_trades(update: Update, context):
    total_trades = len(trade_history)
    winning_trades = sum(1 for trade in trade_history if trade['pl_pct'] > 0)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    avg_win = sum(trade['pl_pct'] for trade in trade_history if trade['pl_pct'] > 0) / winning_trades if winning_trades > 0 else 0
    avg_loss = sum(trade['pl_pct'] for trade in trade_history if trade['pl_pct'] < 0) / (total_trades - winning_trades) if total_trades - winning_trades > 0 else 0
    max_drawdown = min([0] + [trade['pl_pct'] for trade in trade_history]) if trade_history else 0
    start_balance = session_start_balance

    message = f"""
📊 Trade Statistics:

Total Trades: {total_trades}
Winning Trades: {winning_trades}
Win Rate: {win_rate:.1f}%
Avg Win: {avg_win:.2f}%
Avg Loss: {avg_loss:.2f}%
Max Drawdown: {max_drawdown:.2f}%

Current Session:
Start Balance: {start_balance:.2f} USDT
"""
    if update.callback_query:
        query = update.callback_query
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data='menu')]])
        if query.message.text != message or str(query.message.reply_markup) != str(back_markup):
            await query.edit_message_text(message, reply_markup=back_markup)
        else:
            await update.message.reply_text(message, reply_markup=get_main_menu())

async def send_help(update: Update, context):
    help_message = """
Basic Commands:
    /start - Start the sniper bot
    /stop - Stop the bot and close any open trades
    /balance - Show USDT and active coin balances
    /status - Show bot status and active trades
    /menu - Display the main menu
    /set <parameter> <value> - Change configuration values (e.g., /set coin ZBOT/USDT, /set time 13:00)
    /clear - Clear the target coin and monitor all new listings

Strategy:
    📈 Sniper Bot: Buys coins newly listed on MEXC (after bot starts) or a specific coin set via /set coin. Monitors every 100ms, buys when live, uses trailing stop-loss (10% below highest price) or initial stop-loss at SL%. Trades each coin only once, no re-entry after TP or SL. Supports up to 3 concurrent trades.
    ⏱️ Scheduled Sniper: If listing_time is set (e.g., /set time 13:00), bot waits until exact time and snipes target coin instantly without ticker checks.

Configuration Parameters:
    🎯 coin - Set target coin to snipe (e.g., ZBOT/USDT)
    🎯 tp - Take-profit % (default: 200, for display; trailing SL used)
    🛑 sl - Initial stop-loss % (default: 10)
    💰 margin - % of balance to use for trades (25, 50, 75, 100, default: 50)
    ⏱️ time - Set listing time for scheduled sniping (e.g., 13:00)

Buttons:
    ✅ Start Bot - Activates the bot and shows starting balance
    🛑 Stop Bot - Closes all open trades and stops the bot, showing final balance and P/L
    💰 Balance - Shows USDT and active coin balances
    📡 Status - Shows bot status, active trades, TP, SL, margin, and target coin
    ⚙️ Config - Shows current TP, SL, margin, and active trades
    🔧 Settings - Allows changing TP (1-20%, 200%), SL (1-20%), Margin (25, 50, 75, 100%), Time (HH:MM)
    🎯 Set Target Coin - Select a specific coin to snipe (e.g., ZBOT/USDT)
    🆘 Help - Displays this message
"""
    back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='menu')]])
    
    if update.callback_query:
        query = update.callback_query
        if query.message.text != help_message or str(query.message.reply_markup) != str(back_markup):
            await query.edit_message_text(help_message, reply_markup=back_markup)
    else:
        await update.message.reply_text(help_message, reply_markup=back_markup)

async def set_parameter(update: Update, context):
    global TAKE_PROFIT_PCT, STOP_LOSS_PCT, MARGIN_PCT, target_symbol
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /set <parameter> <value>\nValid parameters: coin, tp, sl, margin, time")
        return
    
    param, value = context.args[0].lower(), context.args[1]
    valid_params = ['coin', 'tp', 'sl', 'margin', 'time']
    
    if param not in valid_params:
        await update.message.reply_text(f"Parameter {param} not found. Use: {', '.join(valid_params)}")
        return
    
    config = load_config()
    params = config.get("parameters", {})
    
    try:
        if param == 'coin':
            await sync_time()
            await set_target_coin(value, update, context)
        elif param == 'tp':
            tp_value = float(value)
            if tp_value > 0:
                TAKE_PROFIT_PCT = tp_value
                params['tp'] = tp_value
                config['parameters'] = params
                save_config(config)
                await update.message.reply_text(f"Take-Profit set to {tp_value}%")
                logging.info(f"Parameter tp set to {tp_value} and saved to config")
            else:
                await update.message.reply_text("Take-Profit must be greater than 0")
                return
        elif param == 'sl':
            sl_value = float(value)
            if 1 <= sl_value <= 20:
                STOP_LOSS_PCT = sl_value
                params['sl'] = sl_value
                config['parameters'] = params
                save_config(config)
                await update.message.reply_text(f"Stop-Loss set to {sl_value}%")
                logging.info(f"Parameter sl set to {sl_value} and saved to config")
            else:
                await update.message.reply_text("Stop-Loss must be between 1 and 20")
                return
        elif param == 'margin':
            margin_value = int(value)
            if margin_value in [25, 50, 75, 100]:
                MARGIN_PCT = margin_value
                params['margin'] = margin_value
                config['parameters'] = params
                save_config(config)
                await update.message.reply_text(f"Margin set to {margin_value}%")
                logging.info(f"Parameter margin set to {margin_value} and saved to config")
            else:
                await update.message.reply_text("Margin must be 25, 50, 75, or 100")
                return
        elif param == 'time':
            try:
                datetime.strptime(value, "%H:%M")
                params['listing_time'] = value
                config['parameters'] = params
                save_config(config)
                await update.message.reply_text(f"⏱️ Listing time set to {value}")
                logging.info(f"Parameter time set to {value} and saved to config")
            except ValueError:
                await update.message.reply_text("Invalid time format! Use HH:MM like 13:00")
    except ValueError:
        await update.message.reply_text("Invalid value. Use appropriate format for each parameter.")
    except Exception as e:
        logging.error(f"Error setting parameter {param}: {e}")
        await update.message.reply_text(f"Error setting {param}: {e}. Please try again or check API status.")

async def clear_target_command(update: Update, context):
    await clear_target_coin(update, context)

async def reset_global_states():
    global is_running, active_trades
    is_running = False
    active_trades = {}
    logging.info("Global states have been reset.")

async def send_signal(message, retries=3, delay=5):
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message)
            logging.info(f"Signal sent: {message}")
            return
        except Exception as e:
            logging.error(f"Error sending signal on attempt {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
    logging.error(f"Failed to send signal after {retries} attempts: {message}")

def get_current_utc_time():
    return datetime.now(timezone.utc).strftime("%H:%M")

def get_current_ist_time():
    ist_timezone = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_timezone).strftime("%H:%M")

async def wait_until_target_time(target_time_str, buffer_seconds=2):
    now = datetime.now()
    target_time = datetime.strptime(target_time_str, "%H:%M").replace(
        year=now.year, month=now.month, day=now.day
    )
    # Wait until (target time - buffer)
    wait_seconds = (target_time - now).total_seconds() - buffer_seconds
    if wait_seconds > 0:
        logging.info(f"⏳ Waiting {wait_seconds:.2f}s until target time - {buffer_seconds}s buffer")
        await asyncio.sleep(wait_seconds)

async def place_market_buy_order(symbol, amount):
    try:
        await sync_time()
        order = await exchange.create_market_buy_order(symbol, amount)
        logging.info(f"Market buy order placed: {order}")
        return order
    except Exception as e:
        logging.error(f"Error placing market buy order for {symbol}: {e}")
        return None

async def place_market_sell_order(symbol, amount):
    try:
        await sync_time()
        order = await exchange.create_market_sell_order(symbol, amount)
        logging.info(f"Market sell order placed: {order}")
        return order
    except Exception as e:
        logging.error(f"Error placing market sell order for {symbol}: {e}")
        return None

async def get_balance(symbol, retries=3, delay=5):
    for attempt in range(retries):
        try:
            await sync_time()
            balance = await exchange.fetch_balance()
            return balance['total'].get(symbol, 0.0)
        except Exception as e:
            logging.error(f"Error fetching balance for {symbol} (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
            else:
                if attempt == retries - 1:
                    await send_signal(f"⚠️ Failed to fetch {symbol} balance after {retries} attempts. Check API credentials or MEXC server.")
                return 0.0

async def process_trade(symbol, entry_price, amount):
    global active_trades, trade_history, target_symbol, is_running
    base_currency = symbol.split('/')[0]
    trade_start_time = datetime.now(timezone.utc)

    # 🟡 Safety Check: Make sure trade exists
    if symbol not in active_trades:
        logging.warning(f"❌ No active trade found for {symbol}")
        return

    trade = active_trades[symbol]
    trade['highest_price'] = entry_price
    trade['max_profit'] = 0.0  # max profit % reached

    while symbol in active_trades:
        try:
            ticker = await exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            balance = await exchange.fetch_balance()
            current_amount = balance['free'].get(base_currency, 0.0)

            if current_amount <= 0:
                logging.info(f"No holdings for {base_currency}, closing trade")
                if symbol in active_trades:
                    del active_trades[symbol]
                return

            # 💹 Update highest price seen
            trade['highest_price'] = max(trade['highest_price'], current_price)

            # 🔢 Calculate % gain/loss
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            trade['max_profit'] = max(trade['max_profit'], profit_pct)

            # 🛡 Initial Stop Loss
            initial_sl_price = entry_price * (1 - STOP_LOSS_PCT / 100)

            # 🔐 Dynamic Trailing SL Logic
            trigger_pct = trade['max_profit'] - TRAILING_PCT
            reason = None

            # 🛑 SL Conditions
            if current_price <= initial_sl_price:
                reason = "Initial Stop-Loss"
            elif profit_pct <= trigger_pct:
                reason = f"TSL Hit (Peak: {trade['max_profit']:.1f}%, Now: {profit_pct:.1f}%)"

            if reason:
                order = await place_market_sell_order(symbol, current_amount)
                if order:
                    usdt_balance = await get_balance('USDT')
                    profit_loss_pct = ((current_price - entry_price) / entry_price) * 100
                    profit_loss_usdt = (current_price - entry_price) * current_amount
                    duration = (datetime.now(timezone.utc) - trade_start_time).total_seconds() / 60

                    # 📝 Save Trade
                    trade_history.append({
                        "symbol": symbol,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "pl_pct": round(profit_loss_pct, 2),
                        "pl_usdt": round(profit_loss_usdt, 2),
                        "reason": reason,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

                    if len(trade_history) > 10:
                        trade_history.pop(0)
                    save_trade_history()

                    # 📢 Telegram Update
                    await send_signal(f"""
🚨 TRADE CLOSED 🚨  
📈 Symbol: {symbol}  
📉 Reason: {reason}  
🟢 Entry: {entry_price:.5f}  
🔴 Exit: {current_price:.5f}  
📊 P/L: {profit_loss_pct:.2f}% ({profit_loss_usdt:.2f} USDT)  
💰 Balance: {usdt_balance:.2f} USDT  
⏱ Duration: {duration:.2f} minutes
""")
                    if symbol in active_trades:
                        del active_trades[symbol]
                    if not active_trades:
                        is_running = False
                        await send_signal("🛑 Bot stopped: All trades closed (SL/TP hit).")
                else:
                    logging.error(f"❌ Failed to close {symbol}")
                    if symbol in active_trades:
                        del active_trades[symbol]
                return
            await asyncio.sleep(0.1)

        except Exception as e:
            logging.error(f"Error processing trade for {symbol}: {e}")
            await asyncio.sleep(1)


async def scheduled_sniper():
    global target_symbol, is_running, active_trades

    config = load_config()
    params = config.get("parameters", {})
    listing_time = params.get("listing_time", "")
    symbol = config.get("target_symbol", "")
    fallback_price = params.get("estimated_price", 0.01)
    instant_entry = params.get("instant_entry", False)
    max_jump_pct = params.get("max_jump_pct", 20) / 100

    if not symbol or not listing_time:
        logging.warning("Scheduled sniper skipped: target coin or time not set")
        return

    # Wait till listing time exactly
    await wait_until_target_time(listing_time, buffer_seconds=0)
    logging.info(f"⏱️ Time reached! Starting sniper for {symbol}")

    if not is_running:
        logging.warning("Bot stopped before listing time. Skipping trade.")
        return

    try:
        balance = await get_balance("USDT")
        margin = balance * (MARGIN_PCT / 100)

        if margin < 1.01:
            await send_signal(f"⚠️ Margin {margin:.2f} too low for MEXC minimum (1 USDT)")
            return

        markets = await exchange.load_markets()
        market = markets[symbol]
        precision = int(market['precision']['amount'])

        # ✅ INSTANT ENTRY MODE with smart price
        if instant_entry:
            logging.info("⚡ INSTANT ENTRY ENABLED: Smart fallback logic")
            attempt = 0
            while is_running:
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    live_price = ticker['last'] or fallback_price
                    price_to_use = max(live_price, fallback_price)

                    # 🔁 Smart amount calculation
                    amount = round(margin / price_to_use, precision)
                    est_cost = amount * price_to_use

                    # ✅ Ensure min 1 USDT trade
                    if est_cost < 1.01:
                        logging.warning(f"⚠️ Cost {est_cost:.4f} below 1 USDT. Adjusting amount.")
                        amount = round(1.01 / price_to_use, precision)

                    logging.info(f"🚀 Attempt {attempt+1}: Buying {symbol} at {price_to_use:.6f}, amount: {amount}")
                    await send_signal(f"🚀 Attempt {attempt+1}: Market Buy {symbol} @ ~{price_to_use:.6f}")

                    order = await place_market_buy_order(symbol, amount)

                    trades = await exchange.fetch_my_trades(symbol)
                    total_filled = sum(
                        t['amount'] for t in trades
                        if abs(t['timestamp'] - order['timestamp']) < 5000
                    )

                    if total_filled > 0:
                        entry_price = trades[-1]['price'] if trades else price_to_use
                        active_trades[symbol] = {
                            'entry_price': entry_price,
                            'amount': total_filled,
                            'highest_price': entry_price,
                            'max_profit': 0.0
                        }
                        await send_signal(f"✅ Instant Trade Placed: {symbol} @ ~{entry_price:.6f}")
                        asyncio.create_task(process_trade(symbol, entry_price, total_filled))
                        return
                    else:
                        logging.warning("❌ Order not filled, retrying...")

                except Exception as e:
                    logging.error(f"Fill check error: {e}")

                attempt += 1
                await asyncio.sleep(0.025)
            return  # Exit after retry block

        # 🔽 Normal price-detect mode
        first_price = None
        while is_running:
            try:
                ticker = await exchange.fetch_ticker(symbol)
                if ticker and ticker.get("last"):
                    price = ticker["last"]

                    if not first_price:
                        first_price = price
                        logging.info(f"🎯 First price detected: {first_price:.6f}")

                    if price > first_price * (1 + max_jump_pct):
                        await send_signal(f"⚠️ {symbol} jumped >{max_jump_pct*100:.0f}%, retrying...")
                        await asyncio.sleep(0.01)
                        continue

                    amount = round(margin / price, precision)
                    logging.info(f"🚀 Trying to snipe {symbol} at {price:.6f}")
                    await send_signal(f"🚀 Trying to snipe {symbol} at {price:.6f}")

                    # ✅ Market order place
                    order = await place_market_buy_order(symbol, amount)

                    # ✅ Order fill check
                    trades = await exchange.fetch_my_trades(symbol)
                    total_filled = sum(
                        t['amount'] for t in trades
                        if abs(t['timestamp'] - order['timestamp']) < 5000
                    )

                    if total_filled > 0:
                        logging.info(f"✅ Order filled! Filled amount: {total_filled}")
                        active_trades[symbol] = {
                            'entry_price': price,
                            'amount': total_filled,
                            'highest_price': price
                        }
                        await send_signal(f"✅ Trade placed for {symbol} at {price:.6f}")
                        asyncio.create_task(process_trade(symbol, price, total_filled))
                        return
                    else:
                        logging.warning("❌ Order not filled, retrying...")

            except Exception as e:
                logging.error(f"Sniper error during trade attempt: {e}")

            await asyncio.sleep(0.009)

    except Exception as e:
        logging.error(f"Sniper error: {e}")
        await send_signal(f"❌ Sniper error: {e}")



async def start():
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        application.add_handler(CommandHandler("start", start_bot))
        application.add_handler(CommandHandler("menu", lambda update, context: update.message.reply_text("Main Menu:", reply_markup=get_main_menu())))
        application.add_handler(CommandHandler("stop", stop_bot))
        application.add_handler(CommandHandler("balance", send_balance))
        application.add_handler(CommandHandler("status", send_status))
        application.add_handler(CommandHandler("set", set_parameter))
        application.add_handler(CommandHandler("clear", clear_target_command))
        application.add_handler(CommandHandler("help", send_help))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        await asyncio.Event().wait()
    except Exception as e:
        logging.error(f"Unexpected error in bot loop: {e}")
    finally:
        await exchange.close()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logging.info("Bot resources cleaned up.")

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(start())
    except Exception as e:
        logging.error(f"Error starting main loop: {e}")