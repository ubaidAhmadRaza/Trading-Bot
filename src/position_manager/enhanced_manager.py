"""
Enhanced Position Manager
Handles:
- Fixed lot size (default 0.29)
- Maximum 15 open positions
- Multiple entries from same signal
- Break-even activation
- Trailing stops for runner mode
"""
import MetaTrader5 as mt5
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, asdict
import json
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeStatus(str, Enum):
    """Trade status enumeration"""
    OPEN = "open"
    BE_ACTIVATED = "be_activated"
    RUNNER_MODE = "runner_mode"
    CLOSED = "closed"
    ERROR = "error"


@dataclass
class TradeInfo:
    """Information about an open trade"""
    ticket: int
    symbol: str
    action: str  # BUY or SELL
    entry_price: float
    current_price: float
    volume: float
    stop_loss: float
    take_profits: List[float]  # List of TP levels
    break_even_price: float
    status: TradeStatus
    opened_at: datetime
    signal_id: str  # Link to source signal
    profit_loss: float
    profit_loss_percent: float
    trailing_stop: Optional[float] = None
    tp_reached_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dict for serialization"""
        d = asdict(self)
        d['status'] = self.status.value
        d['opened_at'] = self.opened_at.isoformat()
        d['tp_reached_at'] = self.tp_reached_at.isoformat() if self.tp_reached_at else None
        return d


class EnhancedPositionManager:
    """
    Manages trading positions with advanced features
    """

    def __init__(self, mt5_client, fixed_lot_size: float = 0.29, max_positions: int = 15):
        self.mt5_client = mt5_client
        self.fixed_lot_size = fixed_lot_size
        self.max_positions = max_positions
        self.open_trades: Dict[int, TradeInfo] = {}  # ticket -> TradeInfo
        self.signal_entry_count: Dict[str, int] = {}  # signal_id -> entry count

    def can_open_new_position(self, signal_id: str) -> Tuple[bool, str]:
        """
        Check if a new position can be opened
        Returns: (can_open, reason)
        """
        # Check max open positions
        if len(self.open_trades) >= self.max_positions:
            return False, f"Max {self.max_positions} positions already open"

        return True, "Can open new position"

    def _normalize_volume(self, requested_volume: float, symbol_info: dict) -> float:
        """Fit requested lot size to the broker's min/max/step constraints."""
        min_volume = symbol_info.get('volume_min') or requested_volume
        max_volume = symbol_info.get('volume_max') or requested_volume
        step = symbol_info.get('volume_step') or 0.01

        volume = max(min_volume, min(requested_volume, max_volume))
        steps = round((volume - min_volume) / step)
        volume = min_volume + (steps * step)
        return round(volume, 8)

    def _get_filling_type(self, symbol_info: dict):
        """Use a broker-supported filling mode where possible."""
        filling_mode = symbol_info.get('filling_mode')
        if filling_mode == mt5.ORDER_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        if filling_mode == mt5.ORDER_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if filling_mode == mt5.ORDER_FILLING_RETURN:
            return mt5.ORDER_FILLING_RETURN
        return mt5.ORDER_FILLING_IOC

    def _extract_position_ticket(self, result, symbol: str, magic: int, comment: str) -> Optional[int]:
        """Resolve the open position ticket after a successful market deal."""
        for attr in ('order', 'deal'):
            ticket = getattr(result, attr, None)
            if ticket:
                positions = mt5.positions_get(ticket=ticket)
                if positions:
                    return positions[0].ticket

        positions = mt5.positions_get(symbol=symbol) or []
        for position in positions:
            if getattr(position, 'magic', None) == magic and getattr(position, 'comment', '') == comment:
                return position.ticket
        if len(positions) == 1:
            return positions[0].ticket
        return None

    def place_entry_order(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profits: List[float],
        signal_id: str
    ) -> Optional[TradeInfo]:
        """
        Place a new entry order with fixed lot size

        Returns:
            TradeInfo if successful, None otherwise
        """
        try:
            # Determine order type
            order_type = mt5.ORDER_TYPE_BUY if action.upper() == 'BUY' else mt5.ORDER_TYPE_SELL

            # Get current market price
            symbol_info = self.mt5_client.get_symbol_info(symbol)
            if not symbol_info:
                logger.error(f"Could not get symbol info for {symbol}")
                return None

            trade_symbol = symbol_info['symbol']
            market_price = symbol_info['ask'] if order_type == mt5.ORDER_TYPE_BUY else symbol_info['bid']
            volume = self._normalize_volume(self.fixed_lot_size, symbol_info)
            magic = 777888
            comment = f"EnhancedTrader-{signal_id}"

            # Prepare order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": trade_symbol,
                "volume": volume,
                "type": order_type,
                "price": market_price,
                "deviation": 20,
                "magic": magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_type(symbol_info),
            }

            # Set stop loss
            if stop_loss:
                request["sl"] = stop_loss

            # For now, set primary TP (will manage partial closes separately)
            if take_profits:
                request["tp"] = take_profits[0]

            # Send order
            result = mt5.order_send(request)

            if result is None:
                logger.error(f"Order send returned None for {symbol}: {mt5.last_error()} | request={request}")
                return None

            logger.info(
                f"Order send result for {trade_symbol}: retcode={getattr(result, 'retcode', None)}, "
                f"comment={getattr(result, 'comment', None)}, order={getattr(result, 'order', None)}, "
                f"deal={getattr(result, 'deal', None)}"
            )

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Order failed for {trade_symbol}: {result.comment} (retcode={result.retcode}) | last_error={mt5.last_error()}")
                return None

            ticket = self._extract_position_ticket(result, trade_symbol, magic, comment)
            if not ticket:
                logger.error(f"Order completed but open position ticket could not be resolved for {trade_symbol}: {result}")
                return None

            # Create TradeInfo
            trade = TradeInfo(
                ticket=ticket,
                symbol=trade_symbol,
                action=action,
                entry_price=market_price,
                current_price=market_price,
                volume=volume,
                stop_loss=stop_loss,
                take_profits=take_profits,
                break_even_price=market_price,
                status=TradeStatus.OPEN,
                opened_at=datetime.utcnow(),
                signal_id=signal_id,
                profit_loss=0.0,
                profit_loss_percent=0.0
            )

            self.open_trades[ticket] = trade
            self._increment_signal_entry_count(signal_id)

            logger.info(f"Order placed: {trade_symbol} {action} Ticket: {ticket}")
            return trade

        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            return None

    def update_positions(self) -> List[TradeInfo]:
        """
        Update all open positions from MT5
        Returns list of updated TradeInfo objects
        """
        try:
            positions = self.mt5_client.get_positions()
            updated_trades = []

            for pos in positions:
                ticket = pos['ticket']
                if ticket not in self.open_trades:
                    continue

                trade = self.open_trades[ticket]
                trade.current_price = pos['price_current']
                trade.profit_loss = pos['profit']

                # Calculate profit/loss percentage
                price_diff = abs(trade.current_price - trade.entry_price)
                if trade.entry_price > 0:
                    trade.profit_loss_percent = (price_diff / trade.entry_price) * 100
                    if trade.action.upper() == 'SELL':
                        trade.profit_loss_percent = -trade.profit_loss_percent

                # Check if TP is reached (runner mode)
                    if trade.status == TradeStatus.OPEN:
                        if self._check_tp_reached(trade):
                            trade.status = TradeStatus.BE_ACTIVATED   # first TP → BE
                            logger.info(f"BE activated for {ticket}")
    
                    elif trade.status == TradeStatus.BE_ACTIVATED:
                        if self._check_runner_condition(trade):        # e.g. 2nd TP hit
                            trade.status = TradeStatus.RUNNER_MODE
                            trade.tp_reached_at = datetime.utcnow()
                            logger.info(f"Runner mode for {ticket}")

                updated_trades.append(trade)

            return updated_trades

        except Exception as e:
            logger.error(f"Error updating positions: {str(e)}")
            return []

    def activate_break_even(self, ticket: int) -> bool:
        """
        Move stop loss to entry price when TP is reached
        """
        try:
            if ticket not in self.open_trades:
                return False

            trade = self.open_trades[ticket]

            # Modify position
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": trade.symbol,
                "sl": trade.entry_price,
                "tp": trade.take_profits[0] if trade.take_profits else trade.entry_price,
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                trade.break_even_price = trade.entry_price
                logger.info(f"Break-even activated for ticket {ticket}")
                return True
            else:
                logger.error(f"Failed to activate BE: {getattr(result, 'comment', None)} | last_error={mt5.last_error()}")
                return False

        except Exception as e:
            logger.error(f"Error activating BE: {str(e)}")
            return False

    def activate_trailing_stop(
        self,
        ticket: int,
        trail_distance: float
    ) -> bool:
        """
        Activate trailing stop for runner mode
        Trails below swing lows (BUY) or above swing highs (SELL)
        """
        try:
            if ticket not in self.open_trades:
                return False

            trade = self.open_trades[ticket]

            # Calculate trailing stop price
            if trade.action.upper() == 'BUY':
                trailing_stop = trade.current_price - trail_distance
            else:
                trailing_stop = trade.current_price + trail_distance

            # Modify position
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": trade.symbol,
                "sl": trailing_stop,
                "tp": trade.take_profits[-1] if trade.take_profits else 0,
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                trade.trailing_stop = trailing_stop
                logger.info(f"Trailing stop activated for ticket {ticket} at {trailing_stop}")
                return True
            else:
                logger.error(f"Failed to activate trailing stop: {getattr(result, 'comment', None)} | last_error={mt5.last_error()}")
                return False

        except Exception as e:
            logger.error(f"Error activating trailing stop: {str(e)}")
            return False

    def close_position(self, ticket: int, partial_close: bool = False) -> bool:
        """
        Close a position fully or partially
        """
        try:
            if ticket not in self.open_trades:
                return False

            trade = self.open_trades[ticket]

            close_volume = self.fixed_lot_size / 2 if partial_close else self.fixed_lot_size

            # Determine close order type
            close_type = mt5.ORDER_TYPE_SELL if trade.action.upper() == 'BUY' else mt5.ORDER_TYPE_BUY

            symbol_info = self.mt5_client.get_symbol_info(trade.symbol)
            if not symbol_info:
                return False

            close_price = symbol_info['bid'] if close_type == mt5.ORDER_TYPE_SELL else symbol_info['ask']
            close_volume = self._normalize_volume(close_volume, symbol_info)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": trade.symbol,
                "volume": close_volume,
                "type": close_type,
                "position": ticket,
                "price": close_price,
                "deviation": 20,
                "magic": 777888,
                "comment": f"Close-{ticket}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_type(symbol_info),
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                if not partial_close:
                    trade.status = TradeStatus.CLOSED
                    del self.open_trades[ticket]
                logger.info(f"Position {ticket} closed successfully")
                return True
            else:
                logger.error(f"Failed to close position: {getattr(result, 'comment', None)} | last_error={mt5.last_error()}")
                return False

        except Exception as e:
            logger.error(f"Error closing position: {str(e)}")
            return False

    def close_all_positions(self, symbol: Optional[str] = None) -> List[int]:
        """
        Close all open positions, optionally filtered by symbol
        Returns list of closed ticket numbers
        """
        closed = []
        try:
            tickets_to_close = list(self.open_trades.keys())

            for ticket in tickets_to_close:
                trade = self.open_trades[ticket]

                if symbol and trade.symbol != symbol:
                    continue

                if self.close_position(ticket):
                    closed.append(ticket)

            logger.info(f"Closed {len(closed)} positions")
            return closed

        except Exception as e:
            logger.error(f"Error closing all positions: {str(e)}")
            return closed

    def _check_tp_reached(self, trade: TradeInfo) -> bool:
        """Check if any TP level is reached"""
        if not trade.take_profits:
            return False

        for tp in trade.take_profits:
            if trade.action.upper() == 'BUY':
                if trade.current_price >= tp:
                    return True
            else:  # SELL
                if trade.current_price <= tp:
                    return True

        return False

    def _check_be_activation(self, trade: TradeInfo) -> bool:
        """
        Check if break-even should be activated
        Typically when first TP is reached
        """
        if not trade.take_profits:
            return False

        return self._check_tp_reached(trade)

    def _increment_signal_entry_count(self, signal_id: str):
        """Track number of entries for a signal"""
        if signal_id not in self.signal_entry_count:
            self.signal_entry_count[signal_id] = 0
        self.signal_entry_count[signal_id] += 1

    def get_open_trades_summary(self) -> Dict:
        """Get summary of all open trades"""
        total_pl = sum(t.profit_loss for t in self.open_trades.values())
        total_volume = sum(t.volume for t in self.open_trades.values())

        return {
            'total_positions': len(self.open_trades),
            'total_pl': total_pl,
            'total_volume': total_volume,
            'trades': [t.to_dict() for t in self.open_trades.values()]
        }
