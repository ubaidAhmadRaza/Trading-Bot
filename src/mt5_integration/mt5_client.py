import MetaTrader5 as mt5
from typing import Optional, Dict, List
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_fixed
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MT5Client:
    def __init__(self, login: int, password: str, server: str, mt5_path: Optional[str] = None):
        self.login = login
        self.password = password
        self.server = server
        self.mt5_path = mt5_path
        self.connected = False

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def connect(self) -> bool:
        """Connect to MT5 with retry logic"""
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

    def get_account_info(self) -> Optional[Dict]:
        try:
            info = mt5.account_info()
            if info:
                return {
                    'balance': info.balance,
                    'equity': info.equity,
                    'margin': info.margin,
                    'free_margin': info.margin_free,
                    'profit': info.profit,
                    'currency': info.currency
                }
        except Exception as e:
            logger.error(f"Error getting account info: {str(e)}")
        return None

    def resolve_symbol(self, symbol: str) -> Optional[str]:
        """Resolve a signal symbol to the broker's MT5 symbol name."""
        try:
            if mt5.symbol_select(symbol, True):
                return symbol

            candidates = []
            for pattern in (f"{symbol}*", f"*{symbol}*"):
                matches = mt5.symbols_get(pattern) or []
                candidates.extend([match.name for match in matches])

            clean_symbol = ''.join(ch for ch in symbol.upper() if ch.isalnum())
            for candidate in candidates:
                clean_candidate = ''.join(ch for ch in candidate.upper() if ch.isalnum())
                if clean_candidate.startswith(clean_symbol):
                    if mt5.symbol_select(candidate, True):
                        logger.info(f"Resolved MT5 symbol {symbol} -> {candidate}")
                        return candidate

            logger.error(f"Could not resolve MT5 symbol {symbol}. Candidates: {candidates[:10]}")
            return None

        except Exception as e:
            logger.error(f"Error resolving symbol {symbol}: {str(e)}")
            return None

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        try:
            resolved_symbol = self.resolve_symbol(symbol)
            if not resolved_symbol:
                return None

            info = mt5.symbol_info(resolved_symbol)
            tick = mt5.symbol_info_tick(resolved_symbol)

            if info and tick:
                bid = tick.bid or info.bid
                ask = tick.ask or info.ask
                if not bid or not ask:
                    logger.error(f"Symbol {symbol} has invalid bid/ask values: bid={bid}, ask={ask}")
                    return None

                return {
                    'symbol': resolved_symbol,
                    'source_symbol': symbol,
                    'bid': bid,
                    'ask': ask,
                    'spread': info.spread,
                    'digits': info.digits,
                    'point': info.point,
                    'volume_min': info.volume_min,
                    'volume_max': info.volume_max,
                    'volume_step': info.volume_step,
                    'trade_mode': info.trade_mode,
                    'filling_mode': info.filling_mode,
                    'visible': info.visible,
                }

            logger.error(f"Could not get tick/symbol info for {symbol}: {mt5.last_error()}")
        except Exception as e:
            logger.error(f"Error getting symbol info for {symbol}: {str(e)}")
        return None

    def get_positions(self) -> List[Dict]:
        try:
            positions = mt5.positions_get()
            if positions:
                return [{
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'type': 'BUY' if pos.type == 0 else 'SELL',
                    'volume': pos.volume,
                    'price_open': pos.price_open,
                    'price_current': pos.price_current,
                    'profit': pos.profit,
                    'sl': pos.sl,
                    'tp': pos.tp
                } for pos in positions]
        except Exception as e:
            logger.error(f"Error getting positions: {str(e)}")
        return []
