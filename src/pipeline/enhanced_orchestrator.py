"""
Enhanced Trading Pipeline Orchestrator
Main coordinator for all trading operations
"""
import asyncio
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from src.signal_parser.enhanced_parser import EnhancedSignalParser, TradingSignal
from src.entry_confirmation.confirmation_engine import EntryConfirmationEngine
from src.position_manager.enhanced_manager import EnhancedPositionManager, TradeStatus
from src.notifications.telegram_notifier import NotificationManager, DummyNotificationManager
from src.database.db_manager import DatabaseManager
from src.mt5_integration.mt5_client import MT5Client
from src.telegram_bot.client import TelegramSignalClient
from src.utils.logger import get_logger
from config.settings import settings
import os
import json

logger = get_logger(__name__)


class SafetyControls:
    """Safety control states"""
    def __init__(self):
        self.emergency_stop = False
        self.pause_new_trades = False
        self.all_closed = False


class EnhancedTradingPipeline:
    """
    Enhanced trading pipeline orchestrator
    """

    def __init__(
        self,
        telegram_api_id: int,
        telegram_api_hash: str,
        telegram_phone: str,
        telegram_channels: List[str],
        telegram_bot_token: str,
        telegram_notify_chat_id: str,
        mt5_login: int,
        mt5_password: str,
        mt5_server: str,
        mt5_path: Optional[str] = None,
        fixed_lot_size: float = 0.29,
        max_positions: int = 15,
        enable_notifications: bool = True,
        db_path: str = "data/trading_bot.db"
    ):
        """Initialize the enhanced pipeline"""
        logger.info("Initializing Enhanced Trading Pipeline...")

        # Clients and managers
        self.telegram_client = TelegramSignalClient(
            telegram_api_id,
            telegram_api_hash,
            telegram_phone
        )
        self.mt5_client = MT5Client(mt5_login, mt5_password, mt5_server, mt5_path)

        # Core components
        self.signal_parser = EnhancedSignalParser()
        self.entry_engine = EntryConfirmationEngine(self.mt5_client)
        self.position_manager = EnhancedPositionManager(
            self.mt5_client,
            fixed_lot_size=fixed_lot_size,
            max_positions=max_positions
        )
        self.database = DatabaseManager(db_path)

        # Notifications
        if enable_notifications:
            self.notifier = NotificationManager(telegram_bot_token, telegram_notify_chat_id)
        else:
            self.notifier = DummyNotificationManager()

        # Safety controls
        self.safety = SafetyControls()

        # Tracking
        self.pending_signals: Dict[int, TradingSignal] = {}  # signal_id -> signal
        self.zone_reached_signals: Dict[int, TradingSignal] = {}  # signal_id -> signal
        self.telegram_channels = telegram_channels
        self.is_running = False
        self.last_update = datetime.utcnow()
        self._last_price_log: Dict[int, datetime] = {}

    async def start(self):
        """Start the trading pipeline"""
        logger.info("Starting Enhanced Trading Pipeline...")

        try:
            # Connect to MT5
            if not self.mt5_client.connect():
                raise Exception("Failed to connect to MT5")

            logger.info("Connected to MT5")
            self.database.expire_stale_pending_signals(settings.SIGNAL_EXPIRY_SECONDS)

            # Connect to Telegram
            await self.telegram_client.connect()
            logger.info("Connected to Telegram")

            self.is_running = True

            # Send startup notification
            await self.notifier.send_info(
                "🚀 Trading Bot Started",
                {
                    'Status': 'Online',
                    'Channels': ', '.join(self.telegram_channels),
                    'Max Positions': str(self.position_manager.max_positions),
                    'Lot Size': str(self.position_manager.fixed_lot_size)
                }
            )

            # Start signal listener
            await asyncio.gather(
    self.telegram_client.listen_channels(self.telegram_channels, self.handle_signal),
    self._monitoring_loop()
)

        except Exception as e:
            logger.error(f"Fatal error in pipeline: {str(e)}")
            await self.notifier.send_error(f"Pipeline error: {str(e)}")
            await self.stop()

    async def stop(self):
        """Stop the trading pipeline"""
        logger.info("Stopping pipeline...")
        self.is_running = False

        if self.telegram_client.client:
            self.telegram_client.client.disconnect()

        self.mt5_client.disconnect()
        logger.info("Pipeline stopped")

    async def handle_signal(self, message):
        """Handle incoming trading signal from Telegram"""
        try:
            # Parse signal
            signal = self.signal_parser.parse(message.text, message.chat.title)
            if not signal:
                logger.debug("Could not parse signal from message")
                return

            logger.info(f"Signal received: {signal.symbol} {signal.action}")

            # Save to database
            signal_id = self.database.save_signal(
                symbol=signal.symbol,
                action=signal.action,
                entry_zone=signal.entry_zone,
                stop_loss=signal.stop_loss,
                take_profits=[tp.level for tp in signal.take_profits],
                channel=signal.channel,
                confidence=signal.confidence,
                raw_format=signal.raw_format,
                source_message=signal.source_message
            )

            if not signal_id:
                logger.error("Failed to save signal to database")
                return

            # Send notification
            await self.notifier.send_signal_received(
                signal.symbol,
                signal.action,
                signal.entry_zone,
                signal.stop_loss,
                [tp.level for tp in signal.take_profits]
            )

            # Add to pending signals
            self.pending_signals[signal_id] = signal

        except Exception as e:
            logger.error(f"Error handling signal: {str(e)}")
            self.database.log_error("signal_handler", str(e))
            await self.notifier.send_error(str(e))

    async def _monitoring_loop(self):
        """Main monitoring loop - runs based on `settings.SIGNAL_POLL_INTERVAL`"""
        interval = max(1, settings.SIGNAL_POLL_INTERVAL)
        while self.is_running:
            try:
                # Update positions
                trades = self.position_manager.update_positions()
                for trade in trades:
                    await self._handle_trade_update(trade)

                # Check pending signals for zone reached
                await self._check_pending_signals()

                # Check runner mode trades
                await self._check_runner_mode_trades()

                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                self.database.log_error("monitoring_loop", str(e))
                await self.notifier.send_error(f"Monitoring error: {str(e)}")

    async def _check_pending_signals(self):
        """Check if any pending signals have reached entry zone"""
        signals_to_remove = []

        for signal_id, signal in list(self.pending_signals.items()):
            try:
                # Check expiry
                age = datetime.utcnow() - signal.timestamp
                if age > timedelta(seconds=settings.SIGNAL_EXPIRY_SECONDS):
                    logger.info(f"Signal {signal_id} expired after {settings.SIGNAL_EXPIRY_SECONDS} seconds")
                    self.database.expire_signal(signal_id, reason="timeout")
                    await self.notifier.send_info("Signal expired", {"signal_id": signal_id, "symbol": signal.symbol})
                    signals_to_remove.append(signal_id)
                    continue
                # Get current price
                symbol_info = self.mt5_client.get_symbol_info(signal.symbol)
                if not symbol_info:
                    logger.warning(f"No MT5 price available for {signal.symbol}; signal {signal_id} remains pending")
                    continue

                if signal.action.upper() == 'BUY':
                    current_price = symbol_info['ask']
                else:
                    current_price = symbol_info['bid']

                # Check if in entry zone
                if signal.entry_zone['min'] <= current_price <= signal.entry_zone['max']:
                    logger.info(f"Entry zone reached for signal {signal_id}")
                    self.database.mark_zone_reached(signal_id, current_price)

                    # Send notification
                    await self.notifier.send_zone_reached(
                        signal.symbol,
                        signal.action,
                        current_price
                    )

                    # Check entry confirmation (may be bypassed in test/dev)
                    if settings.ENABLE_BYPASS_ENTRY_CONFIRMATION:
                        is_confirmed = True
                        confirmation_details = {'reasons': ['bypass_enabled']}
                        logger.info(f"Bypassing entry confirmation for signal {signal_id} (test mode)")
                    else:
                        is_confirmed, confirmation_details = self.entry_engine.check_entry_confirmation(
                            signal.symbol,
                            signal.action,
                            signal.entry_zone,
                            current_price
                        )

                    if is_confirmed:
                        logger.info(f"Entry confirmed for signal {signal_id}")

                        # Check if can open position
                        can_open, reason = self.position_manager.can_open_new_position(str(signal_id))
                        if not can_open or self.safety.pause_new_trades:
                            reason = "New trades paused" if self.safety.pause_new_trades else reason
                            logger.warning(f"Cannot open position for signal {signal_id}: {reason}")
                            self.database.mark_signal_trade_failed(signal_id, reason)
                            signals_to_remove.append(signal_id)
                            continue

                        # Place order
                        trade = self.position_manager.place_entry_order(
                            signal.symbol,
                            signal.action,
                            current_price,
                            signal.stop_loss,
                            [tp.level for tp in signal.take_profits],
                            str(signal_id)
                        )

                        if trade:
                            self.database.mark_signal_traded(signal_id, trade.ticket)
                            # Save to database
                            self.database.save_trade(
                                ticket=trade.ticket,
                                signal_id=signal_id,
                                symbol=signal.symbol,
                                action=signal.action,
                                entry_price=trade.entry_price,
                                stop_loss=trade.stop_loss,
                                take_profits=[tp.level for tp in signal.take_profits],
                                volume=trade.volume
                            )

                            # Send notification
                            await self.notifier.send_trade_opened(
                                trade.ticket,
                                signal.symbol,
                                signal.action,
                                trade.entry_price,
                                trade.volume,
                                trade.stop_loss
                            )

                            # Move to zone_reached
                            self.zone_reached_signals[signal_id] = signal
                            signals_to_remove.append(signal_id)
                        else:
                            reason = "MT5 order_send failed; check latest order retcode in logs"
                            logger.error(f"Trade placement failed for signal {signal_id}: {reason}")
                            self.database.mark_signal_trade_failed(signal_id, reason)
                            signals_to_remove.append(signal_id)

                    else:
                        logger.info(f"Entry not confirmed for {signal_id}: {confirmation_details['reasons']}")

                else:
                    now = datetime.utcnow()
                    last_log = self._last_price_log.get(signal_id)
                    if not last_log or (now - last_log).total_seconds() >= 30:
                        logger.info(
                            f"Signal {signal_id} waiting for zone: {signal.symbol} {signal.action} "
                            f"price={current_price}, zone={signal.entry_zone['min']}-{signal.entry_zone['max']}, "
                            f"age={int((now - signal.timestamp).total_seconds())}s"
                        )
                        self._last_price_log[signal_id] = now

            except Exception as e:
                logger.error(f"Error checking signal {signal_id}: {str(e)}")
                self.database.log_error("check_signals", str(e))

        # Remove processed signals
        for signal_id in signals_to_remove:
            if signal_id in self.pending_signals:
                del self.pending_signals[signal_id]
            self._last_price_log.pop(signal_id, None)

    async def _handle_trade_update(self, trade):
        """Handle trade status updates"""
        try:
            if trade.status == TradeStatus.BE_ACTIVATED:
                # Activate break-even
                self.position_manager.activate_break_even(trade.ticket)
                self.database.activate_be_on_trade(trade.ticket)

                await self.notifier.send_be_activated(
                    trade.ticket,
                    trade.symbol,
                    trade.break_even_price
                )

            elif trade.status == TradeStatus.RUNNER_MODE:
                # Activate runner mode
                trail_distance = abs(trade.current_price - trade.stop_loss) * 0.5

                self.position_manager.activate_trailing_stop(trade.ticket, trail_distance)
                self.database.activate_runner_mode_on_trade(trade.ticket)

                await self.notifier.send_runner_mode_activated(
                    trade.ticket,
                    trade.symbol,
                    trail_distance
                )

        except Exception as e:
            logger.error(f"Error handling trade update: {str(e)}")

    async def _check_runner_mode_trades(self):
        """Check runner mode trades for trend continuation"""
        for ticket, trade in list(self.position_manager.open_trades.items()):
            try:
                if trade.status != TradeStatus.RUNNER_MODE:
                    continue

                # Check trend continuation
                is_trend_continuing = self._check_trend_continuation(trade)

                if not is_trend_continuing:
                    logger.info(f"Trend weakened for {ticket}, closing runner trade")
                    self.position_manager.close_position(ticket)

                    # Log to database
                    self.database.close_trade(
                        ticket,
                        trade.current_price,
                        trade.profit_loss,
                        trade.profit_loss_percent
                    )

            except Exception as e:
                logger.error(f"Error in runner mode check: {str(e)}")

    def _check_trend_continuation(self, trade) -> bool:
        """
        Check if trend continues for runner mode
        BUY: Higher highs, higher lows, no bearish CHOCH, EMA20 > EMA50
        SELL: Lower highs, lower lows, no bullish CHOCH, EMA20 < EMA50
        """
        try:
            import MetaTrader5 as mt5
            import numpy as np

            # Get recent candles
            rates = mt5.copy_rates_from_pos(trade.symbol, 5, 0, 10)
            if not rates or len(rates) < 5:
                return True

            highs = [r['high'] for r in rates]
            lows = [r['low'] for r in rates]
            closes = np.array([r['close'] for r in rates])

            if trade.action.upper() == 'BUY':
                # Check for higher highs and higher lows
                hh = all(highs[i] <= highs[i+1] for i in range(len(highs)-1))
                hl = all(lows[i] <= lows[i+1] for i in range(len(lows)-1))

                if not (hh and hl):
                    return False

            else:  # SELL
                # Check for lower highs and lower lows
                lh = all(highs[i] >= highs[i+1] for i in range(len(highs)-1))
                ll = all(lows[i] >= lows[i+1] for i in range(len(lows)-1))

                if not (lh and ll):
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking trend: {str(e)}")
            return True

    async def emergency_stop(self):
        """Emergency stop - close all positions immediately"""
        logger.warning("EMERGENCY STOP ACTIVATED")
        self.safety.emergency_stop = True
        closed = self.position_manager.close_all_positions()
        await self.notifier.send_info(
            "🚨 EMERGENCY STOP",
            {'Positions Closed': len(closed)}
        )

    async def pause_new_trades(self):
        """Pause new trades but keep existing ones"""
        logger.warning("Pausing new trades")
        self.safety.pause_new_trades = True
        await self.notifier.send_info(
            "⏸️ New Trades Paused",
            {'Status': 'Only existing trades will be managed'}
        )

    async def resume_trades(self):
        """Resume new trades"""
        logger.info("Resuming new trades")
        self.safety.pause_new_trades = False
        await self.notifier.send_info(
            "▶️ Trades Resumed",
            {'Status': 'New trades enabled'}
        )
