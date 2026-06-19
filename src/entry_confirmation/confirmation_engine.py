"""
Entry Confirmation Engine
Validates entry conditions using technical analysis
- M1/M5 rejection candle checks
- Minor Break of Structure (BOS)
- Momentum confirmation
"""
import MetaTrader5 as mt5
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CandleData:
    """Represents OHLC candle data"""
    def __init__(self, open_price: float, high: float, low: float, close: float, time: datetime):
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.time = time
        self.body = abs(close - open_price)
        self.upper_wick = high - max(open_price, close)
        self.lower_wick = min(open_price, close) - low
        self.range = high - low

    def is_rejection_candle(self, direction: str) -> bool:
        """
        Check if candle is a rejection candle
        BUY: Long upper wick, small body (rejection of highs)
        SELL: Long lower wick, small body (rejection of lows)
        """
        wick_to_body_ratio = 2.0  # Wick should be at least 2x the body
        min_wick_ratio = 0.7  # Wick should be at least 70% of total range

        if direction.upper() == 'BUY':
            # Rejection of highs: upper wick > 2x body, upper wick > 70% of range
            return (self.upper_wick > self.body * wick_to_body_ratio and
                    self.upper_wick > self.range * min_wick_ratio)
        else:  # SELL
            # Rejection of lows: lower wick > 2x body, lower wick > 70% of range
            return (self.lower_wick > self.body * wick_to_body_ratio and
                    self.lower_wick > self.range * min_wick_ratio)

    def is_bullish(self) -> bool:
        """Candle is bullish (close > open)"""
        return self.close > self.open

    def is_bearish(self) -> bool:
        """Candle is bearish (close < open)"""
        return self.close < self.open


