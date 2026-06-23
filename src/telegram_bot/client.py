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

        # Force full dialog sync first to prevent slow channel resolution
        logger.info("Syncing dialogs...")
        await self.client.get_dialogs()
        logger.info("Dialogs synced")

        valid_channels = []
        
        for channel in channels:
            try:
                try:
                    entity = await self.client.get_input_entity(channel)
                    valid_channels.append(entity)
                    logger.info(f"✅ Resolved channel: {channel}")
                except (ValueError, TypeError):
                    if isinstance(channel, str):
                        try:
                            channel_id = int(channel)
                            valid_channels.append(channel_id)
                            logger.info(f"✅ Using channel ID directly: {channel}")
                        except ValueError:
                            raise ValueError(f'Cannot resolve channel: {channel}')
                    else:
                        raise
            except Exception as e:
                logger.warning(f"⚠️  Cannot access channel '{channel}': {str(e)}")
                continue

        if not valid_channels:
            logger.error("❌ No valid channels to listen to!")
            raise ValueError("No valid channels configured")

        logger.info(f"✅ Listening to {len(valid_channels)} channels")

        @self.client.on(events.NewMessage(chats=valid_channels, incoming=None))
        async def message_handler(event):
            try:
                message = event.message
                text = message.text or message.message or ''
                print(f"RAW MESSAGE from {event.chat_id}: {text[:200] if text else 'NO TEXT (may be image-only)'}")
                await callback(message)
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}",
                             extra={'extra_data': {'channel': event.chat_id}})

        @self.client.on(events.MessageEdited(chats=valid_channels))
        async def edited_message_handler(event):
            try:
                message = event.message
                text = message.text or message.message or ''
                logger.info(f"📝 Edited message detected in channel {event.chat_id}")
                await callback(message)
            except Exception as e:
                logger.error(f"Error processing edited message: {str(e)}",
                             extra={'extra_data': {'channel': event.chat_id}})

        # Catch up on any missed messages
        await self.client.catch_up()
        logger.info("Catch-up complete — now listening live")
        
        await self.client.run_until_disconnected()

    async def backfill_messages(self, channels: list, callback: Callable, limit: int = 10):
        """Fetch recent messages from all channels before live listening starts"""
        for channel in channels:
            try:
                messages = await self.get_recent_messages(channel, limit=limit)
                logger.info(f"📥 Backfilled {len(messages)} messages from {channel}")
                for msg in messages:
                    await callback(msg)
            except Exception as e:
                logger.error(f"Error backfilling {channel}: {str(e)}")

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