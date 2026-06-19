# Strategy Testing TODO

This document lists the remaining work before production approval. Core integration is complete; strategy testing is the main remaining phase.

## Objective

Validate that the bot's entry logic, trade management, and risk settings behave correctly across real market conditions before live deployment.

## Current Integration Status

Completed:

- Telegram signal ingestion.
- Signal parsing.
- MT5 account connection.
- Broker symbol resolution.
- Gold and crypto symbol support.
- Entry-zone monitoring.
- Fixed-lot order request generation.
- Broker `order_check` validation.
- Signal and trade audit trail.

Remaining:

- Strategy performance testing.
- Entry-confirmation testing.
- Risk and lot-size validation.
- Demo/live dry-run.

## Test Phases

### Phase 1: Parser Testing

Goal: confirm all expected client signal formats parse correctly.

Test cases:

- `XAUUSD BUY` with entry zone, SL, TP1, TP2.
- `XAUUSD SELL` with entry zone, SL, TP1, TP2.
- `BTCUSD BUY` with realistic BTC prices.
- `ETHUSD SELL` with realistic ETH prices.
- Action-first format: `BUY ETHUSD @ 3400`.
- Compact format: `BTCUSD BUY 62900 - 63100`.
- Invalid signal with missing SL.
- Invalid signal with SL on the wrong side of entry.

Pass criteria:

- Valid signals are saved to `data/signals.json`.
- Invalid signals are skipped and logged.
- Symbol, action, entry zone, SL, and TP values are correct.

### Phase 2: Broker Symbol Testing

Goal: confirm all client symbols resolve to tradable MT5 symbols.

Known broker symbols:

- `XAUUSDm`
- `BTCUSDm`
- `BTCUSDTm`
- `ETHUSDm`
- `LTCUSDm`
- `XRPUSDm`
- `DOGEUSDm`
- `SOLUSDm`

Pass criteria:

- Clean symbols like `XAUUSD`, `BTCUSD`, and `ETHUSD` resolve successfully.
- Bad symbols like `BTCUSDM` fail with clear logs.
- Bid/ask values are non-zero before order attempts.

### Phase 3: Entry-Zone Testing

Goal: confirm the bot only attempts trades when current price is inside the entry zone.

Test cases:

- Entry zone below current market price.
- Entry zone above current market price.
- Entry zone containing current market price.
- Narrow entry zone.
- Wide entry zone.

Pass criteria:

- Outside-zone signals remain `pending`.
- Inside-zone signals become `zone_reached`.
- Expired signals become `expired`.

### Phase 4: Order Validation Testing

Goal: confirm order requests are broker-valid before live placement.

Use `MetaTrader5.order_check`, not `order_send`, for this phase.

Test cases:

- Gold BUY and SELL.
- BTC BUY and SELL.
- ETH BUY and SELL.
- Minimum allowed lot.
- Configured lot size.
- Invalid SL/TP distances.

Pass criteria:

- Valid requests return `retcode=0` and `comment='Done'`.
- Invalid requests show clear broker error details.
- Volume is normalized to broker min/max/step.

### Phase 5: Demo Order Testing

Goal: confirm real order placement on demo account.

Settings:

```env
TRADING_MODE=live
ENABLE_BYPASS_ENTRY_CONFIRMATION=true
FIXED_LOT_SIZE=0.01
SIGNAL_EXPIRY_SECONDS=600
SIGNAL_POLL_INTERVAL=2
```

Test cases:

- One XAUUSD BUY.
- One XAUUSD SELL.
- One BTCUSD BUY or SELL.

Pass criteria:

- Signal status becomes `traded`.
- Trade appears in `data/trades.json`.
- MT5 terminal shows the position.
- No unhandled exceptions in `logs/trading_bot.log`.

### Phase 6: Confirmation Strategy Testing

Goal: test the actual confirmation logic.

Settings:

```env
ENABLE_BYPASS_ENTRY_CONFIRMATION=false
```

Checks to validate:

- Entry zone.
- M1/M5 rejection candle.
- Break of structure.
- Momentum.
- EMA confirmation.

Pass criteria:

- Bot does not trade when confirmation fails.
- Bot trades only when all required conditions pass.
- Logs explain failed confirmation reasons.

### Phase 7: Trade Management Testing

Goal: validate post-entry behavior.

Features:

- Break-even activation.
- Runner mode.
- Trailing stop.
- Close position.
- Close all positions.

Pass criteria:

- SL moves to entry when break-even condition is met.
- Runner mode activates only after expected TP condition.
- Closing operations update `data/trades.json`.

### Phase 8: Production Readiness Review

Before production:

- Set final `FIXED_LOT_SIZE`.
- Set final `MAX_OPEN_POSITIONS`.
- Set `ENABLE_BYPASS_ENTRY_CONFIRMATION=false`.
- Confirm notification target.
- Confirm Telegram channel IDs.
- Confirm broker symbols.
- Confirm MT5 account type and leverage.
- Confirm maximum acceptable risk.

Pass criteria:

- Demo testing completed.
- Strategy testing completed.
- Client approves risk settings.
- No critical errors in latest logs.

## Known Risks

- Live trading can lose money.
- Strategy confirmation logic still needs market validation.
- Broker symbol availability can vary by account/server.
- Crypto spreads and minimum stop distances can be wider than forex/metals.
- Market execution can fail even if `order_check` passes, especially during fast moves.

## Final Remaining Deliverable

The final remaining deliverable is strategy testing evidence:

- Test signal examples.
- Logs proving parser and zone behavior.
- `order_check` results.
- Demo trade screenshots or MT5 history.
- Final recommended production settings.