class EntryConfirmationEngine:
    """
    Validates entry conditions before trade execution
    """

    def __init__(self, mt5_client):
        self.mt5_client = mt5_client
        self.ema_period_short = 20
        self.ema_period_long = 50

    def check_entry_confirmation(
        self,
        symbol: str,
        action: str,
        entry_zone: Dict[str, float],
        current_price: float
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Comprehensive entry confirmation check

        Returns:
            (is_confirmed, details_dict)
        """
        details = {
            'symbol': symbol,
            'action': action,
            'current_price': current_price,
            'in_entry_zone': False,
            'm1_rejection': False,
            'm5_rejection': False,
            'bos_confirmed': False,
            'momentum_confirmed': False,
            'ema_confirmation': False,
            'reasons': []
        }

        try:
            # Check 1: Is price in entry zone?
            if not self._check_entry_zone(current_price, entry_zone):
                details['reasons'].append('Price not in entry zone')
                return False, details

            details['in_entry_zone'] = True

            # Check 2: M1 and M5 rejection candles
            m1_rejection = self._check_rejection_candle(symbol, 1, action)  # 1 = M1
            m5_rejection = self._check_rejection_candle(symbol, 5, action)  # 5 = M5

            details['m1_rejection'] = m1_rejection
            details['m5_rejection'] = m5_rejection

            if not (m1_rejection or m5_rejection):
                details['reasons'].append('No rejection candle on M1/M5')
                return False, details

            # Check 3: Break of Structure (BOS)
            bos = self._check_break_of_structure(symbol, action)
            details['bos_confirmed'] = bos

            if not bos:
                details['reasons'].append('No Break of Structure confirmed')
                return False, details

            # Check 4: Momentum confirmation
            momentum = self._check_momentum(symbol, action)
            details['momentum_confirmed'] = momentum

            if not momentum:
                details['reasons'].append('Momentum not confirmed')
                return False, details

            # Check 5: EMA confirmation
            ema_confirmed = self._check_ema_confirmation(symbol, action)
            details['ema_confirmation'] = ema_confirmed

            if not ema_confirmed:
                details['reasons'].append('EMA confirmation failed')
                return False, details

            details['reasons'].append('All confirmations passed')
            return True, details

        except Exception as e:
            logger.error(f"Error in entry confirmation: {str(e)}")
            details['reasons'].append(f'Error: {str(e)}')
            return False, details

    def _check_entry_zone(self, current_price: float, entry_zone: Dict[str, float]) -> bool:
        """Check if current price is within entry zone"""
        return entry_zone['min'] <= current_price <= entry_zone['max']

    def _check_rejection_candle(self, symbol: str, timeframe: int, action: str) -> bool:
        """
        Check for rejection candle on M1 or M5
        timeframe: 1 for M1, 5 for M5
        """
        try:
            # Get last 2 candles
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 2)
            if rates is None or len(rates) < 2:
                return False

            last_candle = CandleData(
                open_price=rates[-1]['open'],
                high=rates[-1]['high'],
                low=rates[-1]['low'],
                close=rates[-1]['close'],
                time=datetime.fromtimestamp(rates[-1]['time'])
            )

            is_rejection = last_candle.is_rejection_candle(action)
            logger.debug(f"{symbol} M{timeframe} rejection check: {is_rejection}")
            return is_rejection

        except Exception as e:
            logger.error(f"Error checking rejection candle for {symbol}: {str(e)}")
            return False

    def _check_break_of_structure(self, symbol: str, action: str) -> bool:
        """
        Check for Break of Structure (BOS)
        BUY: Price breaks above previous swing high
        SELL: Price breaks below previous swing low
        """
        try:
            # Get last 5 M5 candles to find swing points
            rates = mt5.copy_rates_from_pos(symbol, 5, 0, 5)
            if rates is None or len(rates) < 5:
                return False

            highs = [r['high'] for r in rates]
            lows = [r['low'] for r in rates]

            if action.upper() == 'BUY':
                # Check if current close is above previous highs
                current_close = rates[-1]['close']
                prev_high = max(highs[:-1])  # Previous swing high
                return current_close > prev_high

            else:  # SELL
                # Check if current close is below previous lows
                current_close = rates[-1]['close']
                prev_low = min(lows[:-1])  # Previous swing low
                return current_close < prev_low

        except Exception as e:
            logger.error(f"Error checking BOS for {symbol}: {str(e)}")
            return False

    def _check_momentum(self, symbol: str, action: str) -> bool:
        """
        Check momentum using RSI or candle strength
        Uses the last few candles to verify trend momentum
        """
        try:
            rates = mt5.copy_rates_from_pos(symbol, 1, 0, 3)
            if rates is None or len(rates) < 3:
                return False

            # Simple momentum: check if last 2 candles are in direction
            candles = [CandleData(
                open_price=r['open'],
                high=r['high'],
                low=r['low'],
                close=r['close'],
                time=datetime.fromtimestamp(r['time'])
            ) for r in rates[-2:]]

            if action.upper() == 'BUY':
                # At least 1 bullish candle in last 2
                momentum = sum(1 for c in candles if c.is_bullish()) >= 1
            else:  # SELL
                # At least 1 bearish candle in last 2
                momentum = sum(1 for c in candles if c.is_bearish()) >= 1

            logger.debug(f"{symbol} momentum check: {momentum}")
            return momentum

        except Exception as e:
            logger.error(f"Error checking momentum for {symbol}: {str(e)}")
            return False

    def _check_ema_confirmation(self, symbol: str, action: str) -> bool:
        """
        Check EMA20/EMA50 confirmation
        BUY: EMA20 > EMA50
        SELL: EMA20 < EMA50
        """
        try:
            # Get rates for EMA calculation
            rates = mt5.copy_rates_from_pos(symbol, 5, 0, 100)
            if rates is None or len(rates) < 50:
                logger.warning(f"Not enough data for EMA calculation on {symbol}")
                return True  # Skip EMA check if not enough data

            closes = np.array([r['close'] for r in rates])

            # Calculate EMAs
            ema20 = self._calculate_ema(closes, self.ema_period_short)
            ema50 = self._calculate_ema(closes, self.ema_period_long)

            if action.upper() == 'BUY':
                ema_confirmed = ema20 > ema50
            else:  # SELL
                ema_confirmed = ema20 < ema50

            logger.debug(f"{symbol} EMA20: {ema20:.2f}, EMA50: {ema50:.2f}, Confirmed: {ema_confirmed}")
            return ema_confirmed

        except Exception as e:
            logger.error(f"Error checking EMA for {symbol}: {str(e)}")
            return True  # Default to True if error

    @staticmethod
    def _calculate_ema(data: np.ndarray, period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(data) < period:
            return np.mean(data)

        multiplier = 2 / (period + 1)
        ema = np.mean(data[:period])

        for i in range(period, len(data)):
            ema = (data[i] * multiplier) + (ema * (1 - multiplier))

        return ema
