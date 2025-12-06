# MEXC Scheduled Sniper Bot

A fully automated, Telegram-controlled sniper system engineered for ultra-fast execution of MEXC token listings. This bot is designed for traders who require precision timing, responsive controls, remote access, and complete visibility into bot operations.

Table of Contents

Introduction

Features

System Architecture

Telegram User Interface

Screenshots

Detailed Functional Explanation

Configuration (config.json)

Installation

Usage

Trade Engine Logic

Risk Management Model

Data Persistence

Project Structure

Limitations & Recommendations

Disclaimer

## 1. Introduction

This project provides a Python-based sniper bot that integrates directly with the MEXC exchange. It supports two primary modes of operation:

Scheduled Sniping – executes at an exact time (HH:MM) without waiting for market feed.

Live Sniping – monitors new listings in real-time and executes immediately when data becomes live.

A complete Telegram interface is included, enabling remote control, parameter changes, real-time balance viewing, and immediate feedback during trading sessions.

This bot is intended for users who want automation without sacrificing configurability and control.

## 2. Features
Core Sniping Capabilities

Scheduled timestamp execution to match official listing announcements.

Real-time detection of new MEXC trading pairs (via CCXT).

Instant fallback-price buy logic when ticker feed is unavailable at launch.

Precision entry using synchronized exchange time.

Risk Control & Trade Automation

Configurable take-profit (TP).

Configurable stop-loss (SL).

Dynamic trailing stop-loss triggered by highest price reached.

Automated sell execution on TP or SL breach.

Per-trade performance logging.

Automatic session summary when bot stops.

Telegram-Based Controls

Start/stop the bot remotely.

Modify TP, SL, margin, time, target symbol.

View real-time balance across USDT and active coins.

View active trades at any moment.

Retrieve stored trade history.

Menu-driven interaction with inline keyboards.

Notification alerts on every trade event.

Technical Enhancements

Asynchronous engine for low-latency execution.

Exchange time auto-sync logic with offset correction.

Automatic fail-safe if API issues occur.

Trade storage in JSON for long-term record keeping.

Supports up to 3 concurrent trades.

## 3. System Architecture

The bot consists of several coordinated layers:

3.1 Telegram Interface Layer

Handles:

User commands

Menu buttons

Dynamic responses

Validation of input parameters

Real-time reporting

3.2 Execution Core (sniper engine)

Responsible for:

Monitoring time

Market monitoring (for live sniping)

Creating market buy orders

Monitoring active positions

Evaluating stop-loss & trailing stop conditions

Executing market sell orders

3.3 Persistence Layer

Includes:

config.json (settings, API keys, parameters)

trade_history.json (per-trade logs, timestamps, P/L details)

3.4 Exchange Communication Layer

Uses CCXT to:

Fetch tickers

Pull balances

Execute market buy and sell orders

Check server time

This architecture ensures separation of concerns and robustness.

## 4. Telegram User Interface

The Telegram bot is designed for operational simplicity while offering complete depth of control.
Key UI components include:

Main menu with actionable options

Settings menu with adjustable TP, SL, Margin, Time

Target coin selection

Callback query handlers for seamless button navigation

Context-based responses

Real-time display of current parameters and active trades

This makes the bot usable entirely from a mobile device without needing a terminal.

## 5. Screenshots
### Main Menu

Shows the full dashboard including Start Bot, Stop Bot, Balance, Status, Config, Trades, Settings, Target Coin, Help.


<img width="1221" height="966" alt="Image" src="https://github.com/user-attachments/assets/8f8c3c49-e948-44a2-991f-455086b8b925" />

### Coin Selection & Watching Confirmation

The bot begins monitoring the selected trading pair for live market activation.

 
<img width="1237" height="963" alt="Image" src="https://github.com/user-attachments/assets/f3949832-02d4-4087-907d-8ceca439acc8" />

### Sniper Bot Activation Summary

Displays session start balance, margin, TP/SL settings, selected target coin, and synchronized timestamps.


<img width="1241" height="956" alt="Image" src="https://github.com/user-attachments/assets/2487f237-196b-4b87-9c2d-57a3f7eff773" />


<img width="1242" height="979" alt="Image" src="https://github.com/user-attachments/assets/aa81fd83-3c65-4478-ab72-fe608285dddc" />

