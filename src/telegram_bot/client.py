from telethon import TelegramClient, events
from typing import Callable, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramSignalClient:
    def __init__(self, api_id: int, api_hash: str, phone: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client: Optional[TelegramClient] = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def connect(self):
        """Connect to Telegram with retry logic"""
        try:
            self.client = TelegramClient('session', self.api_id, self.api_hash)
            await self.client.start(phone=self.phone)
            logger.info("Successfully connected to Telegram")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Telegram: {str(e)}")
            raise

    async def listen_channels(self, channels: list, callback: Callable):
        """Listen to multiple Telegram channels (supports private groups)"""
        if not self.client:
            raise ValueError("Client not connected. Call connect() first.")

        valid_channels = []
        
        for channel in channels:
            try:
                # Try to resolve as entity first (for usernames and cached entities)
                try:
                    entity = await self.client.get_input_entity(channel)
                    valid_channels.append(entity)
                    logger.info(f"✅ Resolved channel: {channel}")
                except (ValueError, TypeError):
                    # If resolution fails, try using channel ID directly
                    # Convert to int if it's a string number
                    if isinstance(channel, str):
                        try:
                            channel_id = int(channel)
                            valid_channels.append(channel_id)
                            logger.info(f"✅ Using channel ID directly: {channel}")
                        except ValueError:
                            # Not a number, re-raise original error
                            raise ValueError(f'Cannot resolve channel: {channel}')
                    else:
                        raise
            except Exception as e:
                logger.warning(f"⚠️  Cannot access channel '{channel}': {str(e)}")
                logger.info(f"   Tip: Ensure you're a member of this channel and it exists")
                continue

        if not valid_channels:
            logger.error("❌ No valid channels to listen to!")
            logger.info("""
            CHANNEL CONFIGURATION HELP:
            
            1. Channel by Username (e.g., "mytrading_signals"):
               TELEGRAM_CHANNELS=["mytrading_signals"]
            
            2. Channel by ID (e.g., "-1001234567890"):
               TELEGRAM_CHANNELS=["-1001234567890"]
               (Must be a member of the channel)
            
            3. Multiple Channels:
               TELEGRAM_CHANNELS=["channel1", "channel2", "-1001234567890"]
            
            💡 To find channel ID:
               - Forward a message from the channel to @userinfobot
               - It will show the channel ID
            """)
            raise ValueError("No valid channels configured")

        logger.info(f"✅ Listening to {len(valid_channels)} channels")

        @self.client.on(events.NewMessage(chats=valid_channels))
        async def message_handler(event):
            try:
                message = event.message
                await callback(message)
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}",
                             extra={'extra_data': {'channel': event.chat_id}})

        await self.client.run_until_disconnected()

    async def get_recent_messages(self, channel: str, limit: int = 100):
        """Fetch recent messages from a channel for backfill"""
        try:
            messages = []
            async for message in self.client.iter_messages(channel, limit=limit):
                if message.text:
                    messages.append({
                        'id': message.id,
                        'date': message.date,
                        'text': message.text,
                        'channel': channel
                    })
            return messages
        except Exception as e:
            logger.error(f"Error fetching messages from {channel}: {str(e)}")
            return []
