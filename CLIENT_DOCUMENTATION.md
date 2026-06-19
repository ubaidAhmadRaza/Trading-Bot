# Client Documentation

## Project Summary

This project is a Telegram-to-MT5 trading automation system. It listens to configured Telegram channels, parses trading signals, waits for market price to enter the signal entry zone, and then places trades through MetaTrader 5.

The current build is ready for operational testing. Only strategy testing and final production validation remain.

## Completed Features

### Telegram Integration

- Connects to Telegram using Telethon.
- Supports public channel usernames and private channel IDs.
- Listens for new messages in configured signal channels.
- Parses incoming signal text automatically.

### Signal Parsing

Supported message styles:

```text
XAUUSD BUY
Entry: 4150 - 4160
SL: 4140
TP1: 4170
TP2: 4185
```

```text
BTCUSD BUY 62900 - 63100
SL: 62000
TP1: 64000
TP2: 65000
```

```text
BUY ETHUSD @ 3400
SL: 3300
TP: 3550
```

Supported actions:

- `BUY`
- `SELL`
- `LONG`, normalized to `BUY`
- `SHORT`, normalized to `SELL`

### MT5 Integration

- Connects to MT5 using configured login, password, server, and terminal path.
- Validates account connection.
- Selects symbols in Market Watch.
- Resolves clean signal symbols to broker-specific symbols.
- Reads bid/ask ticks before checking entry zones.
- Sends market orders through `MetaTrader5.order_send`.
- Uses `MetaTrader5.order_check` for non-trading validation.

### Broker Symbol Resolution

The bot accepts clean symbols from Telegram and maps them to broker symbols.

Examples:

| Telegram Signal | MT5 Broker Symbol |
|---|---|
| `XAUUSD` | `XAUUSDm` |
| `BTCUSD` | `BTCUSDm` or `BTCUSDTm` |
| `BTCUSDT` | `BTCUSDTm` |
| `ETHUSD` | `ETHUSDm` |
| `LTCUSD` | `LTCUSDm` |
| `XRPUSD` | `XRPUSDm` |
| `DOGEUSD` | `DOGEUSDm` |
| `SOLUSD` | `SOLUSDm` |

Client instruction: send clean base symbols such as `BTCUSD`, not broker-suffixed symbols such as `BTCUSDM`.

### Order Management

- Uses fixed lot size from `.env`.
- Enforces maximum open-position count.
- Normalizes lot size to broker minimum, maximum, and step.
- Applies stop loss and first take profit from the signal.
- Records open trades in `data/trades.json`.
- Records signal status changes in `data/signals.json`.

### Signal Lifecycle

Each signal can move through these statuses:

| Status | Meaning |
|---|---|
| `pending` | Signal parsed and waiting for entry zone. |
| `zone_reached` | Price entered the configured entry zone. |
| `traded` | MT5 order was placed and trade was saved. |
| `trade_failed` | Price reached zone, but order placement failed. |
| `expired` | Signal expired before a valid trade was placed. |

### Monitoring

Use:

```powershell
venv\Scripts\python.exe monitor_signals.py
```

Continuous watch mode:

```powershell
venv\Scripts\python.exe monitor_signals.py --watch 2
```

Important files:

- `logs/trading_bot.log`
- `data/signals.json`
- `data/trades.json`
- `data/errors.json`

### Notifications

If notification settings are configured, the system can send Telegram bot alerts for:

- Bot startup.
- Signal received.
- Entry zone reached.
- Trade opened.
- Break-even activated.
- Runner mode activated.
- Errors.

## Configuration Reference

Required `.env` values:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_CHANNELS=["-1001234567890"]

MT5_LOGIN=123456
MT5_PASSWORD=your_password
MT5_SERVER=Broker-Server
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

Trading settings:

```env
TRADING_MODE=live
FIXED_LOT_SIZE=0.29
MAX_OPEN_POSITIONS=15
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=2
ENABLE_BYPASS_ENTRY_CONFIRMATION=true
ENABLE_NOTIFICATIONS=false
```

Recommended production setting:

```env
ENABLE_BYPASS_ENTRY_CONFIRMATION=false
```

## Operating Procedure

1. Start MetaTrader 5.
2. Confirm the MT5 account is logged in.
3. Start the bot:

   ```powershell
   venv\Scripts\python.exe main.py
   ```

4. Send a signal to the configured Telegram channel.
5. Monitor the signal:

   ```powershell
   venv\Scripts\python.exe monitor_signals.py --watch 2
   ```

6. Check logs if no order is placed:

   ```powershell
   Get-Content logs\trading_bot.log -Tail 100
   ```

## Valid Test Signals

Gold:

```text
XAUUSD BUY
Entry: 4150 - 4160
SL: 4140
TP1: 4170
TP2: 4185
```

Bitcoin:

```text
BTCUSD BUY
Entry: 62900 - 63100
SL: 62000
TP1: 64000
TP2: 65000
```

Ethereum:

```text
ETHUSD SELL
Entry: 3450 - 3500
SL: 3600
TP1: 3350
TP2: 3250
```

Use entry zones near current market price when testing order execution.

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| Signal does not parse | Unsupported message format | Use documented format. |
| Signal stays pending | Market price is outside entry zone | Use an entry zone near current price for testing. |
| No MT5 price available | Broker symbol not found or no tick | Use clean symbols like `BTCUSD`, check MT5 Market Watch. |
| Order not placed | Broker rejected request | Check `trade_failed` status and `logs/trading_bot.log`. |
| Crypto not trading | Wrong symbol such as `BTCUSDM` | Use `BTCUSD` or `BTCUSDT`. |
| Signal expires | Zone not reached before timeout | Increase `SIGNAL_EXPIRY_SECONDS`. |

## Client Handoff Status

Ready:

- Signal ingestion.
- Symbol resolution.
- MT5 tick lookup.
- Entry-zone monitoring.
- Order request validation.
- JSON tracking.
- Monitoring and logs.

Remaining:

- Strategy testing.
- Confirmation-rule tuning.
- Demo account burn-in.
- Final risk settings.
- Production approval.
