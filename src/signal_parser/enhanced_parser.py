"""
Enhanced Signal Parser
Parses trading signals from Telegram messages.

Supports multiple real-world channel formats:
  Format A (structured):
    EURUSD BUY
    Entry: 1.0850 - 1.0870
    SL: 1.0800
    TP1: 1.0920
    TP2: 1.0980
    TP3: 1.1050

  Format B (compact):
    #XAUUSD SELL 1920.00
    SL 1930
    TP 1900 / 1880 / 1860

  Format C (zone-based):
    GBPUSD | BUY
    Zone: 1.2600 - 1.2650
    Stop Loss: 1.2540
    Take Profit: 1.2750

  Format D (plain):
    BUY USDJPY @ 148.50
    SL: 147.80
    TP: 149.50
"""
import re
from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass, field
from pydantic import BaseModel, validator
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class TakeProfitLevel:
    """A single take-profit level"""
    level: float
    index: int = 0          # TP1, TP2, TP3 …

    def __repr__(self):
        return f"TP{self.index + 1}={self.level}"


class EnhancedTradingSignal(BaseModel):
    """
    Full signal model expected by EnhancedTradingPipeline / orchestrator.
    """
    symbol: str
    action: str                             # BUY | SELL | CLOSE
    entry_zone: dict                        # {'min': float, 'max': float}
    stop_loss: Optional[float] = None
    take_profits: List[TakeProfitLevel] = field(default_factory=list)
    confidence: float = 1.0
    raw_format: str = "unknown"             # A | B | C | D | unknown
    timestamp: datetime = None
    source_message: str = ""
    channel: str = ""

    class Config:
        arbitrary_types_allowed = True      # allow TakeProfitLevel dataclass

    @validator('action')
    def validate_action(cls, v):
        v = v.upper().strip()
        if v not in ['BUY', 'SELL', 'CLOSE']:
            raise ValueError(f'Invalid action: {v}')
        return v

    @validator('confidence')
    def validate_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError('Confidence must be between 0 and 1')
        return v

    @validator('timestamp', pre=True, always=True)
    def set_timestamp(cls, v):
        return v or datetime.utcnow()

    @property
    def entry_price(self) -> float:
        """Mid-point of entry zone — convenience for order placement"""
        return (self.entry_zone['min'] + self.entry_zone['max']) / 2

    @property
    def take_profit(self) -> Optional[float]:
        """First TP level — convenience property"""
        return self.take_profits[0].level if self.take_profits else None


# Keep the old flat model available so existing code that imports
# TradingSignal from this module doesn't break.
class TradingSignal(BaseModel):
    symbol: str
    action: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 1.0
    timestamp: datetime = None
    source_message: str = ""
    channel: str = ""

    @validator('action')
    def validate_action(cls, v):
        v = v.upper()
        if v not in ['BUY', 'SELL', 'CLOSE']:
            raise ValueError(f'Invalid action: {v}')
        return v

    @validator('timestamp', pre=True, always=True)
    def set_timestamp(cls, v):
        return v or datetime.utcnow()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_float(s: str) -> Optional[float]:
    """Safe string → float, handles commas and spaces."""
    try:
        return float(s.replace(',', '').strip())
    except (ValueError, AttributeError):
        return None


def _build_zone(entry_str: str, buffer_pct: float = 0.05) -> dict:
    """
    Build an entry zone dict from a raw entry string.
    Handles:
      '1.0850'               → single price  → ±buffer
      '1.0850 - 1.0870'     → explicit range
      '1.0850/1.0870'       → slash range
    """
    # Try explicit range first:  1.0850 - 1.0870  or  1.0850/1.0870
    range_match = re.search(
        r'([\d,.]+)\s*[-/]\s*([\d,.]+)', entry_str
    )
    if range_match:
        lo = _to_float(range_match.group(1))
        hi = _to_float(range_match.group(2))
        if lo and hi:
            return {'min': min(lo, hi), 'max': max(lo, hi)}

    # Single price with buffer
    price = _to_float(re.sub(r'[^\d.,]', '', entry_str))
    if price:
        buf = price * (buffer_pct / 100)
        return {'min': round(price - buf, 6), 'max': round(price + buf, 6)}

    return {'min': 0.0, 'max': 0.0}


def _parse_tp_list(text: str) -> List[TakeProfitLevel]:
    """
    Extract all TP values from a block of text.
    Handles:
      TP1: 1.0920  TP2: 1.0980  TP3: 1.1050
      TP: 1.0920 / 1.0980 / 1.1050
      TP: 1900 | 1880 | 1860
      Take Profit: 1.2750
    """
    tps: List[float] = []

    # Numbered TPs:  TP1: 1.09  or  T/P 1: 1.09
    numbered = re.findall(
        r'(?:tp|t/p|take\s*profit)\s*\d\s*[:\s]*([\d,.]+)',
        text, re.IGNORECASE
    )
    for val in numbered:
        f = _to_float(val)
        if f:
            tps.append(f)

    # Slash / pipe separated list after TP:
    # TP: 1900 / 1880 / 1860
    if not tps:
        list_match = re.search(
            r'(?:tp|t/p|take\s*profit)\s*[:\s]*([\d,./|\s]+)',
            text, re.IGNORECASE
        )
        if list_match:
            raw = list_match.group(1)
            for part in re.split(r'[/|,\s]+', raw):
                f = _to_float(part)
                if f and f > 0:
                    tps.append(f)

    # Single TP fallback
    if not tps:
        single = re.search(
            r'(?:tp|t/p|take\s*profit)\s*[:\s]*([\d,.]+)',
            text, re.IGNORECASE
        )
        if single:
            f = _to_float(single.group(1))
            if f:
                tps.append(f)

    # Deduplicate, keep order
    seen = set()
    unique: List[float] = []
    for t in tps:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return [TakeProfitLevel(level=v, index=i) for i, v in enumerate(unique)]


