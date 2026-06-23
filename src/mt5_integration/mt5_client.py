import MetaTrader5 as mt5
from typing import Optional, Dict, List
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_fixed
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MT5Client:
    def __init__(self, login: int, password: str, server: str, mt5_path: Optional[str] = None):
        self.login    = login
        self.password = password
        self.server   = server
        self.mt5_path = mt5_path
        self.connected = False

        # ── Caches ────────────────────────────────────────────────────────
        # Symbol resolution: signal symbol → broker symbol (never changes)
        self._symbol_cache: Dict[str, str] = {}

        # Static symbol fields: broker symbol → dict of fields that never
        # change at runtime (volume limits, digits, filling mode, etc.)
        self._symbol_static: Dict[str, Dict] = {}

    # ── Connection ─────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def connect(self) -> bool:
        try:
            if self.mt5_path:
                mt5_path = Path(self.mt5_path)
                if not mt5_path.exists():
                    logger.error(f"MT5 path does not exist: {self.mt5_path}")
                    return False
                initialized = mt5.initialize(str(mt5_path))
            else:
                initialized = mt5.initialize()

            if not initialized:
                logger.error(f"MT5 initialize failed: {mt5.last_error()}")
                return False

            authorized = mt5.login(
                login=self.login,
                password=self.password,
                server=self.server
            )

            if not authorized:
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                return False

            self.connected = True
            logger.info(f"Successfully connected to MT5 (Account: {self.login})")
            return True

        except Exception as e:
            logger.error(f"Error connecting to MT5: {str(e)}")
            return False

    def disconnect(self):
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("Disconnected from MT5")

    # ── Account ────────────────────────────────────────────────────────────

    def get_account_info(self) -> Optional[Dict]:
        try:
            info = mt5.account_info()
            if info:
                return {
                    'balance':     info.balance,
                    'equity':      info.equity,
                    'margin':      info.margin,
                    'free_margin': info.margin_free,
                    'profit':      info.profit,
                    'currency':    info.currency,
                }
        except Exception as e:
            logger.error(f"Error getting account info: {str(e)}")
        return None

    # ── Symbol resolution (cached) ─────────────────────────────────────────

    def resolve_symbol(self, symbol: str) -> Optional[str]:
        """
        Resolve a signal symbol to the broker MT5 symbol name.
        Result is cached for the lifetime of the process — resolution
        never changes once the broker symbol is found.
        """
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]

        try:
            if mt5.symbol_select(symbol, True):
                self._symbol_cache[symbol] = symbol
                return symbol

            candidates = []
            for pattern in (f"{symbol}*", f"*{symbol}*"):
                matches = mt5.symbols_get(pattern) or []
                candidates.extend([m.name for m in matches])

            clean_symbol = ''.join(ch for ch in symbol.upper() if ch.isalnum())
            for candidate in candidates:
                clean_candidate = ''.join(ch for ch in candidate.upper() if ch.isalnum())
                if clean_candidate.startswith(clean_symbol):
                    if mt5.symbol_select(candidate, True):
                        logger.info(f"Resolved MT5 symbol {symbol} -> {candidate}")
                        self._symbol_cache[symbol] = candidate
                        return candidate

            logger.error(f"Could not resolve MT5 symbol {symbol}. Candidates: {candidates[:10]}")
            return None

        except Exception as e:
            logger.error(f"Error resolving symbol {symbol}: {str(e)}")
            return None

    # ── Symbol info (static fields cached, tick always live) ───────────────

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """
        Returns symbol info with live bid/ask from tick.
        Static fields (volume limits, digits, filling mode) are cached
        after the first successful call — they never change at runtime.
        """
        try:
            resolved = self.resolve_symbol(symbol)
            if not resolved:
                return None

            # ── Live tick (always fresh — contains bid/ask) ────────────────
            tick = mt5.symbol_info_tick(resolved)
            if not tick:
                logger.error(f"Could not get tick for {resolved}: {mt5.last_error()}")
                return None

            bid = tick.bid
            ask = tick.ask
            if not bid or not ask:
                logger.error(f"Invalid bid/ask for {resolved}: bid={bid} ask={ask}")
                return None

            # ── Static fields (cached after first call) ────────────────────
            if resolved not in self._symbol_static:
                info = mt5.symbol_info(resolved)
                if not info:
                    logger.error(f"Could not get symbol_info for {resolved}: {mt5.last_error()}")
                    return None
                self._symbol_static[resolved] = {
                    'spread':       info.spread,
                    'digits':       info.digits,
                    'point':        info.point,
                    'volume_min':   info.volume_min,
                    'volume_max':   info.volume_max,
                    'volume_step':  info.volume_step,
                    'trade_mode':   info.trade_mode,
                    'filling_mode': info.filling_mode,
                    'visible':      info.visible,
                }
                logger.debug(f"Cached static symbol info for {resolved}")

            static = self._symbol_static[resolved]

            return {
                'symbol':        resolved,
                'source_symbol': symbol,
                'bid':           bid,
                'ask':           ask,
                **static,
            }

        except Exception as e:
            logger.error(f"Error getting symbol info for {symbol}: {str(e)}")
        return None

    # ── Positions ──────────────────────────────────────────────────────────

    def get_positions(self) -> List[Dict]:
        try:
            positions = mt5.positions_get()
            if positions:
                return [{
                    'ticket':        pos.ticket,
                    'symbol':        pos.symbol,
                    'type':          'BUY' if pos.type == 0 else 'SELL',
                    'volume':        pos.volume,
                    'price_open':    pos.price_open,
                    'price_current': pos.price_current,
                    'profit':        pos.profit,
                    'sl':            pos.sl,
                    'tp':            pos.tp,
                } for pos in positions]
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
        return []