# Enhanced Telegram → MT5 Trading Bot

## Overview

Production-ready algorithmic trading bot with advanced features including:
- Dual signal format support (Format 1 & 2)
- Entry confirmation with technical analysis
- Fixed lot sizing with max 15 positions
- Break-even activation and runner mode
- Comprehensive Telegram notifications
- Full audit trail with database logging

---

## Features

### 1. Signal Parsing (Dual Format Support)

#### Format 1: Structured multi-line signals
```
XAUUSD BUY
Entry: 3360-3357
SL: 3350
TP1: 3367
TP2: 3375
```

#### Format 2: Compact signals
```
BUY GOLD
3360-3357
SL 3350
TP 3370
```

**Supported symbols and aliases:**
- Direct: EURUSD, GBPUSD, XAUUSD, etc.
- Aliases: GOLD → XAUUSD, SILVER → XAGUSD, OIL → XTIUSD

### 2. Entry Confirmation Engine

Validates entries using four confirmation checks:

| Check | Details |
|-------|---------|
| **Entry Zone** | Price must be within specified entry zone |
| **M1/M5 Rejection Candles** | Rejects invalid price movements (2x body, 70% range) |
| **Break of Structure** | Confirms price breaks previous swing high/low |
| **Momentum** | At least 1 directional candle in last 2 |
| **EMA Confirmation** | EMA20 > EMA50 (BUY) or EMA20 < EMA50 (SELL) |

All 5 must pass before trade execution.

### 3. Position Management

| Feature | Specification |
|---------|---------------|
| **Lot Size** | Fixed 0.29 lots (no balance-based calculations) |
| **Max Positions** | 15 concurrent open trades |
| **Multiple Entries** | Support re-entry from same signal |
| **Auto SL/TP** | Set from signal parameters |
| **Break-Even** | Auto-move SL to entry when TP1 hit |
| **Runner Mode** | Trailing stop on continued trend |

### 4. Runner Mode & Trend Continuation

**Activation:** When first TP level is reached

**Trend checks:**
- **BUY:** Higher highs, higher lows, no bearish CHOCH, EMA20 > EMA50
- **SELL:** Lower highs, lower lows, no bullish CHOCH, EMA20 < EMA50

**Trailing Stop:**
- BUY: Trail below swing lows
- SELL: Trail above swing highs

### 5. Safety Features

```python
# Emergency Stop - close all immediately
await pipeline.emergency_stop()

# Pause New Trades - manage existing only
await pipeline.pause_new_trades()

# Resume Trading
await pipeline.resume_trades()
```

### 6. Telegram Notifications

Real-time alerts for:
- 📊 Signal received
- 🎯 Entry zone reached
- ✅ Trade opened (ticket, price, SL)
- 🛡️ Break-even activated
- 🎊 Take profit reached
- 🚀 Runner mode activated
- 🏁 Trade closed (P&L, %)
- ⚠️ Errors

### 7. Database Logging

Persistent storage for:
- **Signals:** Symbol, action, zones, SL/TP, source, status
- **Trades:** Entry/exit, P&L, BE/runner status, linked signal
- **Modifications:** SL moves, TP moves, BE activation, timestamps
- **Errors:** Type, message, context, occurrence time

---

## Architecture

### Module Structure

```
src/
├── signal_parser/
│   └── enhanced_parser.py         # Format 1 & 2 parsing
├── entry_confirmation/
│   └── confirmation_engine.py     # Technical analysis checks
├── position_manager/
│   └── enhanced_manager.py        # Fixed lot, 15-position management
├── notifications/
│   └── telegram_notifier.py       # Telegram alert system
├── database/
│   └── db_manager.py              # SQLite persistence
└── pipeline/
    └── enhanced_orchestrator.py   # Main coordinator
```

### Data Flow

```
Telegram Channel
    ↓
[Signal Parser] → Parse Format 1 or 2
    ↓
[Save to DB] → Store signal
    ↓
[Send Notification] → Signal received alert
    ↓
[Monitoring Loop] → Wait for entry zone
    ↓
[Entry Confirmation] → Validate 5 checks
    ↓
[Position Manager] → Place order (fixed 0.29 lot)
    ↓
[Tracking Loop] → Update P&L, manage runner mode
    ↓
[DB & Notifications] → Log all changes
```

---

## Configuration

### Environment Variables (.env)

```bash
# Telegram
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_PHONE=+...
TELEGRAM_CHANNELS=["channel1", "channel2"]
TELEGRAM_BOT_TOKEN=...          # For notifications
TELEGRAM_NOTIFY_CHAT_ID=...     # Notification target

# MT5
MT5_LOGIN=...
MT5_PASSWORD=...
MT5_SERVER=...
MT5_PATH=/path/to/terminal64.exe

# Trading
FIXED_LOT_SIZE=0.29
MAX_OPEN_POSITIONS=15
ENABLE_RUNNER_MODE=true
ENABLE_BREAK_EVEN=true

# Database
DATABASE_PATH=data/trading_bot.db
ENABLE_NOTIFICATIONS=true
```

