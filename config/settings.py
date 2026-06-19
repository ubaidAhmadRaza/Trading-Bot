from pydantic_settings import BaseSettings
from typing import Optional, List
from enum import Enum


class TradingMode(str, Enum):
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class Settings(BaseSettings):
    # Telegram Settings (Optional for testing)
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_PHONE: Optional[str] = None
    TELEGRAM_CHANNELS: Optional[List[str]] = None
    
    # Telegram Bot for Notifications (Optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_NOTIFY_CHAT_ID: Optional[str] = None

    # MT5 Settings (Optional for testing)
    MT5_LOGIN: Optional[int] = None
    MT5_PASSWORD: Optional[str] = None
    MT5_SERVER: Optional[str] = None
    MT5_PATH: Optional[str] = None

    # Trading Settings
    TRADING_MODE: TradingMode = TradingMode.PAPER
    MAX_POSITION_SIZE: float = 0.1
    MAX_DAILY_TRADES: int = 10
    STOP_LOSS_PIPS: int = 50
    TAKE_PROFIT_PIPS: int = 100
    MIN_SIGNAL_CONFIDENCE: float = 0.7

    # Risk Management
    MAX_DRAWDOWN_PERCENT: float = 5.0
    RISK_PER_TRADE_PERCENT: float = 1.0

    # Pipeline Settings
    SIGNAL_POLL_INTERVAL: int = 5  # seconds
    ORDER_TIMEOUT: int = 30  # seconds
    MAX_RETRIES: int = 3
    # Signal lifecycle
    SIGNAL_EXPIRY_SECONDS: int = 600  # seconds before a pending signal expires (default 10 minutes)
    # Testing / dev override - when true, bypass entry confirmation and place trades when zone is reached
    ENABLE_BYPASS_ENTRY_CONFIRMATION: bool = True

    # Enhanced Pipeline Settings
    FIXED_LOT_SIZE: float = 0.29
    MAX_OPEN_POSITIONS: int = 15
    ENABLE_ENTRY_CONFIRMATION: bool = True
    ENABLE_RUNNER_MODE: bool = True
    ENABLE_BREAK_EVEN: bool = True
    
    # Entry Confirmation thresholds
    MIN_M5_REJECTION_CANDLE: bool = True
    MIN_BOS_REQUIRED: bool = True
    EMA_CONFIRMATION_REQUIRED: bool = True

    # Monitoring
    ENABLE_METRICS: bool = False
    REDIS_URL: Optional[str] = None
    ENABLE_NOTIFICATIONS: bool = False
    DATABASE_PATH: str = "data/trading_bot.db"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
