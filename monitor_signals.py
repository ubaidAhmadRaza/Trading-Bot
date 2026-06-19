#!/usr/bin/env python3
"""
Monitor pending signals and their lifecycle in real-time
"""
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from config.settings import settings

def load_signals():
    """Load signals from JSON"""
    signals_file = Path(settings.DATABASE_PATH).parent / "signals.json"
    if signals_file.exists():
        return json.loads(signals_file.read_text())
    return []

def load_trades():
    """Load trades from JSON"""
    trades_file = Path(settings.DATABASE_PATH).parent / "trades.json"
    if trades_file.exists():
        return json.loads(trades_file.read_text())
    return []

def print_signal_status(signals):
    """Print all signals with status"""
    if not signals:
        print("No signals found")
        return
    
    print("\n" + "="*80)
    print("SIGNAL STATUS MONITOR")
    print("="*80)
    
    # Count by status
    statuses = {}
    for signal in signals:
        status = signal.get('status', 'unknown')
        statuses[status] = statuses.get(status, 0) + 1
    
    print(f"\nSignal Summary:")
    print(f"  Pending:  {statuses.get('pending', 0)}")
    print(f"  Zone Hit: {statuses.get('zone_reached', 0)}")
    print(f"  Expired:  {statuses.get('expired', 0)}")
    print(f"  Traded:   {statuses.get('traded', 0)}")
    print(f"  Failed:   {statuses.get('trade_failed', 0)}")
    print(f"  Total:    {len(signals)}")
    
    # Show pending signals
    pending = [s for s in signals if s.get('status') == 'pending']
    if pending:
        print(f"\nPENDING SIGNALS ({len(pending)}):")
        print("-" * 80)
        
        for sig in pending:
            received = datetime.fromisoformat(sig['received_at'])
            age = datetime.utcnow() - received
            expires_in = settings.SIGNAL_EXPIRY_SECONDS - age.total_seconds()
            
            print(f"\n  ID: {sig['id']} | {sig['symbol']} {sig['action']}")
            print(f"  Zone: {sig['entry_zone_min']}-{sig['entry_zone_max']}")
            print(f"  Age: {age.total_seconds():.0f}s | Expires in: {max(0, expires_in):.0f}s")
            print(f"  Received: {sig['received_at']}")
            
            if expires_in <= 0:
                print(f"  SHOULD EXPIRE NOW!")
    
    # Show expired signals
    expired = [s for s in signals if s.get('status') == 'expired']
    if expired:
        print(f"\n\nEXPIRED SIGNALS ({len(expired)}):")
        print("-" * 80)
        
        for sig in expired:
            print(f"\n  ID: {sig['id']} | {sig['symbol']} {sig['action']}")
            print(f"  Reason: {sig.get('expiry_reason', 'unknown')}")
            print(f"  Expired at: {sig.get('expired_at', 'unknown')}")

    failed = [s for s in signals if s.get('status') == 'trade_failed']
    if failed:
        print(f"\n\nFAILED TRADE ATTEMPTS ({len(failed)}):")
        print("-" * 80)

        for sig in failed:
            print(f"\n  ID: {sig['id']} | {sig['symbol']} {sig['action']}")
            print(f"  Reason: {sig.get('failure_reason', 'unknown')}")
            print(f"  Failed at: {sig.get('failed_at', 'unknown')}")
    
    # Show traded signals
    trades = load_trades()
    traded = [s for s in signals if s.get('status') == 'traded' or s['id'] in [t.get('signal_id') for t in trades]]
    if traded:
        print(f"\n\nTRADED SIGNALS ({len(traded)}):")
        print("-" * 80)
        
        for sig in traded:
            # Find associated trade
            trade = next((t for t in trades if t.get('signal_id') == sig['id']), None)
            if trade:
                print(f"\n  ID: {sig['id']} | {sig['symbol']} {sig['action']}")
                print(f"  Trade Ticket: {trade['ticket']}")
                print(f"  Entry Price: {trade['entry_price']}")
                print(f"  Status: {trade.get('status', 'unknown')}")

def watch_signals(interval=5):
    """Watch signals and refresh every N seconds"""
    try:
        while True:
            signals = load_signals()
            print_signal_status(signals)
            
            print(f"\nNext refresh in {interval}s... (Press Ctrl+C to stop)")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\nStopped monitoring")

if __name__ == "__main__":
    import sys
    
    print("\nSIGNAL TRACKING MONITOR")
    print("="*80)
    print("This tool shows:")
    print("  - Pending signals waiting for zone entry")
    print("  - Signals that expired (not entered zone within timeout)")
    print("  - Signals that resulted in trades")
    print("\nDatabase paths:")
    print(f"  Signals: data/signals.json")
    print(f"  Trades:  data/trades.json")
    print(f"\nSettings:")
    print(f"  Poll Interval: {settings.SIGNAL_POLL_INTERVAL}s")
    print(f"  Expiry Time:  {settings.SIGNAL_EXPIRY_SECONDS}s")
    print(f"  Bypass Confirmation: {settings.ENABLE_BYPASS_ENTRY_CONFIRMATION}")
    print("="*80)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--watch":
        # Watch mode - refresh every 5 seconds
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        watch_signals(interval)
    else:
        # Single snapshot
        signals = load_signals()
        print_signal_status(signals)