---

## Running the Bot

### 1. Setup Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your credentials
```

### 2. Run Locally

```bash
python main.py
```

### 3. Run with Docker

```bash
docker-compose up -d
docker-compose logs -f trading-bot
```

---

## Monitoring

### Logs

- **Location:** `logs/trading_bot.log` (JSON format)
- **Rolling:** 10MB per file, 5 backups
- **Includes:** Timestamps, levels, modules, functions

### Database Queries

```python
from src.database.db_manager import DatabaseManager

db = DatabaseManager()

# Get trading statistics
stats = db.get_trade_stats()
# Returns: total_trades, open_trades, win_rate, total_profit, etc.

# Get open trades
open = db.get_open_trades()

# Get signal details
signal = db.get_signal_by_id(signal_id)
```

### Prometheus Metrics (Optional)

- `trades_executed_total` - Counter by symbol/action
- `trade_volume_total` - Total trading volume
- `active_positions` - Current open positions
- `account_balance` - Balance gauge
- `signal_processing_latency_seconds` - Histogram
- `errors_total` - Error counter by type

---

## Example Signal Messages

### Gold BUY (Format 1)
```
XAUUSD BUY
Entry: 3360-3357
SL: 3350
TP1: 3370
TP2: 3380
```

### EUR/USD SELL (Format 2)
```
SELL EURUSD
1.0850-1.0845
SL 1.0860
TP 1.0820
```

### Oil BUY with Confidence (Format 1)
```
OIL BUY
Entry: 82.50-82.40
SL: 82.00
TP1: 83.50
TP2: 84.50
Confidence: 90%
```

---

## Database Schema

### signals table
- `id` (PK), `symbol`, `action`, `entry_zone_min/max`, `stop_loss`
- `take_profits` (JSON), `confidence`, `channel`, `raw_format`
- `received_at`, `zone_reached_at`, `status`

### trades table
- `id` (PK), `ticket` (unique), `signal_id` (FK)
- `symbol`, `action`, `entry_price`, `exit_price`
- `stop_loss`, `take_profits` (JSON), `volume`
- `opened_at`, `closed_at`, `profit_loss`, `profit_loss_percent`
- `be_activated`, `runner_mode`

### trade_modifications table
- `id` (PK), `ticket`, `modification_type` (sl_moved, tp_moved, etc.)
- `old_value`, `new_value`, `reason`, `modified_at`

### error_logs table
- `id` (PK), `error_type`, `error_message`, `context`, `occurred_at`

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| MT5 not found | Set `MT5_PATH` to terminal64.exe full path |
| Telegram auth fails | Check API_ID/HASH; may need to re-authenticate |
| No signals parsed | Verify message format matches Format 1 or 2 |
| Entry not confirmed | Check technical analysis settings; enable verbose logging |
| Database locked | Ensure only one instance running |

---

## API Reference

### EnhancedTradingPipeline

```python
pipeline = EnhancedTradingPipeline(...)

# Start
await pipeline.start()

# Stop
await pipeline.stop()

# Safety controls
await pipeline.emergency_stop()
await pipeline.pause_new_trades()
await pipeline.resume_trades()
```

### EnhancedPositionManager

```python
# Check if can open
can_open, reason = manager.can_open_new_position(signal_id)

# Place order
trade = manager.place_entry_order(...)

# Activate BE
manager.activate_break_even(ticket)

# Activate trailing stop
manager.activate_trailing_stop(ticket, trail_distance)

# Close position
manager.close_position(ticket)

# Get summary
summary = manager.get_open_trades_summary()
```

### DatabaseManager

```python
db = DatabaseManager()

# Save/retrieve
signal_id = db.save_signal(...)
db.save_trade(ticket, signal_id, ...)
db.close_trade(ticket, exit_price, pl, pl%)

# Tracking
db.record_modification(ticket, "sl_moved", old, new)
db.log_error(error_type, message)

# Query
stats = db.get_trade_stats()
trades = db.get_open_trades()
```

---

## Performance Considerations

- **Signal parsing:** <10ms per message
- **Entry confirmation:** <50ms per signal
- **Position updates:** <100ms per position
- **Database writes:** Async, non-blocking
- **Notifications:** Async, queued

Monitoring loop: 1 second cycle

---

## Future Enhancements

- [ ] Web dashboard for position management
- [ ] Backtesting engine
- [ ] Multi-timeframe analysis
- [ ] Advanced technical indicators (MACD, RSI, etc.)
- [ ] AI-based signal filtering
- [ ] Performance analytics
- [ ] Export trade reports

---

## Support & Documentation

- **Database:** SQLite at `data/trading_bot.db`
- **Logs:** JSON format at `logs/trading_bot.log`
- **Config:** Environment variables in `.env`
- **Issues:** Check logs for detailed error context
