#!/usr/bin/env python3
"""
MT5 Connection Diagnostic Script
Run this to identify MT5 connection issues
"""
import sys
from pathlib import Path
from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def check_mt5_installed():
    """Check if MetaTrader5 is installed"""
    print("\n" + "="*60)
    print("STEP 1: Checking if MetaTrader5 is Installed")
    print("="*60)
    
    common_paths = [
        Path("C:/Program Files/MetaTrader 5/terminal64.exe"),
        Path("C:/Program Files (x86)/MetaTrader 5/terminal64.exe"),
        Path("C:/MetaTrader5/terminal64.exe"),
    ]
    
    found = False
    for path in common_paths:
        if path.exists():
            print(f"✅ Found MT5 at: {path}")
            found = True
            return str(path)
    
    if not found:
        print("❌ MetaTrader5 NOT found in common locations:")
        for path in common_paths:
            print(f"   - {path}")
        print("\n💡 SOLUTION: Download MetaTrader5 from https://www.metatrader5.com/")
        return None
    
    return None


def check_mt5_credentials():
    """Check if MT5 credentials are configured"""
    print("\n" + "="*60)
    print("STEP 2: Checking MT5 Credentials")
    print("="*60)
    
    credentials = {
        'MT5_LOGIN': settings.MT5_LOGIN,
        'MT5_PASSWORD': settings.MT5_PASSWORD,
        'MT5_SERVER': settings.MT5_SERVER,
        'MT5_PATH': settings.MT5_PATH,
    }
    
    for key, value in credentials.items():
        if value:
            if 'PASSWORD' in key:
                print(f"✅ {key}: {'*' * len(str(value))}")
            else:
                print(f"✅ {key}: {value}")
        else:
            print(f"⚠️  {key}: Not configured")
    
    if not all([settings.MT5_LOGIN, settings.MT5_PASSWORD, settings.MT5_SERVER]):
        print("\n❌ Missing credentials! Add to .env:")
        print("   MT5_LOGIN=123456")
        print("   MT5_PASSWORD=your_password")
        print("   MT5_SERVER=ICMarkets-Demo")
        return False
    
    return True


def check_mt5_connection():
    """Check if MT5 terminal is running and accessible"""
    print("\n" + "="*60)
    print("STEP 3: Checking MT5 Connection")
    print("="*60)
    
    try:
        import MetaTrader5 as mt5
        print("✅ MetaTrader5 module imported successfully")
        
        # Try to initialize
        print("Attempting to initialize MT5...")
        
        if settings.MT5_PATH:
            print(f"Using custom path: {settings.MT5_PATH}")
            result = mt5.initialize(settings.MT5_PATH)
        else:
            print("Using default MT5 installation")
            result = mt5.initialize()
        
        if result:
            print("✅ MT5 initialized successfully!")
            
            # Try to login
            print(f"Attempting to login to {settings.MT5_SERVER}...")
            authorized = mt5.login(
                login=settings.MT5_LOGIN,
                password=settings.MT5_PASSWORD,
                server=settings.MT5_SERVER
            )
            
            if authorized:
                print("✅ Successfully logged in to MT5!")
                
                # Get account info
                account_info = mt5.account_info()
                if account_info:
                    print(f"\n📊 Account Information:")
                    print(f"   Balance: {account_info.balance}")
                    print(f"   Equity: {account_info.equity}")
                    print(f"   Currency: {account_info.currency}")
                
                mt5.shutdown()
                return True
            else:
                error = mt5.last_error()
                print(f"❌ Login failed: {error}")
                return False
        else:
            error = mt5.last_error()
            print(f"❌ MT5 initialization failed: {error}")
            print("\n💡 POSSIBLE CAUSES:")
            print("   1. MetaTrader5 terminal is not running")
            print("   2. MT5 path is incorrect (if custom path set)")
            print("   3. MT5 is not installed")
            return False
            
    except ImportError:
        print("❌ MetaTrader5 module not installed!")
        print("   Install with: pip install MetaTrader5")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def print_summary():
    """Print diagnostic summary"""
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    
    print("\n📋 CHECKLIST:")
    
    mt5_path = check_mt5_installed()
    print("")
    
    creds_ok = check_mt5_credentials()
    print("")
    
    connection_ok = check_mt5_connection()
    
    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("="*60)
    
    if not mt5_path:
        print("\n1️⃣  INSTALL MetaTrader5:")
        print("   Download from: https://www.metatrader5.com/")
        print("   Install to: C:\\Program Files\\MetaTrader 5\\")
    
    if not creds_ok:
        print("\n2️⃣  CONFIGURE CREDENTIALS:")
        print("   $ cp .env.example .env")
        print("   Edit .env with your MT5 account details")
    
    if not connection_ok:
        print("\n3️⃣  START MetaTrader5 Terminal:")
        print("   Launch MT5 and log in with your account")
        print("   Keep it running while the bot is running")
    
    print("\n4️⃣  RUN THE BOT:")
    print("   $ python main.py")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    print("\n🔍 MT5 CONNECTION DIAGNOSTIC")
    print("="*60)
    
    try:
        print_summary()
    except Exception as e:
        print(f"\n❌ Diagnostic error: {e}")
        sys.exit(1)
