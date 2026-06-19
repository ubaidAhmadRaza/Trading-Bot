import MetaTrader5 as mt5
from typing import Optional, Dict
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_fixed
from src.utils.logger import get_logger
from src.mt5_integration.mt5_client import MT5Client

logger = get_logger(__name__)


class OrderManager:
    def __init__(self, mt5_client: MT5Client):
        self.mt5_client = mt5_client

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    def place_order(self, signal: Dict) -> Optional[int]:
        """Place a trading order with retry logic"""
        try:
            symbol = signal['symbol']
            action = signal['action']
            volume = signal.get('volume', 0.01)
            sl = signal.get('sl') or signal.get('stop_loss')
            tp = signal.get('tp') or signal.get('take_profit') or (signal.get('take_profits') or [None])[0]

            symbol_info = self.mt5_client.get_symbol_info(symbol)
            if not symbol_info:
                logger.error(f"Could not get symbol info for {symbol}")
                return None

            order_type = mt5.ORDER_TYPE_BUY if action.upper() == 'BUY' else mt5.ORDER_TYPE_SELL
            price = symbol_info['ask'] if order_type == mt5.ORDER_TYPE_BUY else symbol_info['bid']

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": f"Telegram Signal {datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            if sl:
                request["sl"] = sl
            if tp:
                request["tp"] = tp

            logger.debug(f"Placing order request: {request}")

            # Ensure symbol is selected in Market Watch (helps avoid 'invalid symbol' issues)
            try:
                selected = mt5.symbol_select(symbol, True)
                logger.debug(f"mt5.symbol_select({symbol}) -> {selected}")
            except Exception as e:
                logger.debug(f"symbol_select error for {symbol}: {e}")

            result = mt5.order_send(request)

            if result is None:
                last = mt5.last_error()
                logger.error(f"mt5.order_send returned None for {symbol}. last_error: {last}")
                return None

            logger.debug(f"mt5.order_send result: retcode={getattr(result, 'retcode', None)}, comment={getattr(result, 'comment', None)}, raw={result}")

            if getattr(result, 'retcode', None) != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Order failed: {getattr(result, 'comment', None)} (retcode: {getattr(result, 'retcode', None)}) | last_error: {mt5.last_error()}")
                return None

            logger.info(f"Order placed successfully: Ticket {getattr(result, 'order', None)}, Price: {price}")
            return getattr(result, 'order', None)

        except Exception as e:
            logger.error(f"Error placing order: {str(e)}")
            return None

    def close_position(self, position_ticket: int) -> bool:
        """Close an open position"""
        try:
            position = mt5.positions_get(ticket=position_ticket)
            if not position:
                logger.error(f"Position {position_ticket} not found")
                return False

            position = position[0]
            symbol = position.symbol
            volume = position.volume

            order_type = mt5.ORDER_TYPE_SELL if position.type == 0 else mt5.ORDER_TYPE_BUY
            symbol_info = self.mt5_client.get_symbol_info(symbol)
            price = symbol_info['bid'] if order_type == mt5.ORDER_TYPE_SELL else symbol_info['ask']

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": position_ticket,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": "Close via Telegram Signal",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)

            if result is None:
                logger.error(f"mt5.order_send returned None when closing position {position_ticket}. last_error: {mt5.last_error()}")
                return False

            if getattr(result, 'retcode', None) != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Failed to close position: {getattr(result, 'comment', None)} | last_error: {mt5.last_error()}")
                return False

            logger.info(f"Position {position_ticket} closed successfully")
            return True

        except Exception as e:
            logger.error(f"Error closing position: {str(e)}")
            return False
