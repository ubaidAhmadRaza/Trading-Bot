#!/usr/bin/env python3
"""
Telegram Channel Finder Script
Use this to get the correct channel IDs for your bot configuration
"""
import asyncio
import json
from telethon import TelegramClient, events
from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def find_channels():
    """Find all channels you're a member of"""
    
    if not all([settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.TELEGRAM_PHONE]):
        logger.error("❌ Missing Telegram credentials!")
        logger.info("""
        Configure in .env:
        - TELEGRAM_API_ID
        - TELEGRAM_API_HASH
        - TELEGRAM_PHONE
        """)
        return

    print("\n" + "="*70)
    print("TELEGRAM CHANNEL FINDER")
    print("="*70)
    print(f"\nConnecting as: {settings.TELEGRAM_PHONE}")
    print("This will list all channels you're a member of...\n")

    client = TelegramClient('session', settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    
    try:
        await client.start(phone=settings.TELEGRAM_PHONE)
        logger.info("✅ Connected to Telegram")
        
        # Get all dialogs (chats, channels, etc.)
        channels_found = []
        
        print("Fetching your channels and groups...")
        print("-" * 70)
        
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            
            # Filter for channels and supergroups (public trading channels)
            if hasattr(entity, 'broadcast') or (hasattr(entity, 'megagroup') and entity.megagroup):
                channel_id = entity.id
                channel_name = dialog.name or "Unknown"
                
                # Get channel username if available
                username = getattr(entity, 'username', None)
                
                info = {
                    'name': channel_name,
                    'id': channel_id,
                    'username': username,
                    'is_broadcast': getattr(entity, 'broadcast', False),
                    'is_megagroup': getattr(entity, 'megagroup', False),
                }
                
                channels_found.append(info)
                
                print(f"\n📺 Channel: {channel_name}")
                print(f"   ID: {channel_id}")
                if username:
                    print(f"   Username: @{username}")
                print(f"   Type: {'Broadcast' if info['is_broadcast'] else 'Megagroup'}")
        
        if channels_found:
            print("\n" + "="*70)
            print("CONFIGURATION")
            print("="*70)
            
            print("\nCopy one of these to your .env file:")
            print("\nOption 1: Use Channel IDs")
            ids = [str(ch['id']) for ch in channels_found]
            print(f'TELEGRAM_CHANNELS={json.dumps(ids)}')
            
            print("\nOption 2: Use Channel Usernames (if available)")
            usernames = [f"@{ch['username']}" for ch in channels_found if ch['username']]
            if usernames:
                print(f'TELEGRAM_CHANNELS={json.dumps(usernames)}')
            else:
                print("(No public usernames found)")
            
            print("\nOption 3: Mix IDs and Usernames")
            mixed = []
            for ch in channels_found:
                if ch['username']:
                    mixed.append(f"@{ch['username']}")
                else:
                    mixed.append(str(ch['id']))
            print(f'TELEGRAM_CHANNELS={json.dumps(mixed)}')
        else:
            print("\n❌ No channels found!")
            print("\nMake sure you're a member of the channels you want to monitor.")
            print("Then run this script again.")
        
        print("\n" + "="*70)
        print("NEXT STEPS")
        print("="*70)
        print("\n1. Copy one of the configuration options above")
        print("2. Paste into your .env file as TELEGRAM_CHANNELS")
        print("3. Run: python main.py")
        print("\n" + "="*70 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(find_channels())
