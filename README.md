# Telegram MT5 Trading Bot

Client-ready Telegram-to-MetaTrader 5 trading bot for reading trading signals from Telegram channels, validating entry zones, and placing MT5 market orders.

## Current Status

The order execution pipeline is implemented and verified with MT5 `order_check`.

Completed:

- Telegram channel listener using Telethon.
- Signal parser for structured and compact signal messages.
- MT5 login and broker symbol resolution.
- Gold and crypto symbol mapping, including broker suffixes such as `XAUUSDm`, `BTCUSDm`, and `BTCUSDTm`.
- Entry-zone monitoring.
- Optional entry-confirmation bypass for testing.
- Fixed-lot order placement.
- JSON audit trail for signals, trades, errors, and modifications.
- Signal lifecycle statuses: `pending`, `zone_reached`, `traded`, `trade_failed`, `expired`.
- Monitoring script for signal/trade status.

Remaining:

- Strategy testing and validation on historical/live market scenarios.
- Final production risk settings.
- Client sign-off after demo/live dry-run.

## Quick Start

Use PowerShell from the project root:

```powershell
venv\Scripts\python.exe main.py
```

Monitor signal status:

```powershell
venv\Scripts\python.exe monitor_signals.py
```

Run MT5 diagnostics:

```powershell
venv\Scripts\python.exe diagnose_mt5.py
```

## Required Configuration

Create `.env` from `.env.example` and configure:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_CHANNELS=["-1001234567890"]

MT5_LOGIN=123456
MT5_PASSWORD=your_password
MT5_SERVER=Broker-Server
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

TRADING_MODE=live
FIXED_LOT_SIZE=0.29
MAX_OPEN_POSITIONS=15
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=2
ENABLE_BYPASS_ENTRY_CONFIRMATION=true
```

Important: `ENABLE_BYPASS_ENTRY_CONFIRMATION=true` is for testing only. In production, set it to `false` so the confirmation engine controls entries.

## Supported Signal Formats

Structured format:

```text
XAUUSD BUY
Entry: 4150 - 4160
SL: 4140
TP1: 4170
TP2: 4185
```

Compact inline format:

```text
BTCUSD BUY 62900 - 63100
SL: 62000
TP1: 64000
TP2: 65000
```

Action-first format:

```text
BUY ETHUSD @ 3400
SL: 3300
TP: 3550
```

## Supported Symbols

The bot accepts clean signal symbols and resolves them to broker symbols.

Examples verified on the current broker:

| Signal Symbol | Broker Symbol |
|---|---|
| `XAUUSD` | `XAUUSDm` |
| `BTCUSD` | `BTCUSDm` or `BTCUSDTm` |
| `BTCUSDT` | `BTCUSDTm` |
| `ETHUSD` | `ETHUSDm` |
| `LTCUSD` | `LTCUSDm` |
| `XRPUSD` | `XRPUSDm` |
| `DOGEUSD` | `DOGEUSDm` |
| `SOLUSD` | `SOLUSDm` |

Do not send symbols like `BTCUSDM`. Use clean names such as `BTCUSD`; the bot handles broker suffixes.

## Data Files

The bot uses JSON storage:

- `data/signals.json`: signal lifecycle.
- `data/trades.json`: opened and closed trades.
- `data/modifications.json`: SL/TP and trade-management events.
- `data/errors.json`: operational errors.
- `logs/trading_bot.log`: JSON logs.

## Key Documentation

- `CLIENT_DOCUMENTATION.md`: client handoff and usage guide.
- `STRATEGY_TESTING_TODO.md`: remaining strategy testing plan.
- `TESTING_AND_MONITORING.md`: testing and monitoring procedures.
- `TELEGRAM_CHANNELS_GUIDE.md`: channel setup help.

## Safety Notes

This bot can place real trades when connected to a live MT5 account. Before production use:

- Test on a demo account.
- Use a small lot size.
- Set `ENABLE_BYPASS_ENTRY_CONFIRMATION=false`.
- Confirm broker symbols and minimum lot sizes.
- Validate strategy behavior with the checklist in `STRATEGY_TESTING_TODO.md`.
