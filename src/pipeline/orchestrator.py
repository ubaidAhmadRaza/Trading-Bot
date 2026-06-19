import asyncio
from src.telegram_bot.client import TelegramSignalClient
from src.telegram_bot.signal_parser import SignalParser
from src.mt5_integration.mt5_client import MT5Client
from src.mt5_integration.order_manager import OrderManager
from src.pipeline.signal_validator import SignalValidator
from src.utils.logger import get_logger

logger = get_logger(__name__)

# --- Config (load from env/settings in production) ---
import os
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
TELEGRAM_CHANNELS = os.getenv("TELEGRAM_CHANNELS", "[]")
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", None)
RISK_PER_TRADE_PERCENT = float(os.getenv("RISK_PER_TRADE_PERCENT", "1.0"))
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "0.1"))
ENABLE_METRICS = os.getenv("ENABLE_METRICS", "false").lower() == "true"


import json
try:
    CHANNELS = json.loads(TELEGRAM_CHANNELS)
except Exception:
    CHANNELS = []


class TradingPipeline:
    def __init__(self):
        self.telegram_client = TelegramSignalClient(TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE)
        self.mt5_client = MT5Client(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH)
        self.order_manager = OrderManager(self.mt5_client)
        self.signal_validator = SignalValidator()
        self.metrics = None
        if ENABLE_METRICS:
            try:
                from src.utils.metrics import MetricsCollector
                self.metrics = MetricsCollector()
            except Exception as e:
                logger.warning(f"Could not start metrics: {e}")
        self.is_running = False

    async def start(self):
        """Start the trading pipeline"""
        logger.info("Starting Trading Pipeline...")

        if not self.mt5_client.connect():
            raise Exception("Failed to connect to MT5")

        await self.telegram_client.connect()

        self.is_running = True
        await self.telegram_client.listen_channels(CHANNELS, self.handle_signal)

    async def handle_signal(self, message):
        """Handle incoming signal from Telegram"""
        try:
            signal = SignalParser.parse(message.text, message.chat.title)
            if not signal:
                return

            logger.info(f"Received signal: {signal.symbol} {signal.action}")
            signal_dict = signal.dict()

            if not self.signal_validator.validate(signal_dict):
                logger.info(f"Signal rejected for {signal.symbol}")
                return

            volume = self._calculate_position_size(signal_dict)
            if volume <= 0:
                logger.warning(f"Invalid position size for {signal.symbol}")
                return

            if signal.action == 'CLOSE':
                await self._close_all_positions(signal.symbol)
            else:
                order_ticket = self.order_manager.place_order({**signal_dict, 'volume': volume})
                if order_ticket:
                    logger.info(f"Trade executed: {signal.symbol} {signal.action} Ticket: {order_ticket}")
                    if self.metrics:
                        self.metrics.record_trade(signal.symbol, signal.action, signal.entry_price)
                else:
                    logger.error(f"Failed to execute trade for {signal.symbol}")

        except Exception as e:
            logger.error(f"Error handling signal: {str(e)}")

    def _calculate_position_size(self, signal: dict) -> float:
        try:
            account_info = self.mt5_client.get_account_info()
            if not account_info:
                return 0.01

            risk_amount = account_info['balance'] * (RISK_PER_TRADE_PERCENT / 100)

            if signal.get('stop_loss') and signal.get('entry_price'):
                if signal['action'] == 'BUY':
                    sl_distance = signal['entry_price'] - signal['stop_loss']
                else:
                    sl_distance = signal['stop_loss'] - signal['entry_price']

                if sl_distance > 0:
                    symbol_info = self.mt5_client.get_symbol_info(signal['symbol'])
                    if symbol_info:
                        pip_value = 0.0001 if 'USD' in symbol_info['symbol'] else 0.01
                        volume = risk_amount / (sl_distance * pip_value)
                        return min(max(volume, 0.01), MAX_POSITION_SIZE)

            return min(0.01 * (account_info['balance'] / 10000), MAX_POSITION_SIZE)

        except Exception as e:
            logger.error(f"Error calculating position size: {str(e)}")
            return 0.01

    async def _close_all_positions(self, symbol: str):
        positions = self.mt5_client.get_positions()
        for position in positions:
            if position['symbol'] == symbol:
                self.order_manager.close_position(position['ticket'])

    async def stop(self):
        self.is_running = False
        if self.telegram_client.client:
            self.telegram_client.client.disconnect()
        self.mt5_client.disconnect()
        logger.info("Pipeline stopped")
