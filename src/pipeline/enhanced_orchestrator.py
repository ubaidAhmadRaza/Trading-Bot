"""
Enhanced Trading Pipeline Orchestrator
Main coordinator for all trading operations

Signal parsing strategy:
  1. EnhancedSignalParser  (regex, zero latency, zero cost)
  2. OpenRouterSignalParser (Kimi via OpenRouter — fallback for unstructured messages)
     Activated when OPENROUTER_API_KEY is set and ENABLE_OPENROUTER_PARSER=true
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
        fixed_lot_size: float = None,
        max_positions: int = None,
        enable_notifications: bool = True,
        db_path: str = "data/trading_bot.db"
    ):
        logger.info("Initializing Enhanced Trading Pipeline...")

        self.telegram_client = TelegramSignalClient(
            telegram_api_id,
            telegram_api_hash,
            telegram_phone
        )
        self.mt5_client = MT5Client(mt5_login, mt5_password, mt5_server, mt5_path)

        # Signal parsers
        self.signal_parser = EnhancedSignalParser()

        self._openrouter_parser = None
        if settings.ENABLE_OPENROUTER_PARSER and settings.OPENROUTER_API_KEY:
            try:
                from src.signal_parser.openrouter_parser import OpenRouterSignalParser
                self._openrouter_parser = OpenRouterSignalParser(
                    api_key=settings.OPENROUTER_API_KEY,
                    model=settings.OPENROUTER_MODEL,
                    timeout=settings.OPENROUTER_TIMEOUT,
                )
                logger.info(f"✅ OpenRouter/Kimi fallback parser enabled (model={settings.OPENROUTER_MODEL})")
            except Exception as e:
                logger.warning(f"Could not initialise OpenRouter parser: {e}")
        elif settings.ENABLE_OPENROUTER_PARSER and not settings.OPENROUTER_API_KEY:
            logger.warning("ENABLE_OPENROUTER_PARSER=true but OPENROUTER_API_KEY is not set — fallback disabled")

        self.entry_engine = EntryConfirmationEngine(self.mt5_client)
        
        # Use settings.FIXED_LOT_SIZE if no override provided
        if fixed_lot_size is None:
            fixed_lot_size = getattr(settings, 'FIXED_LOT_SIZE', 0.29)
        
        self.position_manager = EnhancedPositionManager(
            self.mt5_client,
            fixed_lot_size=fixed_lot_size,
            max_positions=max_positions
        )
        self.database = DatabaseManager(db_path)

        if enable_notifications:
            self.notifier = NotificationManager(telegram_bot_token, telegram_notify_chat_id)
        else:
            self.notifier = DummyNotificationManager()

        self.safety = SafetyControls()

        self.pending_signals: Dict[int, TradingSignal] = {}
        self.zone_reached_signals: Dict[int, TradingSignal] = {}
        self.telegram_channels = telegram_channels
        self.is_running = False
        self.last_update = datetime.utcnow()
        self._last_price_log: Dict[int, datetime] = {}

    # ── Parser helper ──────────────────────────────────────────────────────

    def _parse_signal(self, message_text: str, channel: str):
        

        if self._openrouter_parser:
            logger.info("Regex parser found no signal — trying OpenRouter/Kimi fallback")
            try:
                signal = self._openrouter_parser.parse(message_text, channel)
                if signal:
                    logger.info(
                        f"OpenRouter/Kimi produced signal: {signal.symbol} {signal.action} "
                        f"[format={signal.raw_format}]"
                    )
                else:
                    logger.info("OpenRouter/Kimi returned no signal")
            except Exception as e:
                logger.error(f"OpenRouter/Kimi parse error: {str(e)}")
        return signal

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self):
        logger.info("Starting Enhanced Trading Pipeline...")

        try:
            if not self.mt5_client.connect():
                raise Exception("Failed to connect to MT5")

            logger.info("Connected to MT5")
            self.database.expire_stale_pending_signals(settings.SIGNAL_EXPIRY_SECONDS)

            await self.telegram_client.connect()
            logger.info("Connected to Telegram")

            self.is_running = True

            await self.notifier.send_info(
                "🚀 Trading Bot Started",
                {
                    'Status': 'Online',
                    'Channels': ', '.join(self.telegram_channels),
                    'Max Positions': str(self.position_manager.max_positions),
                    'Lot Size': str(self.position_manager.fixed_lot_size),
                    'Trades Per Signal': str(settings.TRADES_PER_SIGNAL),
                    'AI Fallback': 'Kimi (OpenRouter)' if self._openrouter_parser else 'Disabled',
                }
            )

            await asyncio.gather(
                self.telegram_client.listen_channels(self.telegram_channels, self.handle_signal),
                self._monitoring_loop()
            )

        except Exception as e:
            logger.error(f"Fatal error in pipeline: {str(e)}")
            await self.notifier.send_error(f"Pipeline error: {str(e)}")
            await self.stop()

    async def stop(self):
        logger.info("Stopping pipeline...")
        self.is_running = False

        if self.telegram_client.client:
            self.telegram_client.client.disconnect()

        self.mt5_client.disconnect()
        logger.info("Pipeline stopped")

    # ── Signal handler ─────────────────────────────────────────────────────

    async def handle_signal(self, message):
        try:
            # Safe channel name extraction
            try:
                channel_name = message.chat.title
            except Exception:
                channel_name = str(getattr(message, 'chat_id', 'unknown'))

            print(f"DEBUG handle_signal: channel={channel_name}, text={message.text[:100] if message.text else 'None'}")

            signal = self._parse_signal(message.text, channel_name)
            if not signal:
                print("DEBUG handle_signal: no signal parsed")
                return
            
            allowed = getattr(settings, 'ALLOWED_SYMBOLS', None)
            if allowed and signal.symbol.upper() not in [s.upper() for s in allowed]:
                print(f"DEBUG handle_signal: {signal.symbol} blocked by ALLOWED_SYMBOLS filter")
                return
            
            print(f"DEBUG handle_signal: signal OK - {signal.symbol} {signal.action}")

            logger.info(
                f"Signal received [{signal.raw_format}]: "
                f"{signal.symbol} {signal.action} zone={signal.entry_zone}"
            )

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
                print("DEBUG handle_signal: failed to save signal")
                return

            await self.notifier.send_signal_received(
                signal.symbol,
                signal.action,
                signal.entry_zone,
                signal.stop_loss,
                [tp.level for tp in signal.take_profits]
            )

            self.pending_signals[signal_id] = signal
            print(f"DEBUG handle_signal: signal saved, ID={signal_id}")

        except Exception as e:
            print(f"DEBUG handle_signal ERROR: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"Error handling signal: {str(e)}")
            self.database.log_error("signal_handler", str(e))
            await self.notifier.send_error(str(e))

    # ── Monitoring loop ────────────────────────────────────────────────────

    async def _monitoring_loop(self):
        interval = max(1, settings.SIGNAL_POLL_INTERVAL)
        while self.is_running:
            try:
                trades = self.position_manager.update_positions()
                for trade in trades:
                    await self._handle_trade_update(trade)

                await self._check_pending_signals()
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
                    logger.info(f"Signal {signal_id} expired after {settings.SIGNAL_EXPIRY_SECONDS}s")
                    self.database.expire_signal(signal_id, reason="timeout")
                    await self.notifier.send_info("Signal expired", {"signal_id": signal_id, "symbol": signal.symbol})
                    signals_to_remove.append(signal_id)
                    continue

                # Get current price
                symbol_info = self.mt5_client.get_symbol_info(signal.symbol)
                if not symbol_info:
                    logger.warning(f"No MT5 price for {signal.symbol}; signal {signal_id} remains pending")
                    continue

                current_price = symbol_info['ask'] if signal.action.upper() == 'BUY' else symbol_info['bid']

                # Build effective zone — single-price entries get a 0.05% execution tolerance
                zone_min = signal.entry_zone['min']
                zone_max = signal.entry_zone['max']
                if zone_min == zone_max:
                    tolerance = zone_min * 0.0005
                    zone_min -= tolerance
                    zone_max += tolerance

                # Check if price is in entry zone
                if zone_min <= current_price <= zone_max:
                    logger.info(f"Entry zone reached for signal {signal_id}")
                    self.database.mark_zone_reached(signal_id, current_price)
                    await self.notifier.send_zone_reached(signal.symbol, signal.action, current_price)

                    # Entry confirmation
                    if settings.ENABLE_BYPASS_ENTRY_CONFIRMATION:
                        is_confirmed = True
                        confirmation_details = {'reasons': ['bypass_enabled']}
                        logger.info(f"Bypassing entry confirmation for signal {signal_id} (test mode)")
                    else:
                        is_confirmed, confirmation_details = self.entry_engine.check_entry_confirmation(
                            signal.symbol, signal.action, signal.entry_zone, current_price
                        )

                    if is_confirmed:
                        logger.info(f"Entry confirmed for signal {signal_id}")

                        trades_to_open = settings.TRADES_PER_SIGNAL
                        opened = 0

                        for i in range(trades_to_open):
                            can_open, reason = self.position_manager.can_open_new_position(str(signal_id))
                            if not can_open or self.safety.pause_new_trades:
                                reason = "New trades paused" if self.safety.pause_new_trades else reason
                                logger.warning(f"Cannot open position {i+1}/{trades_to_open} for signal {signal_id}: {reason}")
                                if opened == 0:
                                    self.database.mark_signal_trade_failed(signal_id, reason)
                                    signals_to_remove.append(signal_id)
                                break

                            trade = self.position_manager.place_entry_order(
                                signal.symbol,
                                signal.action,
                                current_price,
                                signal.stop_loss,
                                [tp.level for tp in signal.take_profits],
                                str(signal_id)
                            )

                            if trade:
                                opened += 1
                                self.database.mark_signal_traded(signal_id, trade.ticket)
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
                                await self.notifier.send_trade_opened(
                                    trade.ticket, signal.symbol, signal.action,
                                    trade.entry_price, trade.volume, trade.stop_loss
                                )
                                logger.info(f"Opened trade {opened}/{trades_to_open} for signal {signal_id}: ticket={trade.ticket}")
                            else:
                                logger.error(f"Trade {i+1}/{trades_to_open} failed for signal {signal_id}")
                                if opened == 0:
                                    reason = "MT5 order_send failed; check latest order retcode in logs"
                                    self.database.mark_signal_trade_failed(signal_id, reason)
                                    signals_to_remove.append(signal_id)
                                break

                        if opened > 0:
                            self.zone_reached_signals[signal_id] = signal
                            signals_to_remove.append(signal_id)
                            logger.info(f"Signal {signal_id} done: {opened}/{trades_to_open} trades opened")

                    else:
                        logger.info(f"Entry not confirmed for {signal_id}: {confirmation_details['reasons']}")

                else:
                    now = datetime.utcnow()
                    last_log = self._last_price_log.get(signal_id)
                    if not last_log or (now - last_log).total_seconds() >= 30:
                        logger.info(
                            f"Signal {signal_id} waiting: {signal.symbol} {signal.action} "
                            f"price={current_price}, zone={signal.entry_zone['min']}-{signal.entry_zone['max']}, "
                            f"age={int((now - signal.timestamp).total_seconds())}s"
                        )
                        self._last_price_log[signal_id] = now

            except Exception as e:
                logger.error(f"Error checking signal {signal_id}: {str(e)}")
                self.database.log_error("check_signals", str(e))

        for signal_id in signals_to_remove:
            self.pending_signals.pop(signal_id, None)
            self._last_price_log.pop(signal_id, None)

    async def _handle_trade_update(self, trade):
        try:
            if trade.status == TradeStatus.BE_ACTIVATED:
                self.position_manager.activate_break_even(trade.ticket)
                self.database.activate_be_on_trade(trade.ticket)
                await self.notifier.send_be_activated(trade.ticket, trade.symbol, trade.break_even_price)

            elif trade.status == TradeStatus.RUNNER_MODE:
                trail_distance = abs(trade.current_price - trade.stop_loss) * 0.5
                self.position_manager.activate_trailing_stop(trade.ticket, trail_distance)
                self.database.activate_runner_mode_on_trade(trade.ticket)
                await self.notifier.send_runner_mode_activated(trade.ticket, trade.symbol, trail_distance)

        except Exception as e:
            logger.error(f"Error handling trade update: {str(e)}")

    async def _check_runner_mode_trades(self):
        for ticket, trade in list(self.position_manager.open_trades.items()):
            try:
                if trade.status != TradeStatus.RUNNER_MODE:
                    continue

                if not self._check_trend_continuation(trade):
                    logger.info(f"Trend weakened for {ticket}, closing runner trade")
                    self.position_manager.close_position(ticket)
                    self.database.close_trade(
                        ticket, trade.current_price, trade.profit_loss, trade.profit_loss_percent
                    )

            except Exception as e:
                logger.error(f"Error in runner mode check: {str(e)}")

    def _check_trend_continuation(self, trade) -> bool:
        try:
            import MetaTrader5 as mt5

            rates = mt5.copy_rates_from_pos(trade.symbol, mt5.TIMEFRAME_M1, 0, 10)
            if rates is None or len(rates) < 5:
                return True

            highs = [float(r['high']) for r in rates]
            lows  = [float(r['low'])  for r in rates]

            if trade.action.upper() == 'BUY':
                hh = all(highs[i] <= highs[i+1] for i in range(len(highs)-1))
                hl = all(lows[i]  <= lows[i+1]  for i in range(len(lows)-1))
                return hh and hl
            else:
                lh = all(highs[i] >= highs[i+1] for i in range(len(highs)-1))
                ll = all(lows[i]  >= lows[i+1]  for i in range(len(lows)-1))
                return lh and ll

        except Exception as e:
            logger.error(f"Error checking trend: {str(e)}")
            return True

    # ── Safety controls ────────────────────────────────────────────────────

    async def emergency_stop(self):
        logger.warning("EMERGENCY STOP ACTIVATED")
        self.safety.emergency_stop = True
        closed = self.position_manager.close_all_positions()
        await self.notifier.send_info("🚨 EMERGENCY STOP", {'Positions Closed': len(closed)})

    async def pause_new_trades(self):
        logger.warning("Pausing new trades")
        self.safety.pause_new_trades = True
        await self.notifier.send_info("⏸️ New Trades Paused", {'Status': 'Only existing trades will be managed'})

    async def resume_trades(self):
        logger.info("Resuming new trades")
        self.safety.pause_new_trades = False
        await self.notifier.send_info("▶️ Trades Resumed", {'Status': 'New trades enabled'})