# ─── Main parser class ────────────────────────────────────────────────────────

class EnhancedSignalParser:
    """
    Tries multiple format patterns in order.
    Returns EnhancedTradingSignal or None.
    """

    # Common symbol pattern: 6-8 uppercase letters, optionally with #
    _SYMBOL = r'#?([A-Z]{2,6}(?:USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|XAU|XAG|BTC|ETH|OIL|NAS|SPX)?[A-Z]{0,3})'
    _ACTION = r'\b(BUY|SELL|CLOSE|LONG|SHORT)\b'
    _PRICE  = r'([\d,.]+(?:\s*[-/]\s*[\d,.]+)?)'   # single or range

    # ── Format A ──────────────────────────────────────────────────────────────
    # EURUSD BUY                         (symbol + action on first line)
    # Entry: 1.0850 - 1.0870
    # SL: 1.0800
    # TP1: 1.0920 / TP2: 1.0980
    _FMT_A = re.compile(
        rf'^{_SYMBOL}\s+{_ACTION}',
        re.IGNORECASE | re.MULTILINE
    )

    # ── Format B ──────────────────────────────────────────────────────────────
    # #XAUUSD SELL 1920.00               (symbol + action + inline price)
    # SL 1930
    # TP 1900 / 1880 / 1860
    _FMT_B = re.compile(
        rf'^{_SYMBOL}\s+{_ACTION}\s+{_PRICE}',
        re.IGNORECASE | re.MULTILINE
    )

    # ── Format C ──────────────────────────────────────────────────────────────
    # GBPUSD | BUY                       (symbol | action)
    # Zone: 1.2600 - 1.2650
    _FMT_C = re.compile(
        rf'^{_SYMBOL}\s*[|\-]\s*{_ACTION}',
        re.IGNORECASE | re.MULTILINE
    )

    # ── Format D ──────────────────────────────────────────────────────────────
    # BUY USDJPY @ 148.50                (action + symbol + @price)
    _FMT_D = re.compile(
        rf'^{_ACTION}\s+{_SYMBOL}(?:\s*@\s*{_PRICE})?',
        re.IGNORECASE | re.MULTILINE
    )

    def parse(self, message_text: str, channel: str) -> Optional[EnhancedTradingSignal]:
        """
        Parse a Telegram message into an EnhancedTradingSignal.
        Returns None if no valid signal found.
        """
        if not message_text or not message_text.strip():
            return None

        text = message_text.strip()

        # Try each format
        for fmt_name, method in [
            ('B', self._try_format_b),   # B before A — more specific
            ('A', self._try_format_a),
            ('C', self._try_format_c),
            ('D', self._try_format_d),
        ]:
            result = method(text)
            if result:
                symbol, action, entry_str = result
                signal = self._build_signal(
                    text, channel, symbol, action, entry_str, fmt_name
                )
                if signal:
                    logger.info(
                        f"Parsed signal [{fmt_name}]: {signal.symbol} {signal.action} "
                        f"zone={signal.entry_zone} sl={signal.stop_loss} "
                        f"tps={signal.take_profits}"
                    )
                    return signal

        logger.debug(f"No signal pattern matched in message: {text[:80]!r}")
        return None

    # ── Format handlers ───────────────────────────────────────────────────────

    def _try_format_b(self, text: str):
        m = self._FMT_B.search(text)
        if m:
            return m.group(1).upper(), self._normalize_action(m.group(2)), m.group(3)
        return None

    def _try_format_a(self, text: str):
        m = self._FMT_A.search(text)
        if m:
            symbol = m.group(1).upper()
            action = self._normalize_action(m.group(2))
            # Entry price is on a separate line
            entry_str = self._extract_entry(text) or '0'
            return symbol, action, entry_str
        return None

    def _try_format_c(self, text: str):
        m = self._FMT_C.search(text)
        if m:
            symbol = m.group(1).upper()
            action = self._normalize_action(m.group(2))
            entry_str = self._extract_zone(text) or self._extract_entry(text) or '0'
            return symbol, action, entry_str
        return None

    def _try_format_d(self, text: str):
        m = self._FMT_D.search(text)
        if m:
            action = self._normalize_action(m.group(1))
            symbol = m.group(2).upper()
            entry_str = m.group(3) if m.lastindex >= 3 and m.group(3) else \
                        self._extract_entry(text) or '0'
            return symbol, action, entry_str
        return None

    # ── Shared extraction helpers ─────────────────────────────────────────────

    def _extract_entry(self, text: str) -> Optional[str]:
        """Extract entry price / range from 'Entry:' line"""
        m = re.search(
            r'(?:entry|enter(?:ing)?|price)\s*[:\s]*([\d,.\s\-/]+)',
            text, re.IGNORECASE
        )
        return m.group(1).strip() if m else None

    def _extract_zone(self, text: str) -> Optional[str]:
        """Extract zone range from 'Zone:' line"""
        m = re.search(
            r'(?:zone|area|range)\s*[:\s]*([\d,.\s\-/]+)',
            text, re.IGNORECASE
        )
        return m.group(1).strip() if m else None

    def _extract_sl(self, text: str) -> Optional[float]:
        """Extract stop-loss from text"""
        m = re.search(
            r'(?:stop\s*loss|sl|s\.l\.?)\s*[:\s]*([\d,.]+)',
            text, re.IGNORECASE
        )
        return _to_float(m.group(1)) if m else None

    def _normalize_action(self, raw: str) -> str:
        """Normalize LONG→BUY, SHORT→SELL"""
        mapping = {'LONG': 'BUY', 'SHORT': 'SELL'}
        upper = raw.upper()
        return mapping.get(upper, upper)

    def _build_signal(
        self,
        text: str,
        channel: str,
        symbol: str,
        action: str,
        entry_str: str,
        raw_format: str
    ) -> Optional[EnhancedTradingSignal]:
        """Assemble and validate the final signal object"""
        try:
            entry_zone = _build_zone(entry_str)

            # Reject if zone is 0/invalid
            if entry_zone['max'] == 0:
                logger.warning(f"Could not determine entry zone for {symbol} — signal skipped")
                return None

            sl = self._extract_sl(text)
            take_profits = _parse_tp_list(text)

            # Basic sanity: SL must be on the correct side of entry
            entry_mid = (entry_zone['min'] + entry_zone['max']) / 2
            if sl:
                if action == 'BUY' and sl >= entry_zone['min']:
                    logger.warning(f"SL {sl} is above/at entry zone min {entry_zone['min']} for BUY — rejected")
                    return None
                if action == 'SELL' and sl <= entry_zone['max']:
                    logger.warning(f"SL {sl} is below/at entry zone max {entry_zone['max']} for SELL — rejected")
                    return None

            # TP sanity: at least one TP on the correct side
            if take_profits:
                if action == 'BUY':
                    valid_tps = [tp for tp in take_profits if tp.level > entry_zone['max']]
                else:
                    valid_tps = [tp for tp in take_profits if tp.level < entry_zone['min']]
                if not valid_tps:
                    logger.warning(f"No valid TPs found on correct side for {symbol} {action}")
                    take_profits = []   # allow signal through but with no TPs
                else:
                    take_profits = [TakeProfitLevel(level=tp.level, index=i)
                                    for i, tp in enumerate(valid_tps)]

            # Confidence: bump up if SL + TP both present
            confidence = 0.6
            if sl:
                confidence += 0.2
            if take_profits:
                confidence += 0.1
            if len(take_profits) > 1:
                confidence += 0.1
            confidence = min(confidence, 1.0)

            return EnhancedTradingSignal(
                symbol=symbol,
                action=action,
                entry_zone=entry_zone,
                stop_loss=sl,
                take_profits=take_profits,
                confidence=confidence,
                raw_format=raw_format,
                timestamp=datetime.utcnow(),
                source_message=text[:500],
                channel=channel
            )

        except Exception as e:
            logger.error(f"Error building signal: {str(e)}")
            return None


