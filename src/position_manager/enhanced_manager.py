"""
Enhanced Position Manager
Handles:
- Fixed lot size
- Maximum 15 open positions
- Multiple entries from same signal
- Partial TP closes (TP1: configurable %, TP2: remainder)
- Break-even after TP1
- Trailing stop after TP1
"""
import MetaTrader5 as mt5
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeStatus(str, Enum):
    OPEN         = "open"
    TP1_HIT      = "tp1_hit"       # partial closed, BE set, trailing active
    TP2_HIT      = "tp2_hit"       # fully closed at TP2
    CLOSED       = "closed"        # closed externally (SL / manual)
    ERROR        = "error"
    # Legacy aliases kept so orchestrator _handle_trade_update still compiles
    BE_ACTIVATED = "tp1_hit"
    RUNNER_MODE  = "tp1_hit"


@dataclass
class TradeInfo:
    ticket:              int
    symbol:              str
    action:              str            # BUY | SELL
    entry_price:         float
    current_price:       float
    volume:              float          # original full volume at open
    remaining_volume:    float          # volume still open in MT5
    stop_loss:           float
    take_profits:        List[float]    # [TP1, TP2, …]
    break_even_price:    float
    status:              TradeStatus
    opened_at:           datetime
    signal_id:           str
    profit_loss:         float
    profit_loss_percent: float
    trailing_stop:       Optional[float] = None
    tp_reached_at:       Optional[datetime] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d['status']        = self.status.value
        d['opened_at']     = self.opened_at.isoformat()
        d['tp_reached_at'] = self.tp_reached_at.isoformat() if self.tp_reached_at else None
        return d


