# Testing and Monitoring Guide

## Purpose

Use this guide to verify the bot without guessing from logs. It covers signal parsing, MT5 symbol resolution, entry-zone behavior, order validation, and monitoring.

## Recommended Test Settings

For controlled testing:

```env
ENABLE_BYPASS_ENTRY_CONFIRMATION=true
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=2
FIXED_LOT_SIZE=0.01
```

For production strategy validation:

```env
ENABLE_BYPASS_ENTRY_CONFIRMATION=false
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=5
```

## Run the Bot

```powershell
venv\Scripts\python.exe main.py
```

Expected startup signs:

- MT5 connected.
- Telegram connected.
- Configured Telegram channel resolved.
- Listener started.

## Monitor Signals

Single snapshot:

```powershell
venv\Scripts\python.exe monitor_signals.py
```

Live monitoring:

```powershell
venv\Scripts\python.exe monitor_signals.py --watch 2
```

Signal status meanings:

| Status | Meaning |
|---|---|
| `pending` | Waiting for price to enter zone. |
| `zone_reached` | Price entered the zone. |
| `traded` | Order was placed and recorded. |
| `trade_failed` | Zone was reached, but order failed. |
| `expired` | Signal expired before trade. |

## View Logs

Last 100 log lines:

```powershell
Get-Content logs\trading_bot.log -Tail 100
```

Search for errors:

```powershell
Select-String -Path logs\trading_bot.log -Pattern "ERROR|trade_failed|retcode|last_error"
```

Search for symbol resolution:

```powershell
Select-String -Path logs\trading_bot.log -Pattern "Resolved MT5 symbol"
```

## Validate MT5 Connection

```powershell
venv\Scripts\python.exe diagnose_mt5.py
```

This checks:

- MT5 terminal path.
- Login credentials.
- Account connection.

## Test Signals

Use an entry zone near current market price if the goal is to trigger order logic.

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

Do not use broker suffixes in Telegram messages. Use `BTCUSD`, not `BTCUSDM`.

## Order Validation Without Live Trade

Use MT5 `order_check` during strategy testing before allowing `order_send`.

What to verify:

- Symbol resolves to broker symbol.
- Bid/ask is non-zero.
- Lot size is within broker limits.
- SL and TP are accepted.
- Required margin is acceptable.

Successful validation usually returns:

```text
retcode=0
comment=Done
```

## JSON Files

Signals:

```powershell
Get-Content data\signals.json
```

Trades:

```powershell
Get-Content data\trades.json
```

Errors:

```powershell
Get-Content data\errors.json
```

## Test Scenarios

### Scenario 1: Signal Parses

1. Start the bot.
2. Send a valid Telegram signal.
3. Confirm `data/signals.json` has a new record.

Pass:

- Symbol, action, entry zone, SL, and TP are correct.

### Scenario 2: Signal Waits

1. Send a valid signal with entry zone far from current price.
2. Run `monitor_signals.py`.

Pass:

- Signal remains `pending`.
- Logs show current price versus entry zone.

### Scenario 3: Signal Expires

1. Send a signal with entry zone far from current price.
2. Wait longer than `SIGNAL_EXPIRY_SECONDS`.

Pass:

- Signal becomes `expired`.

### Scenario 4: Zone Reached

1. Send a signal with entry zone around current price.
2. Monitor signal status.

Pass:

- Signal becomes `zone_reached`.
- With bypass enabled, order placement is attempted.

### Scenario 5: Trade Placed

Use demo account or very small lot.

Pass:

- Signal becomes `traded`.
- Trade appears in `data/trades.json`.
- MT5 terminal shows the position.

### Scenario 6: Strategy Confirmation

Set:

```env
ENABLE_BYPASS_ENTRY_CONFIRMATION=false
```

Pass:

- Bot only trades after confirmation checks pass.
- Failed checks are logged.

## Remaining Testing

See `STRATEGY_TESTING_TODO.md` for the full remaining strategy-testing checklist.
