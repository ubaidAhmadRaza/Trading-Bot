from prometheus_client import Counter, Gauge, Histogram, start_http_server
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    def __init__(self, port: int = 8000):
        self.port = port

        self.trades_executed = Counter(
            'trades_executed_total',
            'Total number of trades executed',
            ['symbol', 'action']
        )

        self.trade_volume = Counter(
            'trade_volume_total',
            'Total trading volume',
            ['symbol']
        )

        self.active_positions = Gauge(
            'active_positions',
            'Number of active positions',
            ['symbol']
        )

        self.account_balance = Gauge(
            'account_balance',
            'Current account balance'
        )

        self.signal_latency = Histogram(
            'signal_processing_latency_seconds',
            'Time to process a signal',
            buckets=[0.1, 0.5, 1, 2, 5, 10]
        )

        self.errors = Counter(
            'errors_total',
            'Total number of errors',
            ['type']
        )

        try:
            start_http_server(port)
            logger.info(f"Metrics server started on port {port}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {str(e)}")

    def record_trade(self, symbol: str, action: str, volume: float):
        self.trades_executed.labels(symbol=symbol, action=action).inc()
        self.trade_volume.labels(symbol=symbol).inc(volume)

    def update_positions(self, positions: list):
        symbols = {}
        for pos in positions:
            symbols[pos['symbol']] = symbols.get(pos['symbol'], 0) + 1
        for symbol, count in symbols.items():
            self.active_positions.labels(symbol=symbol).set(count)

    def update_balance(self, balance: float):
        self.account_balance.set(balance)

    def record_latency(self, seconds: float):
        self.signal_latency.observe(seconds)

    def record_error(self, error_type: str):
        self.errors.labels(type=error_type).inc()