class EnhancedPositionManager:

    def __init__(self, mt5_client, fixed_lot_size: float = 0.29, max_positions: int = 15):
        self.mt5_client     = mt5_client
        self.fixed_lot_size = fixed_lot_size
        self.max_positions  = max_positions
        self.open_trades: Dict[int, TradeInfo] = {}
        self.signal_entry_count: Dict[str, int] = {}

        # Pull config from settings with safe defaults
        try:
            from config.settings import settings
            self.tp1_close_ratio: float = getattr(settings, 'TP1_CLOSE_RATIO', 0.5)
            self.trail_distance:  float = getattr(settings, 'TRAIL_DISTANCE',  1.0)
            self.trail_step:      float = getattr(settings, 'TRAIL_STEP',      0.5)
        except Exception:
            self.tp1_close_ratio = 0.5
            self.trail_distance  = 1.0
            self.trail_step      = 0.5

    # ── Eligibility ────────────────────────────────────────────────────────

    def can_open_new_position(self, signal_id: str) -> Tuple[bool, str]:
        if len(self.open_trades) >= self.max_positions:
            return False, f"Max {self.max_positions} positions already open"
        return True, "OK"

    # ── MT5 helpers ────────────────────────────────────────────────────────

    def _normalize_volume(self, requested: float, symbol_info: dict) -> float:
        lo   = symbol_info.get('volume_min')  or requested
        hi   = symbol_info.get('volume_max')  or requested
        step = symbol_info.get('volume_step') or 0.01
        vol  = max(lo, min(requested, hi))
        steps = round((vol - lo) / step)
        return round(lo + steps * step, 8)

    def _get_filling_type(self, symbol_info: dict):
        fm = symbol_info.get('filling_mode')
        if fm == mt5.ORDER_FILLING_FOK:    return mt5.ORDER_FILLING_FOK
        if fm == mt5.ORDER_FILLING_IOC:    return mt5.ORDER_FILLING_IOC
        if fm == mt5.ORDER_FILLING_RETURN: return mt5.ORDER_FILLING_RETURN
        return mt5.ORDER_FILLING_IOC

    def _extract_position_ticket(self, result, symbol: str, magic: int, comment: str) -> Optional[int]:
        for attr in ('order', 'deal'):
            ticket = getattr(result, attr, None)
            if ticket:
                positions = mt5.positions_get(ticket=ticket)
                if positions:
                    return positions[0].ticket
        positions = mt5.positions_get(symbol=symbol) or []
        for p in positions:
            if getattr(p, 'magic', None) == magic and getattr(p, 'comment', '') == comment:
                return p.ticket
        if len(positions) == 1:
            return positions[0].ticket
        return None

    def _get_mt5_position_volume(self, ticket: int) -> Optional[float]:
        """Read actual remaining volume from MT5 (avoids stale local state)."""
        positions = mt5.positions_get(ticket=ticket)
        if positions:
            return positions[0].volume
        return None

    # ── Order placement ────────────────────────────────────────────────────
    # NO TP set on the MT5 order — we manage partials manually.
    # Setting TP here would let MT5 close 100% of volume at TP1.

    def place_entry_order(
        self,
        symbol:       str,
        action:       str,
        entry_price:  float,
        stop_loss:    float,
        take_profits: List[float],
        signal_id:    str
    ) -> Optional[TradeInfo]:
        try:
            order_type  = mt5.ORDER_TYPE_BUY if action.upper() == 'BUY' else mt5.ORDER_TYPE_SELL
            symbol_info = self.mt5_client.get_symbol_info(symbol)
            if not symbol_info:
                logger.error(f"Could not get symbol info for {symbol}")
                return None

            trade_symbol = symbol_info['symbol']
            market_price = symbol_info['ask'] if order_type == mt5.ORDER_TYPE_BUY else symbol_info['bid']
            volume       = self._normalize_volume(self.fixed_lot_size, symbol_info)
            magic        = 777888
            comment      = f"EnhancedTrader-{signal_id}"

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       trade_symbol,
                "volume":       volume,
                "type":         order_type,
                "price":        market_price,
                "deviation":    20,
                "magic":        magic,
                "comment":      comment,
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_type(symbol_info),
            }

            if stop_loss:
                request["sl"] = stop_loss

            # Set last TP on MT5 order as crash safety net.
            # Bot manages TP1 partial close + BE + trailing manually.
            # If bot crashes, MT5 will close remainder at final TP.
            if take_profits:
                request["tp"] = take_profits[-1]

            result = mt5.order_send(request)
            if result is None:
                logger.error(f"order_send returned None for {symbol}: {mt5.last_error()}")
                return None

            logger.info(
                f"Order send result for {trade_symbol}: retcode={result.retcode}, "
                f"comment={result.comment}, order={result.order}, deal={result.deal}"
            )

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Order failed for {trade_symbol}: {result.comment} "
                    f"(retcode={result.retcode}) | last_error={mt5.last_error()}"
                )
                return None

            ticket = self._extract_position_ticket(result, trade_symbol, magic, comment)
            if not ticket:
                logger.error(f"Could not resolve ticket for {trade_symbol}")
                return None

            trade = TradeInfo(
                ticket              = ticket,
                symbol              = trade_symbol,
                action              = action,
                entry_price         = market_price,
                current_price       = market_price,
                volume              = volume,
                remaining_volume    = volume,
                stop_loss           = stop_loss,
                take_profits        = take_profits,
                break_even_price    = market_price,
                status              = TradeStatus.OPEN,
                opened_at           = datetime.utcnow(),
                signal_id           = signal_id,
                profit_loss         = 0.0,
                profit_loss_percent = 0.0,
            )

            self.open_trades[ticket] = trade
            self._increment_signal_entry_count(signal_id)
            logger.info(f"Order placed: {trade_symbol} {action} Ticket={ticket} Vol={volume}")
            return trade

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    # ── Position monitoring ────────────────────────────────────────────────

    def update_positions(self) -> List[TradeInfo]:
        """
        Called every poll cycle by the orchestrator.
        - Syncs price/profit from MT5
        - Runs TP1 / TP2 / trailing logic internally
        - Returns updated TradeInfo list for the orchestrator to log/notify
        """
        try:
            mt5_positions = {p['ticket']: p for p in self.mt5_client.get_positions()}
            updated = []

            for ticket, trade in list(self.open_trades.items()):

                # Position closed externally (SL hit, manual close, etc.)
                if ticket not in mt5_positions:
                    logger.info(f"Ticket {ticket} no longer in MT5 — marking closed")
                    trade.status = TradeStatus.CLOSED
                    del self.open_trades[ticket]
                    continue

                pos = mt5_positions[ticket]
                trade.current_price = pos['price_current']
                trade.profit_loss   = pos['profit']

                # Sync remaining_volume from MT5 (source of truth)
                mt5_vol = pos.get('volume', trade.remaining_volume)
                trade.remaining_volume = mt5_vol

                # P&L %
                price_diff = abs(trade.current_price - trade.entry_price)
                if trade.entry_price > 0:
                    pct = (price_diff / trade.entry_price) * 100
                    trade.profit_loss_percent = pct if trade.action.upper() == 'BUY' else -pct

                # State machine — all MT5 actions happen inside these methods
                if trade.status == TradeStatus.OPEN:
                    self._check_tp1(trade)

                elif trade.status == TradeStatus.TP1_HIT:
                    self._check_tp2(trade)
                    if trade.status != TradeStatus.TP2_HIT:
                        self._update_trailing_stop(trade)

                updated.append(trade)

            return updated

        except Exception as e:
            logger.error(f"Error updating positions: {e}")
            return []

    # ── TP1 ────────────────────────────────────────────────────────────────

    def _check_tp1(self, trade: TradeInfo):
        if not trade.take_profits:
            return
        tp1 = trade.take_profits[0]

        hit = (trade.action.upper() == 'BUY'  and trade.current_price >= tp1) or \
              (trade.action.upper() == 'SELL' and trade.current_price <= tp1)
        if not hit:
            return

        logger.info(f"TP1 hit for ticket {trade.ticket} at {trade.current_price}")

        # Partial close — read actual MT5 volume first to avoid stale state
        mt5_vol    = self._get_mt5_position_volume(trade.ticket) or trade.remaining_volume
        close_vol  = round(mt5_vol * self.tp1_close_ratio, 8)
        if self._partial_close_volume(trade, close_vol):
            trade.remaining_volume = round(mt5_vol - close_vol, 8)
            logger.info(
                f"TP1 partial close: {close_vol} lots closed, "
                f"{trade.remaining_volume} lots remaining for ticket {trade.ticket}"
            )

        # Move SL to break-even
        if self._move_sl(trade, round(trade.entry_price, 2)):
            trade.break_even_price = trade.entry_price
            logger.info(f"Break-even set at {trade.entry_price} for ticket {trade.ticket}")

        # Initialise trailing stop
        if trade.action.upper() == 'BUY':
            trade.trailing_stop = trade.current_price - self.trail_distance
        else:
            trade.trailing_stop = trade.current_price + self.trail_distance

        trade.status        = TradeStatus.TP1_HIT
        trade.tp_reached_at = datetime.utcnow()

    # ── TP2 ────────────────────────────────────────────────────────────────

    def _check_tp2(self, trade: TradeInfo):
        if len(trade.take_profits) < 2:
            return
        tp2 = trade.take_profits[1]

        hit = (trade.action.upper() == 'BUY'  and trade.current_price >= tp2) or \
              (trade.action.upper() == 'SELL' and trade.current_price <= tp2)
        if not hit:
            return

        logger.info(f"TP2 hit for ticket {trade.ticket} at {trade.current_price} — closing remainder")

        # Read actual volume from MT5 before closing remainder
        mt5_vol = self._get_mt5_position_volume(trade.ticket) or trade.remaining_volume
        if self._partial_close_volume(trade, mt5_vol):
            trade.remaining_volume = 0.0
            trade.status           = TradeStatus.TP2_HIT
            del self.open_trades[trade.ticket]
            logger.info(f"Trade {trade.ticket} fully closed at TP2")

    # ── Trailing stop ──────────────────────────────────────────────────────

    def _update_trailing_stop(self, trade: TradeInfo):
        """Move SL by trail_step whenever price moves trail_distance away."""
        if trade.trailing_stop is None:
            return

        if trade.action.upper() == 'BUY':
            new_trail = trade.current_price - self.trail_distance
            if new_trail >= trade.trailing_stop + self.trail_step:
                if self._move_sl(trade, round(new_trail, 2)):
                    logger.info(
                        f"Trailing SL moved {trade.trailing_stop:.5f} → {new_trail:.5f} "
                        f"for ticket {trade.ticket}"
                    )
                    trade.trailing_stop = new_trail
        else:
            new_trail = trade.current_price + self.trail_distance
            if new_trail <= trade.trailing_stop - self.trail_step:
                if self._move_sl(trade, round(new_trail, 2)):
                    logger.info(
                        f"Trailing SL moved {trade.trailing_stop:.5f} → {new_trail:.5f} "
                        f"for ticket {trade.ticket}"
                    )
                    trade.trailing_stop = new_trail

    # ── MT5 action helpers ─────────────────────────────────────────────────

    def _move_sl(self, trade: TradeInfo, new_sl: float) -> bool:
        # Round to 2 decimal places for XAUUSD
        new_sl = round(new_sl, 2)
        
        # Get current price to check minimum distance
        symbol_info = self.mt5_client.get_symbol_info(trade.symbol)
        if symbol_info:
            current_price = symbol_info['bid'] if trade.action.upper() == 'SELL' else symbol_info['ask']
            min_distance = symbol_info.get('point', 0.01) * 10  # 10 points minimum
            
            if trade.action.upper() == 'BUY':
                if new_sl >= current_price - min_distance:
                    logger.warning(f"SL {new_sl} too close to price {current_price}, skipping")
                    return False
            else:
                if new_sl <= current_price + min_distance:
                    logger.warning(f"SL {new_sl} too close to price {current_price}, skipping")
                    return False
        
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": trade.ticket,
            "symbol":   trade.symbol,
            "sl":       new_sl,
            "tp":       trade.take_profits[-1] if trade.take_profits else 0,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            trade.stop_loss = new_sl
            return True
        logger.error(
            f"Failed to move SL for ticket {trade.ticket}: "
            f"{getattr(result, 'comment', None)} | {mt5.last_error()}"
        )
        return False

    def _partial_close_volume(self, trade: TradeInfo, close_volume: float) -> bool:
        """Close a specific volume of an open position."""
        symbol_info = self.mt5_client.get_symbol_info(trade.symbol)
        if not symbol_info:
            return False

        close_type  = mt5.ORDER_TYPE_SELL if trade.action.upper() == 'BUY' else mt5.ORDER_TYPE_BUY
        close_price = symbol_info['bid'] if close_type == mt5.ORDER_TYPE_SELL else symbol_info['ask']
        close_vol   = self._normalize_volume(close_volume, symbol_info)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       trade.symbol,
            "volume":       close_vol,
            "type":         close_type,
            "position":     trade.ticket,
            "price":        close_price,
            "deviation":    20,
            "magic":        777888,
            "comment":      f"PartialClose-{trade.ticket}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_type(symbol_info),
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Partial close OK: {close_vol} lots for ticket {trade.ticket}")
            return True
        logger.error(
            f"Partial close failed for ticket {trade.ticket}: "
            f"{getattr(result, 'comment', None)} | {mt5.last_error()}"
        )
        return False

    # ── Public helpers (orchestrator / emergency stop) ─────────────────────

    def close_position(self, ticket: int, partial_close: bool = False) -> bool:
        if ticket not in self.open_trades:
            return False
        trade   = self.open_trades[ticket]
        mt5_vol = self._get_mt5_position_volume(ticket) or trade.remaining_volume
        vol     = round(mt5_vol * 0.5, 8) if partial_close else mt5_vol
        ok      = self._partial_close_volume(trade, vol)
        if ok and not partial_close:
            trade.status = TradeStatus.CLOSED
            del self.open_trades[ticket]
        return ok

    def close_all_positions(self, symbol: Optional[str] = None) -> List[int]:
        closed = []
        for ticket in list(self.open_trades.keys()):
            trade = self.open_trades[ticket]
            if symbol and trade.symbol != symbol:
                continue
            if self.close_position(ticket):
                closed.append(ticket)
        logger.info(f"Closed {len(closed)} positions")
        return closed

    # ── Legacy methods called by orchestrator _handle_trade_update ─────────
    # The orchestrator checks trade.status == BE_ACTIVATED / RUNNER_MODE.
    # Since those are now aliases for TP1_HIT, the orchestrator block will
    # trigger but these methods are safe no-ops if already applied.

    def activate_break_even(self, ticket: int) -> bool:
        """No-op: BE is now applied automatically in _check_tp1."""
        logger.debug(f"activate_break_even called for {ticket} — handled internally")
        return True

    def activate_trailing_stop(self, ticket: int, trail_distance: float) -> bool:
        """No-op: trailing is now applied automatically in _update_trailing_stop."""
        logger.debug(f"activate_trailing_stop called for {ticket} — handled internally")
        return True

    # ── Misc ───────────────────────────────────────────────────────────────

    def _increment_signal_entry_count(self, signal_id: str):
        self.signal_entry_count[signal_id] = self.signal_entry_count.get(signal_id, 0) + 1

    def _check_tp_reached(self, trade: TradeInfo) -> bool:
        """Legacy — used by orchestrator."""
        if not trade.take_profits:
            return False
        tp1 = trade.take_profits[0]
        if trade.action.upper() == 'BUY':
            return trade.current_price >= tp1
        return trade.current_price <= tp1

    def _check_runner_condition(self, trade: TradeInfo) -> bool:
        """Legacy — used by orchestrator."""
        if len(trade.take_profits) < 2:
            return False
        tp2 = trade.take_profits[1]
        if trade.action.upper() == 'BUY':
            return trade.current_price >= tp2
        return trade.current_price <= tp2

    def get_open_trades_summary(self) -> dict:
        return {
            'total_positions': len(self.open_trades),
            'total_pl':        sum(t.profit_loss for t in self.open_trades.values()),
            'total_volume':    sum(t.remaining_volume for t in self.open_trades.values()),
            'trades':          [t.to_dict() for t in self.open_trades.values()],
        }