"""
Telegram Notification System
Sends notifications for:
- Signal received
- Zone reached
- Trade opened
- Break-even activated
- TP reached
- Runner mode activated
- Trade closed
- Error messages
"""
import asyncio
from turtle import title
from typing import Optional, List
from datetime import datetime
from enum import Enum
from telegram import Bot
from telegram.error import TelegramError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationType(str, Enum):
    """Types of notifications"""
    SIGNAL_RECEIVED = "signal_received"
    ZONE_REACHED = "zone_reached"
    TRADE_OPENED = "trade_opened"
    BE_ACTIVATED = "be_activated"
    TP_REACHED = "tp_reached"
    RUNNER_MODE = "runner_mode"
    TRADE_CLOSED = "trade_closed"
    ERROR = "error"
    INFO = "info"


class NotificationManager:
    """
    Manages Telegram notifications for trading events
    """

    def __init__(self, bot_token: str, notification_chat_id: str):
        """
        Args:
            bot_token: Telegram bot token
            notification_chat_id: Chat ID to send notifications
        """
        self.bot = Bot(token=bot_token)
        self.chat_id = notification_chat_id
        self.notification_queue = []

    async def send_notification(
        self,
        notification_type: NotificationType,
        title: str,
        details: dict,
        emoji: Optional[str] = None
    ) -> bool:
        """
        Send a formatted notification

        Args:
            notification_type: Type of notification
            title: Notification title
            details: Dictionary of details to include
            emoji: Optional emoji prefix

        Returns:
            True if sent successfully
        """
        try:
            message = self._format_notification(notification_type, title, details, emoji)
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            logger.debug(f"Notification sent: {title}")
            return True

        except TelegramError as e:
            logger.error(f"Failed to send Telegram notification: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error in send_notification: {str(e)}")
            return False

    async def send_signal_received(
        self,
        symbol: str,
        action: str,
        entry_zone: dict,
        stop_loss: float,
        take_profits: List[float]
    ) -> bool:
        """Signal received notification"""
        details = {
            'Symbol': symbol,
            'Action': f"🔵 {action}" if action.upper() == 'BUY' else f"🔴 {action}",
            'Entry Zone': f"{entry_zone['min']} - {entry_zone['max']}",
            'Stop Loss': f"{stop_loss}",
            'Take Profits': ', '.join([f"{tp}" for tp in take_profits])
        }
        return await self.send_notification(
            NotificationType.SIGNAL_RECEIVED,
            f"📊 New Signal: {symbol}",
            details,
            "📊"
        )

    async def send_zone_reached(
        self,
        symbol: str,
        action: str,
        current_price: float
    ) -> bool:
        """Zone reached notification"""
        details = {
            'Symbol': symbol,
            'Action': action,
            'Current Price': f"{current_price}"
        }
        return await self.send_notification(
            NotificationType.ZONE_REACHED,
            f"🎯 Entry Zone Reached: {symbol}",
            details,
            "🎯"
        )

    async def send_trade_opened(
        self,
        ticket: int,
        symbol: str,
        action: str,
        entry_price: float,
        volume: float,
        stop_loss: float
    ) -> bool:
        """Trade opened notification"""
        details = {
            'Ticket': ticket,
            'Symbol': symbol,
            'Action': action,
            'Entry Price': f"{entry_price}",
            'Volume': f"{volume}",
            'Stop Loss': f"{stop_loss}"
        }
        return await self.send_notification(
            NotificationType.TRADE_OPENED,
            f"✅ Trade Opened: {symbol}",
            details,
            "✅"
        )

    async def send_be_activated(
        self,
        ticket: int,
        symbol: str,
        entry_price: float
    ) -> bool:
        """Break-even activated notification"""
        details = {
            'Ticket': ticket,
            'Symbol': symbol,
            'New SL': f"{entry_price}"
        }
        return await self.send_notification(
            NotificationType.BE_ACTIVATED,
            f"🛡️ Break-Even Activated: {symbol}",
            details,
            "🛡️"
        )

    async def send_tp_reached(
        self,
        ticket: int,
        symbol: str,
        tp_level: float,
        profit: float
    ) -> bool:
        """Take profit reached notification"""
        details = {
            'Ticket': ticket,
            'Symbol': symbol,
            'TP Level': f"{tp_level}",
            'Profit': f"${profit:.2f}" if profit > 0 else f"-${abs(profit):.2f}"
        }
        return await self.send_notification(
            NotificationType.TP_REACHED,
            f"🎊 Take Profit Reached: {symbol}",
            details,
            "🎊"
        )

    async def send_runner_mode_activated(
        self,
        ticket: int,
        symbol: str,
        trailing_stop: float
    ) -> bool:
        """Runner mode activated notification"""
        details = {
            'Ticket': ticket,
            'Symbol': symbol,
            'Trailing Stop': f"{trailing_stop}"
        }
        return await self.send_notification(
            NotificationType.RUNNER_MODE,
            f"🚀 Runner Mode: {symbol}",
            details,
            "🚀"
        )

    async def send_trade_closed(
        self,
        ticket: int,
        symbol: str,
        close_price: float,
        profit: float,
        profit_percent: float
    ) -> bool:
        """Trade closed notification"""
        profit_str = f"${profit:.2f}" if profit > 0 else f"-${abs(profit):.2f}"
        details = {
            'Ticket': ticket,
            'Symbol': symbol,
            'Close Price': f"{close_price}",
            'Profit/Loss': profit_str,
            'Profit %': f"{profit_percent:.2f}%"
        }
        return await self.send_notification(
            NotificationType.TRADE_CLOSED,
            f"🏁 Trade Closed: {symbol}",
            details,
            "🏁"
        )

    async def send_error(self, error_message: str) -> bool:
        """Error notification"""
        details = {
            'Error': error_message,
            'Time': datetime.utcnow().isoformat()
        }
        return await self.send_notification(
            NotificationType.ERROR,
            "⚠️ Error Occurred",
            details,
            "⚠️"
        )

    async def send_info(self, title: str, info_dict: dict) -> bool:
        """General info notification"""
        return await self.send_notification(
            NotificationType.INFO,
            title,
            info_dict,
            "ℹ️"
        )

    def _format_notification(
        self,
        notification_type: NotificationType,
        title: str,
        details: dict,
        emoji: Optional[str] = None
    ) -> str:
        """Format notification message"""
        message = f"<b>{emoji} {title}</b>\n\n"

        for key, value in details.items():
            message += f"<b>{key}:</b> {value}\n"

        message += f"\n<i>Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"

        return message


class DummyNotificationManager:
    """
    Dummy notification manager for testing (no actual notifications)
    """

    async def send_notification(self, *args, **kwargs) -> bool:
        title = args[1] if len(args) > 1 else kwargs.get('title', 'Notification')
        logger.info(f"[DUMMY NOTIFICATION] {title}")
        return True

    async def send_signal_received(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_zone_reached(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_trade_opened(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_be_activated(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_tp_reached(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_runner_mode_activated(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_trade_closed(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_error(self, *args, **kwargs) -> bool:
        return await self.send_notification()

    async def send_info(self, *args, **kwargs) -> bool:
        return await self.send_notification()