# ─── Backwards-compatible basic parser ───────────────────────────────────────

class SignalParser:
    """
    Original flat parser — kept for backwards compatibility.
    Use EnhancedSignalParser for the full pipeline.
    """

    PATTERNS = {
        'symbol':      r'#?([A-Z]{6,})',
        'action':      r'\b(BUY|SELL|CLOSE)\b',
        'entry':       r'(?:entry|enter|price)\s*[:\s]*([\d.]+)',
        'stop_loss':   r'(?:stop\s*loss|sl)\s*[:\s]*([\d.]+)',
        'take_profit': r'(?:take\s*profit|tp\s*1?)\s*[:\s]*([\d.]+)',
        'confidence':  r'(?:confidence|sure)\s*[:\s]*(\d+)%',
    }

    @classmethod
    def parse(cls, message_text: str, channel: str) -> Optional[TradingSignal]:
        try:
            data = {}
            for key, pattern in cls.PATTERNS.items():
                match = re.search(pattern, message_text, re.IGNORECASE)
                if match:
                    data[key] = match.group(1).strip()

            if not all(k in data for k in ['symbol', 'action']):
                return None

            confidence = float(data.get('confidence', 100)) / 100
            entry = _to_float(data['entry']) if data.get('entry') else None
            sl    = _to_float(data['stop_loss']) if data.get('stop_loss') else None
            tp    = _to_float(data['take_profit']) if data.get('take_profit') else None

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