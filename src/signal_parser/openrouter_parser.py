"""
OpenRouter Signal Parser (Kimi model)
--------------------------------------
Fallback parser that sends raw Telegram messages to the Kimi model via
OpenRouter and extracts a normalised trading signal.

Used when the regex-based EnhancedSignalParser returns None — i.e. for
free-text, emoji-heavy, multilingual, or informal signal messages.

Canonical output format (JSON returned by the model):
{
  "symbol":      "BTCUSD",          // clean signal symbol, no broker suffix
  "action":      "BUY",             // BUY | SELL | CLOSE
  "entry_min":   62900.0,           // entry zone lower bound
  "entry_max":   63100.0,           // entry zone upper bound
  "stop_loss":   62000.0,           // null if not found
  "take_profits": [64000.0, 65000.0] // empty list if not found
}

Integration:
    from src.signal_parser.openrouter_parser import OpenRouterSignalParser
    parser = OpenRouterSignalParser()
    signal = parser.parse(raw_text, channel_name)

Toggle via .env:
    OPENROUTER_API_KEY=sk-or-...
    ENABLE_OPENROUTER_PARSER=true
"""

import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

from src.signal_parser.enhanced_parser import (
    EnhancedTradingSignal,
    TakeProfitLevel,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Kimi model identifier on OpenRouter
KIMI_MODEL = "moonshotai/kimi-k2"

# System prompt — instructs the model to output ONLY a JSON object
SYSTEM_PROMPT = """You are a professional trading signal parser. Extract trading data from Telegram messages and return ONLY a valid JSON object. No markdown, no explanation, no extra text.

## OUTPUT SCHEMA (all keys always required)
{
  "symbol":       string | null,
  "action":       string | null,
  "entry_min":    number | null,
  "entry_max":    number | null,
  "stop_loss":    number | null,
  "take_profits": [number, ...]
}

## SYMBOL RULES
- ALWAYS map these to standard symbols:
  GOLD → XAUUSD
  SILVER → XAGUSD
  BTC → BTCUSD
  ETH → ETHUSD
  OIL / CRUDE → USOIL
  DOW / DJ → US30
  NASDAQ / NQ → NAS100
  SP500 / SPX → US500
- Strip broker suffixes: XAUUSDm → XAUUSD
- Strip hashtags: #XAUUSD → XAUUSD
- NEVER output GOLD. Only output XAUUSD.

## ACTION RULES
- Return exactly: BUY, SELL, or CLOSE
- Map these to BUY: LONG, BUY LIMIT, BUY STOP, BULLISH, BUY NOW
- Map these to SELL: SHORT, SELL LIMIT, SELL STOP, BEARISH, SELL NOW
- Map these to CLOSE: CLOSE, EXIT, TP HIT, BOOK PROFITS

## ENTRY ZONE RULES
- Range "4136.00 - 4126.00" → entry_min=4126.0, entry_max=4136.0 (smaller first, larger second)
- Range "4126-4136" or "4126 / 4136" → entry_min=4126, entry_max=4136
- Single price "Entry: 4135" or "Price: 4135" → entry_min=entry_max=4135
- Labels: Entry, Enter, Price, Zone, Area, Range, Buy at, Sell at, @
- If no entry found: entry_min=null, entry_max=null

## STOP LOSS RULES
- Labels: SL, S/L, Stop, Stop Loss, StopLoss, SL:
- Return the exact price number
- If given in pips (e.g. "SL: 50 pips"):
  - BUY: SL = entry_min - (pips / 10)
  - SELL: SL = entry_max + (pips / 10)
- If no SL found: null

## TAKE PROFIT RULES
- Labels: TP, T/P, Take Profit, Target, TP1, TP2, TP3, T1, T2, T3, TP:
- Extract ALL TP levels in order
- Can be comma separated, slash separated, or new lines
- If given in pips (e.g. "TP: 50Pips / 100Pips" or "TP: 50/100 pips"):
  - 10 pips = 1.0 price move for XAUUSD
  - BUY: TP = entry_max + (pips / 10)
  - SELL: TP = entry_min - (pips / 10)
  - "50Pips / 100Pips" for BUY at 4136 → take_profits: [4141.0, 4146.0]
  - "50Pips / 100Pips" for SELL at 4136 → take_profits: [4131.0, 4126.0]
- If given as exact prices (e.g. "TP1: 4141, TP2: 4146") → use the numbers directly
- If no TP found: []

## PIP CALCULATION (XAUUSD)
- 1 pip = 0.1 price
- 10 pips = 1.0 price
- 50 pips = 5.0 price
- 100 pips = 10.0 price
- Only apply pip math when values are clearly pip counts (small numbers like 50, 100, 150)
- Large numbers like 4135, 2650 are prices, NOT pips

## PRICE FORMATTING
- Remove commas: 1,850.50 → 1850.50
- Remove currency symbols: $63,000 → 63000
- Remove spaces in numbers: 1 850.50 → 1850.50
- Negative prices → null

## EXAMPLES

Message: "GOLD BUY NOW Price : 4136.00 - 4126.00 SL : 4121.00 TP : 50Pips / 100Pips"
Output: {"symbol":"XAUUSD","action":"BUY","entry_min":4126.0,"entry_max":4136.0,"stop_loss":4121.0,"take_profits":[4141.0,4146.0]}

Message: "SELL XAUUSD 4130 SL 4140 TP 4120 / 4110"
Output: {"symbol":"XAUUSD","action":"SELL","entry_min":4130,"entry_max":4130,"stop_loss":4140,"take_profits":[4120,4110]}

Message: "GOLD BUY NOW !"
Output: {"symbol":"XAUUSD","action":"BUY","entry_min":null,"entry_max":null,"stop_loss":null,"take_profits":[]}

Message: "hit be then go up"
Output: {"symbol":null,"action":null,"entry_min":null,"entry_max":null,"stop_loss":null,"take_profits":[]}

## FAILURE CASES
- Not a trading signal (chat, news, discussion) → all null
- Cannot determine symbol AND action → all null
- Partial data is fine — return what you can, null/empty the rest
- NEVER make up values. If unsure, use null.

Return ONLY the JSON object. No markdown, no backticks, no explanation.
"""


# ── Parser class ──────────────────────────────────────────────────────────────

class OpenRouterSignalParser:
    """
    Calls the Kimi model (via OpenRouter) to parse any Telegram signal
    message into an EnhancedTradingSignal.
    """

    def __init__(self, api_key: str, model: str = KIMI_MODEL, timeout: int = 15):
        """
        Args:
            api_key:  OpenRouter API key  (OPENROUTER_API_KEY from .env)
            model:    OpenRouter model string (default: Kimi K2)
            timeout:  HTTP request timeout in seconds
        """
        if not api_key:
            raise ValueError("OpenRouter API key must be provided")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    # ── Public API ─────────────────────────────────────────────────────────

    def parse(self, message_text: str, channel: str) -> Optional[EnhancedTradingSignal]:
        """
        Parse a raw Telegram message into an EnhancedTradingSignal.

        Returns:
            EnhancedTradingSignal on success, None otherwise.
        """
        if not message_text or not message_text.strip():
            return None

        try:
            raw_json = self._call_openrouter(message_text)
            if not raw_json:
                return None

            data = self._safe_parse_json(raw_json)
            if not data:
                return None

            signal = self._build_signal(data, message_text, channel)
            if signal:
                logger.info(
                    f"[OpenRouter/Kimi] Parsed signal: {signal.symbol} {signal.action} "
                    f"zone={signal.entry_zone} sl={signal.stop_loss} tps={signal.take_profits}"
                )
            return signal

        except Exception as e:
            logger.error(f"[OpenRouter/Kimi] Unexpected error: {e}")
            return None

    # ── Internal helpers ────────────────────────────────────────────────────

    def _call_openrouter(self, message_text: str) -> Optional[str]:
        """Send message to OpenRouter and return raw response text."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": message_text.strip()},
            ],
            "temperature": 0,        # deterministic output
            "max_tokens": 256,
        }

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer":  "https://github.com/telegram-mt5-bot",  # recommended by OpenRouter
            "X-Title":       "Telegram MT5 Trading Bot",
        }

        req = urllib.request.Request(
            OPENROUTER_API_URL,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                response_body = resp.read().decode("utf-8")

            response_data = json.loads(response_body)
            content = (
                response_data
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            logger.debug(f"[OpenRouter/Kimi] Raw response: {content!r}")
            return content or None

        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            logger.error(f"[OpenRouter/Kimi] HTTP {e.code}: {body_text[:300]}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"[OpenRouter/Kimi] Network error: {e.reason}")
            return None

    @staticmethod
    def _safe_parse_json(text: str) -> Optional[dict]:
        """Extract and parse JSON from model output (strips markdown fences if present)."""
        # Strip ```json ... ``` fences
        clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()

        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            # Try to find a JSON object anywhere in the text
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

        logger.warning(f"[OpenRouter/Kimi] Could not parse JSON from: {text!r}")
        return None

    @staticmethod
    def _build_signal(
        data: dict,
        source_message: str,
        channel: str,
    ) -> Optional[EnhancedTradingSignal]:
        """Convert the parsed dict into an EnhancedTradingSignal."""

        symbol = data.get("symbol")
        action = data.get("action")

        # Must have at minimum symbol + action
        if not symbol or not action:
            logger.debug("[OpenRouter/Kimi] Missing symbol or action — signal skipped")
            return None

        action = action.upper().strip()
        if action not in ("BUY", "SELL", "CLOSE"):
            logger.warning(f"[OpenRouter/Kimi] Unrecognised action '{action}' — skipped")
            return None

        # Entry zone
        entry_min = data.get("entry_min")
        entry_max = data.get("entry_max")

        # Both must be present and positive
        if not entry_min or not entry_max or entry_min <= 0 or entry_max <= 0:
            logger.warning(f"[OpenRouter/Kimi] Invalid entry zone ({entry_min}, {entry_max}) — skipped")
            return None

        entry_zone = {
            "min": min(float(entry_min), float(entry_max)),
            "max": max(float(entry_min), float(entry_max)),
        }

        # Stop loss
        stop_loss = data.get("stop_loss")
        if stop_loss:
            stop_loss = float(stop_loss)
            # Basic sanity check
            if action == "BUY" and stop_loss >= entry_zone["min"]:
                logger.warning(
                    f"[OpenRouter/Kimi] SL {stop_loss} >= entry_min {entry_zone['min']} for BUY — clearing SL"
                )
                stop_loss = None
            elif action == "SELL" and stop_loss <= entry_zone["max"]:
                logger.warning(
                    f"[OpenRouter/Kimi] SL {stop_loss} <= entry_max {entry_zone['max']} for SELL — clearing SL"
                )
                stop_loss = None

        # Take profits
        raw_tps = data.get("take_profits") or []
        take_profits = []
        for i, tp_val in enumerate(raw_tps):
            try:
                tp = float(tp_val)
                if action == "BUY" and tp > entry_zone["max"]:
                    take_profits.append(TakeProfitLevel(level=tp, index=i))
                elif action == "SELL" and tp < entry_zone["min"]:
                    take_profits.append(TakeProfitLevel(level=tp, index=i))
            except (TypeError, ValueError):
                continue

        # Confidence scoring (same logic as EnhancedSignalParser)
        confidence = 0.6
        if stop_loss:
            confidence += 0.2
        if take_profits:
            confidence += 0.1
        if len(take_profits) > 1:
            confidence += 0.1
        confidence = min(confidence, 1.0)

        return EnhancedTradingSignal(
            symbol=symbol.upper(),
            action=action,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            take_profits=take_profits,
            confidence=confidence,
            raw_format="openrouter_kimi",
            timestamp=datetime.utcnow(),
            source_message=source_message[:500],
            channel=channel,
        )