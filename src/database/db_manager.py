"""
Database Manager - JSON-based persistence
Stores:
- All signals
- All trades
- Trade modifications
- All errors
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """
    JSON-based database manager for trading data
    """

    def __init__(self, db_path: str = "data/trading_bot.db"):
        """Initialize database directory and files"""
        self.db_path = Path(db_path)
        self.data_dir = self.db_path.parent
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize collections
        self.signals_file = self.data_dir / "signals.json"
        self.trades_file = self.data_dir / "trades.json"
        self.modifications_file = self.data_dir / "modifications.json"
        self.errors_file = self.data_dir / "errors.json"

        # Create files if not exist
        for file in [self.signals_file, self.trades_file, self.modifications_file, self.errors_file]:
            if not file.exists():
                file.write_text(json.dumps([]))

    def _read_file(self, filepath: Path) -> list:
        """Read JSON file safely"""
        try:
            if filepath.exists():
                return json.loads(filepath.read_text())
            return []
        except Exception as e:
            logger.error(f"Error reading {filepath}: {e}")
            return []

    def _write_file(self, filepath: Path, data: list):
        """Write JSON file safely"""
        try:
            filepath.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.error(f"Error writing {filepath}: {e}")

    def save_signal(
        self,
        symbol: str,
        action: str,
        entry_zone: dict,
        stop_loss: float,
        take_profits: list,
        channel: str,
        confidence: float = 1.0,
        raw_format: int = 1,
        source_message: str = None
    ) -> Optional[int]:
        """Save signal to database"""
        try:
            signals = self._read_file(self.signals_file)
            signal_id = max([s.get('id', 0) for s in signals], default=0) + 1

            signal = {
                'id': signal_id,
                'symbol': symbol,
                'action': action,
                'entry_zone_min': entry_zone['min'],
                'entry_zone_max': entry_zone['max'],
                'stop_loss': stop_loss,
                'take_profits': take_profits,
                'channel': channel,
                'confidence': confidence,
                'raw_format': raw_format,
                'source_message': source_message,
                'received_at': datetime.utcnow().isoformat(),
                'zone_reached_at': None,
                'trade_ticket': None,
                'status': 'pending'
            }

            signals.append(signal)
            self._write_file(self.signals_file, signals)
            logger.info(f"Signal saved to database: ID={signal_id}")
            return signal_id

        except Exception as e:
            logger.error(f"Error saving signal: {str(e)}")
            return None

    def expire_signal(self, signal_id: int, reason: str = None) -> bool:
        """Mark a pending signal as expired with optional reason"""
        try:
            signals = self._read_file(self.signals_file)

            for signal in signals:
                if signal.get('id') == signal_id:
                    signal['status'] = 'expired'
                    signal['expired_at'] = datetime.utcnow().isoformat()
                    signal['expiry_reason'] = reason
                    break

            self._write_file(self.signals_file, signals)
            logger.info(f"Signal marked expired: ID={signal_id}, reason={reason}")
            return True

        except Exception as e:
            logger.error(f"Error expiring signal: {str(e)}")
            return False

    def mark_zone_reached(self, signal_id: int, current_price: float) -> bool:
        """Mark a signal as having reached its entry zone."""
        try:
            signals = self._read_file(self.signals_file)

            for signal in signals:
                if signal.get('id') == signal_id:
                    signal['status'] = 'zone_reached'
                    signal['zone_reached_at'] = datetime.utcnow().isoformat()
                    signal['zone_reached_price'] = current_price
                    break

            self._write_file(self.signals_file, signals)
            logger.info(f"Signal zone reached: ID={signal_id}, price={current_price}")
            return True

        except Exception as e:
            logger.error(f"Error marking zone reached: {str(e)}")
            return False

    def mark_signal_traded(self, signal_id: int, ticket: int) -> bool:
        """Mark a signal as traded and store the MT5 ticket."""
        try:
            signals = self._read_file(self.signals_file)

            for signal in signals:
                if signal.get('id') == signal_id:
                    signal['status'] = 'traded'
                    signal['trade_ticket'] = ticket
                    signal['traded_at'] = datetime.utcnow().isoformat()
                    break

            self._write_file(self.signals_file, signals)
            logger.info(f"Signal marked traded: ID={signal_id}, ticket={ticket}")
            return True

        except Exception as e:
            logger.error(f"Error marking signal traded: {str(e)}")
            return False

    def mark_signal_trade_failed(self, signal_id: int, reason: str) -> bool:
        """Mark a signal as failed after an entry attempt."""
        try:
            signals = self._read_file(self.signals_file)

            for signal in signals:
                if signal.get('id') == signal_id:
                    signal['status'] = 'trade_failed'
                    signal['failed_at'] = datetime.utcnow().isoformat()
                    signal['failure_reason'] = reason
                    break

            self._write_file(self.signals_file, signals)
            logger.info(f"Signal marked trade_failed: ID={signal_id}, reason={reason}")
            return True

        except Exception as e:
            logger.error(f"Error marking signal trade failed: {str(e)}")
            return False

    def expire_stale_pending_signals(self, expiry_seconds: int) -> int:
        """Expire persisted pending signals that are older than the active timeout."""
        try:
            signals = self._read_file(self.signals_file)
            now = datetime.utcnow()
            expired_count = 0

            for signal in signals:
                if signal.get('status') != 'pending':
                    continue

                received_at = signal.get('received_at')
                if not received_at:
                    continue

                try:
                    received = datetime.fromisoformat(received_at)
                except ValueError:
                    continue

                if now - received > timedelta(seconds=expiry_seconds):
                    signal['status'] = 'expired'
                    signal['expired_at'] = now.isoformat()
                    signal['expiry_reason'] = 'timeout_after_restart'
                    expired_count += 1

            if expired_count:
                self._write_file(self.signals_file, signals)
                logger.info(f"Expired {expired_count} stale pending signals")

            return expired_count

        except Exception as e:
            logger.error(f"Error expiring stale pending signals: {str(e)}")
            return 0

    def save_trade(
        self,
        ticket: int,
        signal_id: int,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profits: list,
        volume: float
    ) -> bool:
        """Save trade to database"""
        try:
            trades = self._read_file(self.trades_file)

            trade = {
                'ticket': ticket,
                'signal_id': signal_id,
                'symbol': symbol,
                'action': action,
                'entry_price': entry_price,
                'exit_price': None,
                'stop_loss': stop_loss,
                'take_profits': take_profits,
                'volume': volume,
                'opened_at': datetime.utcnow().isoformat(),
                'closed_at': None,
                'status': 'open',
                'profit_loss': None,
                'profit_loss_percent': None,
                'be_activated': False,
                'runner_mode': False,
                'notes': ''
            }

            trades.append(trade)
            self._write_file(self.trades_file, trades)
            logger.info(f"Trade saved to database: Ticket={ticket}")
            return True

        except Exception as e:
            logger.error(f"Error saving trade: {str(e)}")
            return False

    def close_trade(
        self,
        ticket: int,
        exit_price: float,
        profit_loss: float,
        profit_loss_percent: float
    ) -> bool:
        """Close trade in database"""
        try:
            trades = self._read_file(self.trades_file)

            for trade in trades:
                if trade['ticket'] == ticket:
                    trade['exit_price'] = exit_price
                    trade['profit_loss'] = profit_loss
                    trade['profit_loss_percent'] = profit_loss_percent
                    trade['closed_at'] = datetime.utcnow().isoformat()
                    trade['status'] = 'closed'
                    break

            self._write_file(self.trades_file, trades)
            logger.info(f"Trade closed in database: Ticket={ticket}")
            return True

        except Exception as e:
            logger.error(f"Error closing trade: {str(e)}")
            return False

    def record_modification(
        self,
        ticket: int,
        modification_type: str,
        old_value: Optional[float] = None,
        new_value: Optional[float] = None,
        reason: str = None
    ) -> bool:
        """Record trade modification"""
        try:
            modifications = self._read_file(self.modifications_file)

            mod = {
                'ticket': ticket,
                'modification_type': modification_type,
                'old_value': old_value,
                'new_value': new_value,
                'reason': reason,
                'modified_at': datetime.utcnow().isoformat()
            }

            modifications.append(mod)
            self._write_file(self.modifications_file, modifications)
            logger.info(f"Modification recorded: Ticket={ticket}, Type={modification_type}")
            return True

        except Exception as e:
            logger.error(f"Error recording modification: {str(e)}")
            return False

    def log_error(
        self,
        error_type: str,
        error_message: str,
        context: str = None
    ) -> bool:
        """Log error to database"""
        try:
            errors = self._read_file(self.errors_file)

            error_log = {
                'error_type': error_type,
                'error_message': error_message,
                'context': context,
                'occurred_at': datetime.utcnow().isoformat()
            }

            errors.append(error_log)
            self._write_file(self.errors_file, errors)
            return True

        except Exception as e:
            logger.error(f"Error logging error: {str(e)}")
            return False

    def activate_be_on_trade(self, ticket: int) -> bool:
        """Mark BE as activated for trade"""
        try:
            trades = self._read_file(self.trades_file)

            for trade in trades:
                if trade['ticket'] == ticket:
                    trade['be_activated'] = True
                    break

            self._write_file(self.trades_file, trades)
            return True

        except Exception as e:
            logger.error(f"Error updating BE status: {str(e)}")
            return False

    def activate_runner_mode_on_trade(self, ticket: int) -> bool:
        """Mark runner mode as activated for trade"""
        try:
            trades = self._read_file(self.trades_file)

            for trade in trades:
                if trade['ticket'] == ticket:
                    trade['runner_mode'] = True
                    break

            self._write_file(self.trades_file, trades)
            return True

        except Exception as e:
            logger.error(f"Error updating runner mode status: {str(e)}")
            return False

    def get_signal_by_id(self, signal_id: int) -> Optional[dict]:
        """Get signal details by ID"""
        try:
            signals = self._read_file(self.signals_file)

            for signal in signals:
                if signal['id'] == signal_id:
                    return {
                        'id': signal['id'],
                        'symbol': signal['symbol'],
                        'action': signal['action'],
                        'entry_zone': {'min': signal['entry_zone_min'], 'max': signal['entry_zone_max']},
                        'stop_loss': signal['stop_loss'],
                        'received_at': signal['received_at']
                    }

            return None

        except Exception as e:
            logger.error(f"Error retrieving signal: {str(e)}")
            return None

    def get_open_trades(self) -> List[dict]:
        """Get all open trades"""
        try:
            trades = self._read_file(self.trades_file)
            return [
                {
                    'ticket': t['ticket'],
                    'symbol': t['symbol'],
                    'action': t['action'],
                    'entry_price': t['entry_price'],
                    'opened_at': t['opened_at']
                }
                for t in trades if t['status'] == 'open'
            ]

        except Exception as e:
            logger.error(f"Error retrieving trades: {str(e)}")
            return []

    def get_trade_stats(self) -> dict:
        """Get trading statistics"""
        try:
            trades = self._read_file(self.trades_file)
            closed_trades = [t for t in trades if t['status'] == 'closed']

            total_profit = sum(t.get('profit_loss', 0) or 0 for t in closed_trades)
            winning_trades = len([t for t in closed_trades if (t.get('profit_loss') or 0) > 0])
            losing_trades = len([t for t in closed_trades if (t.get('profit_loss') or 0) < 0])
            open_trades = len([t for t in trades if t['status'] == 'open'])

            return {
                'total_trades': len(trades),
                'open_trades': open_trades,
                'closed_trades': len(closed_trades),
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'total_profit': total_profit,
                'win_rate': (winning_trades / len(closed_trades) * 100) if closed_trades else 0
            }

        except Exception as e:
            logger.error(f"Error getting stats: {str(e)}")
            return {}

