import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, validator
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradingSignal(BaseModel):
    symbol: str
    action: str  # BUY, SELL, CLOSE
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 1.0
    timestamp: datetime
    source_message: str
    channel: str

    @validator('action')
    def validate_action(cls, v):
        v = v.upper()
        if v not in ['BUY', 'SELL', 'CLOSE']:
            raise ValueError(f'Invalid action: {v}')
        return v

    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError('Confidence must be between 0 and 1')
        return v


class SignalParser:
    PATTERNS = {
        'symbol': r'(?:symbol|pair|asset)[:\s]*([A-Z]{6,})',
        'action': r'(BUY|SELL|CLOSE)',
        'entry': r'(?:entry|enter)[:\s]*([\d.]+)',
        'stop_loss': r'(?:stop loss|sl)[:\s]*([\d.]+)',
        'take_profit': r'(?:take profit|tp)[:\s]*([\d.]+)',
        'confidence': r'(?:confidence|sure)[:\s]*(\d+)%',
    }

    @classmethod
    def parse(cls, message_text: str, channel: str) -> Optional[TradingSignal]:
        """Parse trading signal from Telegram message"""
        try:
            data = {}
            for key, pattern in cls.PATTERNS.items():
                match = re.search(pattern, message_text, re.IGNORECASE)
                if match:
                    data[key] = match.group(1).strip()

            if not all(k in data for k in ['symbol', 'action']):
                logger.debug(f"Incomplete signal data: {data}")
                return None

            confidence = float(data.get('confidence', 100)) / 100
            entry = float(data['entry']) if data.get('entry') else None
            sl = float(data['stop_loss']) if data.get('stop_loss') else None
            tp = float(data['take_profit']) if data.get('take_profit') else None

            if entry and sl and tp:
                if not (sl < entry < tp or tp < entry < sl):
                    logger.warning(f"Invalid price levels: entry={entry}, sl={sl}, tp={tp}")
                    return None

            return TradingSignal(
                symbol=data['symbol'].upper(),
                action=data['action'].upper(),
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                confidence=confidence,
                timestamp=datetime.utcnow(),
                source_message=message_text[:500],
                channel=channel
            )

        except Exception as e:
            logger.error(f"Error parsing signal: {str(e)}")
            return None