## 6. Detailed Functional Explanation
6.1 Target Selection

User sets coin through Telegram (/set coin SYMBOL).

Bot validates symbol availability on MEXC.

Bot begins monitoring symbol immediately or prepares for scheduled mode.

6.2 Scheduled Sniping

Bot waits until exact HH:MM time.

Time sync offset is applied for accuracy.

Buy order is placed at the first moment allowed.

6.3 Live Feed Sniping

Monitors ticker updates.

Detects first valid price entry.

Executes buy with correct precision and margin allocation.

6.4 Trade Monitoring Loop

Once a trade is open:

Continuously fetches current price.

Updates highest price during run.

Evaluates trailing stop condition.

Evaluates initial stop-loss.

Executes sell when conditions met.

Logs the trade into history.

6.5 Telegram Reporting

Bot sends:

Entry confirmation

Exit confirmation

Reason for exit (TSL hit, SL hit, TP target reached)

Balance update

Session summary when bot stops

This ensures full traceability of actions.

## 7. Configuration (config.json)

Example values taken from your project:

{
    "mexc": {
        "api_key": "",
        "api_secret": ""
    },
    "telegram": {
        "token": "",
        "chat_id": ""
    },
    "parameters": {
        "tp": 200.0,
        "sl": 10,
        "margin": 100,
        "listing_time": "12:30",
        "estimated_price": 0.005,
        "instant_entry": true,
        "max_jump_pct": 20
    },
    "target_symbol": "TBA/USDT"
}

Parameter Explanation
Parameter	Meaning
tp	Profit percentage at which exit is triggered if trailing SL isn't hit
sl	Initial stop-loss percentage
margin	Percentage of available USDT balance to use for entry
listing_time	Scheduled sniping trigger time
estimated_price	Fallback entry price
instant_entry	Enables buying even if ticker isn't yet available
max_jump_pct	Allowed price deviation jump
## 8. Installation
Step 1. Clone Repository
git clone https://github.com/yourname/mexc-sniper-bot.git

Step 2. Install Dependencies
pip install -r requirements.txt

Step 3. Configure API Keys

Update config.json.

Step 4. Start the Bot
python sm.py

## 9. Usage
Basic Commands
Command	Description
/menu	Opens the main control dashboard
/start	Activates the sniper engine
/stop	Stops bot and closes active trades
/balance	Shows account balance
/status	Displays running status
/trades	Shows full trade history
/set coin X/USDT	Set target coin
/set time HH:MM	Assign scheduled listing
/set tp X	Set take-profit
/set sl X	Set stop-loss
/set margin X	Set margin allocation
/clear	Clears active target

## 10. Trade Engine Logic
Buy Order Logic

Calculates amount based on margin and price.

Ensures minimum order requirement (1 USDT) is respected.

Uses exchange precision settings.

Monitoring Logic

Loops continuously with 0.1s interval.

Tracks max price, SL trigger, TSL trigger.

Executes sell instantly when conditions match.

Exit Condition Flow

Initial SL hit

Trailing SL hit

TP target reached (if enabled)

Trade Logging

Each trade record contains:

Symbol

Entry price

Exit price

Profit/Loss percent

Profit/Loss in USDT

Reason for closing

Timestamp

## 11. Risk Management Model

The bot uses:

Fixed stop-loss

Trailing stop-loss

Capital allocation per trade via margin percentage

No re-entry after exit

Maximum allowed simultaneous trades

Users must choose settings appropriate to their strategy.

## 12. Data Persistence
trade_history.json

Stores historical trades.
Each entry includes detailed performance metrics.

config.json

Persistently stores user parameters across sessions.

## 13. Project Structure
sm.py                  # Main bot file
config.json            # User configuration & API keys
trade_history.json     # Historical trade log
README.md              # Documentation

## 14. Limitations & Recommendations

Requires stable network to sync with MEXC servers.

API key must have trading permissions enabled.

Sudden price gaps during listing may cause slippage.

Running too close to listing time may reduce precision.

Use small capital for testing to validate risk model.

# 15. Disclaimer

Automated trading involves financial risk.
This bot executes real trades and should only be run if you understand the consequences.
The developer is not responsible for losses or unexpected API behavior.
