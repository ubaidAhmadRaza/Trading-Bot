from typing import Dict, Optional
from datetime import datetime, timedelta
import redis
from src.utils.logger import get_logger

logger = get_logger(__name__)

MIN_SIGNAL_CONFIDENCE = 0.7
MAX_DAILY_TRADES = 10


class SignalValidator:
    def __init__(self, redis_client: Optional[redis.Redis] = None,
                 min_confidence: float = MIN_SIGNAL_CONFIDENCE,
                 max_daily_trades: int = MAX_DAILY_TRADES):
        self.redis_client = redis_client
        self.min_confidence = min_confidence
        self.max_daily_trades = max_daily_trades

    def validate(self, signal: Dict) -> bool:
        """Validate trading signal against all rules"""
        try:
            if signal.get('confidence', 0) < self.min_confidence:
                logger.info(f"Signal rejected: Low confidence {signal['confidence']}")
                return False

            if not self._is_valid_symbol(signal['symbol']):
                logger.info(f"Signal rejected: Invalid symbol {signal['symbol']}")
                return False

            if not self._check_daily_limit():
                logger.info("Signal rejected: Daily trade limit reached")
                return False

            if not self._validate_price_levels(signal):
                logger.info("Signal rejected: Invalid price levels")
                return False

            if self._is_duplicate_signal(signal):
                logger.info("Signal rejected: Duplicate signal")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating signal: {str(e)}")
            return False

    def _is_valid_symbol(self, symbol: str) -> bool:
        import MetaTrader5 as mt5
        return bool(mt5.symbol_info(symbol))

    def _check_daily_limit(self) -> bool:
        if not self.redis_client:
            return True

        today = datetime.now().strftime('%Y%m%d')
        key = f"daily_trades:{today}"
        count = self.redis_client.get(key)
        if count and int(count) >= self.max_daily_trades:
            return False
        return True

    def _validate_price_levels(self, signal: Dict) -> bool:
        entry = signal.get('entry_price')
        sl = signal.get('stop_loss')
        tp = signal.get('take_profit')

        if not sl and not tp:
            return True

        if entry and sl:
            if signal['action'].upper() == 'BUY' and sl >= entry:
                return False
            if signal['action'].upper() == 'SELL' and sl <= entry:
                return False

        if entry and tp:
            if signal['action'].upper() == 'BUY' and tp <= entry:
                return False
            if signal['action'].upper() == 'SELL' and tp >= entry:
                return False

        return True

    def _is_duplicate_signal(self, signal: Dict) -> bool:
        if not self.redis_client:
            return False

        key = f"signal:{signal['symbol']}:{signal['action']}"
        last_signal = self.redis_client.get(key)

        if last_signal:
            last_time = datetime.fromisoformat(last_signal.decode())
            if datetime.utcnow() - last_time < timedelta(minutes=5):
                return True

        self.redis_client.setex(key, timedelta(minutes=10), datetime.utcnow().isoformat())
        return False
