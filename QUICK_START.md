# Quick Start

## 1. Configure `.env`

Use `.env.example` as the template and set:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_CHANNELS=["-1001234567890"]

MT5_LOGIN=123456
MT5_PASSWORD=your_password
MT5_SERVER=Broker-Server
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

FIXED_LOT_SIZE=0.01
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=2
ENABLE_BYPASS_ENTRY_CONFIRMATION=true
```

Use a demo account or very small lot while testing.

## 2. Start MetaTrader 5

Open MT5 and confirm the account is logged in.

## 3. Run the Bot

```powershell
venv\Scripts\python.exe main.py
```

## 4. Monitor Signals

```powershell
venv\Scripts\python.exe monitor_signals.py --watch 2
```

## 5. Send a Test Signal

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

Use an entry zone near current market price if you want the order logic to trigger quickly.

## 6. Check Results

Files:

- `data/signals.json`
- `data/trades.json`
- `data/errors.json`
- `logs/trading_bot.log`

Docs:

- `CLIENT_DOCUMENTATION.md`
- `TESTING_AND_MONITORING.md`
- `STRATEGY_TESTING_TODO.md`
