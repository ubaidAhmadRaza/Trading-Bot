# Setup Guide

## Requirements

- Windows machine with MetaTrader 5 installed.
- MT5 account credentials.
- Telegram API credentials from `https://my.telegram.org`.
- Python virtual environment already present at `venv`.

## Telegram Setup

1. Go to `https://my.telegram.org`.
2. Create an API app.
3. Copy `api_id` and `api_hash`.
4. Add them to `.env`:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
```

Configure channels:

```env
TELEGRAM_CHANNELS=["-1001234567890"]
```

Use `find_telegram_channels.py` if you need to discover available channel IDs.

## MT5 Setup

Add MT5 credentials:

```env
MT5_LOGIN=123456
MT5_PASSWORD=your_password
MT5_SERVER=Broker-Server
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

Validate MT5:

```powershell
venv\Scripts\python.exe diagnose_mt5.py
```

## Trading Settings

Testing:

```env
FIXED_LOT_SIZE=0.01
MAX_OPEN_POSITIONS=15
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=2
ENABLE_BYPASS_ENTRY_CONFIRMATION=true
```

Production strategy validation:

```env
ENABLE_BYPASS_ENTRY_CONFIRMATION=false
SIGNAL_POLL_INTERVAL=5
```

## Run

```powershell
venv\Scripts\python.exe main.py
```

## Monitor

```powershell
venv\Scripts\python.exe monitor_signals.py --watch 2
```

## Storage

The project uses JSON storage:

- `data/signals.json`
- `data/trades.json`
- `data/modifications.json`
- `data/errors.json`

Logs are stored in:

- `logs/trading_bot.log`

## Next Step

After setup, follow `STRATEGY_TESTING_TODO.md`. Strategy testing is the remaining phase before production approval.
