#!/usr/bin/env python3
"""
Enhanced Telegram → MT5 Trading Bot
Supports Format 1 & 2 signals with entry confirmation and runner mode
"""
import asyncio
import signal
import sys
import json
from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def main():
    """Main entry point for the enhanced trading bot"""
    
    logger.info("=" * 50)
    logger.info("Starting Enhanced Trading Bot")
    logger.info("=" * 50)
    
    # Check for required credentials
    if not all([
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
        settings.TELEGRAM_PHONE,
        settings.TELEGRAM_CHANNELS,
        settings.MT5_LOGIN,
        settings.MT5_PASSWORD,
        settings.MT5_SERVER
    ]):
        logger.error("❌ Missing required credentials!")
        logger.info("""
        
        ✅ TO RUN THE BOT:

        1. Copy .env.example to .env:
           cp .env.example .env

        2. Fill in required fields:
           - TELEGRAM_API_ID
           - TELEGRAM_API_HASH
           - TELEGRAM_PHONE
           - TELEGRAM_CHANNELS
           - MT5_LOGIN
           - MT5_PASSWORD
           - MT5_SERVER

        3. Optional but recommended:
           - TELEGRAM_BOT_TOKEN (for notifications)
           - TELEGRAM_NOTIFY_CHAT_ID (for notifications)

        4. Run again:
           python main.py
        """)
        sys.exit(1)
    
    # Parse channels from environment
    try:
        if isinstance(settings.TELEGRAM_CHANNELS, str):
            channels = json.loads(settings.TELEGRAM_CHANNELS)
        else:
            channels = settings.TELEGRAM_CHANNELS or []
    except Exception as e:
        logger.error(f"Error parsing TELEGRAM_CHANNELS: {e}")
        channels = []

    # Import here to avoid import errors if settings are missing
    from src.pipeline.enhanced_orchestrator import EnhancedTradingPipeline

    # Initialize pipeline
    pipeline = EnhancedTradingPipeline(
        telegram_api_id=settings.TELEGRAM_API_ID,
        telegram_api_hash=settings.TELEGRAM_API_HASH,
        telegram_phone=settings.TELEGRAM_PHONE,
        telegram_channels=channels,
        telegram_bot_token=settings.TELEGRAM_BOT_TOKEN,
        telegram_notify_chat_id=settings.TELEGRAM_NOTIFY_CHAT_ID,
        mt5_login=settings.MT5_LOGIN,
        mt5_password=settings.MT5_PASSWORD,
        mt5_server=settings.MT5_SERVER,
        mt5_path=settings.MT5_PATH,
        fixed_lot_size=settings.FIXED_LOT_SIZE,
        max_positions=settings.MAX_OPEN_POSITIONS,
        enable_notifications=settings.ENABLE_NOTIFICATIONS,
        db_path=settings.DATABASE_PATH
    )

    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(pipeline.stop())
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await pipeline.start()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        await pipeline.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
