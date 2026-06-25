"""
Trading Bot Dashboard
Run with: streamlit run dashboard.py
"""
import streamlit as st
import json
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pandas as pd
import MetaTrader5 as mt5
import os

st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Dark theme CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c1f26;
        border-radius: 10px;
        padding: 16px 20px;
        border: 1px solid #2e3340;
        margin-bottom: 10px;
    }
    .metric-label { color: #8b949e; font-size: 13px; margin-bottom: 4px; }
    .metric-value { color: #e6edf3; font-size: 26px; font-weight: 700; }
    .metric-value.green { color: #3fb950; }
    .metric-value.red   { color: #f85149; }
    .metric-value.blue  { color: #58a6ff; }
    .section-title {
        color: #e6edf3;
        font-size: 16px;
        font-weight: 600;
        margin: 20px 0 10px 0;
        padding-bottom: 6px;
        border-bottom: 1px solid #2e3340;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-open     { background:#1f3d2e; color:#3fb950; }
    .badge-traded   { background:#1f3d2e; color:#3fb950; }
    .badge-pending  { background:#2d2a1f; color:#d29922; }
    .badge-expired  { background:#2a1f1f; color:#8b949e; }
    .badge-failed   { background:#2d1f1f; color:#f85149; }
    .badge-closed   { background:#1a1f2e; color:#58a6ff; }
    .badge-tp1_hit  { background:#1a2a3a; color:#58a6ff; }
    .badge-trade_failed { background:#2d1f1f; color:#f85149; }
    .badge-zone_reached { background:#1a2a3a; color:#58a6ff; }
    stDataFrame { background: #1c1f26 !important; }
</style>
""", unsafe_allow_html=True)


# ── MT5 Connection Manager ─────────────────────────────────────────────────────

def get_mt5_connection():
    """Initialize MT5 connection with proper error handling"""
    try:
        # Try to initialize MT5
        if not mt5.initialize():
            # Try with common terminal paths
            common_paths = [
                r"C:\Program Files\MetaTrader 5\terminal64.exe",
                r"C:\Program Files\MetaTrader 5\terminal.exe",
                r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
                r"C:\Program Files (x86)\MetaTrader 5\terminal.exe",
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    if mt5.initialize(path):
                        break
            
            if not mt5.initialize():
                return False, "MT5 initialization failed. Make sure MT5 is running."
        
        # Check if we're actually connected
        account_info = mt5.account_info()
        if account_info is None:
            mt5.shutdown()
            return False, "MT5 not logged in. Please login to MT5 first."
        
        return True, "Connected"
        
    except Exception as e:
        return False, f"MT5 error: {str(e)}"


def get_mt5_trades(days_back: int = 7):
    """Get both open and recent closed trades directly from MT5"""
    trades = []
    mt5_initialized = False
    
    try:
        # Initialize MT5
        initialized, msg = get_mt5_connection()
        if not initialized:
            st.warning(f"⚠️ {msg}")
            return []
        
        mt5_initialized = True
        
        # Get account info to verify connection
        account_info = mt5.account_info()
        if account_info is None:
            st.warning("⚠️ MT5 account not logged in")
            mt5.shutdown()
            return []
        
        # Get open positions
        positions = mt5.positions_get()
        if positions:
            for pos in positions:
                # Debug: Print position details
                print(f"Position {pos.ticket}: SL={pos.sl}, TP={pos.tp}, Type={pos.type}")
                
                trades.append({
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'action': 'BUY' if pos.type == 0 else 'SELL',
                    'volume': pos.volume,
                    'entry_price': pos.price_open,
                    'stop_loss': pos.sl if pos.sl else None,
                    'take_profits': [pos.tp] if pos.tp else [],
                    'status': 'open',
                    'profit_loss': pos.profit,
                    'opened_at': datetime.fromtimestamp(pos.time).isoformat(),
                    'closed_at': None,
                    'price_current': pos.price_current,
                    'comment': pos.comment if hasattr(pos, 'comment') else '',
                    'type': pos.type  # Add type for debugging
                })
        
        # Get closed trades from last N days
        from_date = datetime.now() - timedelta(days=days_back)
        deals = mt5.history_deals_get(from_date, datetime.now())
        
        if deals:
            # Group deals by position_id
            position_deals = {}
            for deal in deals:
                pos_id = deal.position_id
                if pos_id not in position_deals:
                    position_deals[pos_id] = []
                position_deals[pos_id].append(deal)
            
            # Process each position
            for pos_id, deal_list in position_deals.items():
                entry_deal = None
                exit_deal = None
                for deal in deal_list:
                    if deal.entry == 0:  # Entry
                        entry_deal = deal
                    elif deal.entry == 1:  # Exit
                        exit_deal = deal
                
                if entry_deal:
                    trade = {
                        'ticket': pos_id,
                        'symbol': entry_deal.symbol,
                        'action': 'BUY' if entry_deal.type == 0 else 'SELL',
                        'volume': entry_deal.volume,
                        'entry_price': entry_deal.price,
                        'stop_loss': None,
                        'take_profits': [],
                        'status': 'closed' if exit_deal else 'open',
                        'profit_loss': exit_deal.profit if exit_deal else 0,
                        'opened_at': datetime.fromtimestamp(entry_deal.time).isoformat(),
                        'closed_at': datetime.fromtimestamp(exit_deal.time).isoformat() if exit_deal else None,
                        'price_current': None,
                        'comment': '',
                        'type': entry_deal.type
                    }
                    trades.append(trade)
        
    except Exception as e:
        st.error(f"❌ Error reading from MT5: {str(e)}")
        return []
    
    finally:
        if mt5_initialized:
            try:
                mt5.shutdown()
            except:
                pass
    
    return trades


# ── Data loaders ───────────────────────────────────────────────────────────────

def load_json(path: str) -> list:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return []
    return []


@st.cache_data(ttl=5)
def load_all():
    """Load signals from JSON, trades directly from MT5"""
    signals = load_json("data/signals.json")
    modifications = load_json("data/modifications.json")
    errors = load_json("data/errors.json")
    
    # Get trades directly from MT5
    trades = get_mt5_trades(days_back=7)
    
    return signals, trades, modifications, errors


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Settings")
    
    st.markdown("---")
    st.markdown("### 📁 Data paths")
    data_dir = st.text_input("Data directory", value="data")
    
    st.markdown("---")
    st.markdown("### 📅 Date filter")
    today = datetime.now(timezone.utc).date()
    date_from = st.date_input("From", value=today - timedelta(days=7))
    date_to = st.date_input("To", value=today)
    
    st.markdown("---")
    st.markdown("### 🔄 Data Source")
    st.info("📊 Trades loaded directly from MT5\n📡 Signals loaded from JSON")
    
    st.markdown("---")
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()
    
    # MT5 connection status with detailed info
    st.markdown("### 📡 MT5 Status")
    initialized, msg = get_mt5_connection()
    
    if initialized:
        try:
            account_info = mt5.account_info()
            if account_info:
                st.success(f"✅ Connected\nAccount: {account_info.login}")
                st.caption(f"Balance: ${account_info.balance:.2f}")
                st.caption(f"Equity: ${account_info.equity:.2f}")
            else:
                st.warning("⚠️ Connected but no account info")
            mt5.shutdown()
        except:
            st.warning("⚠️ Connection issue")
    else:
        st.error(f"❌ {msg}")
    
    st.caption(f"Last updated: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")


# ── Load data ──────────────────────────────────────────────────────────────────

signals, trades, modifications, errors = load_all()

# Filter by date
def in_range(ts_str):
    try:
        if not ts_str:
            return False
        dt = datetime.fromisoformat(ts_str).date()
        return date_from <= dt <= date_to
    except Exception:
        return False

signals_f = [s for s in signals if in_range(s.get('received_at', ''))]
trades_f = [t for t in trades if in_range(t.get('opened_at', ''))]
errors_f = [e for e in errors if in_range(e.get('occurred_at', ''))]


# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown("# 📈 Trading Bot Dashboard")
st.markdown(f"`{date_from}` → `{date_to}`  •  Data from `{data_dir}/`  •  **Live MT5 Data**")
st.markdown("---")


# ── Top KPI row ────────────────────────────────────────────────────────────────

open_trades = [t for t in trades if t.get('status') == 'open']
closed_trades = [t for t in trades_f if t.get('status') == 'closed']
total_pl = sum(t.get('profit_loss') or 0 for t in closed_trades)
winning = [t for t in closed_trades if (t.get('profit_loss') or 0) > 0]
losing = [t for t in closed_trades if (t.get('profit_loss') or 0) < 0]
win_rate = (len(winning) / len(closed_trades) * 100) if closed_trades else 0

traded_today = [
    s for s in signals
    if s.get('status') == 'traded'
    and in_range(s.get('received_at', ''))
]

col1, col2, col3, col4, col5, col6 = st.columns(6)

def kpi(col, label, value, color=""):
    col.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-label">{label}</div>'
        f'<div class="metric-value {color}">{value}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

kpi(col1, "Open Positions", len(open_trades), "blue")
kpi(col2, "Trades Today", len(traded_today), "blue")
kpi(col3, "Closed (period)", len(closed_trades), "")
kpi(col4, "Total P&L", f"${total_pl:+.2f}", "green" if total_pl >= 0 else "red")
kpi(col5, "Win Rate", f"{win_rate:.1f}%", "green" if win_rate >= 50 else "red")
kpi(col6, "Errors (period)", len(errors_f), "red" if errors_f else "")


st.markdown("---")


# ── Row 2: Charts ──────────────────────────────────────────────────────────────

col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown('<div class="section-title">📊 Signal Status Breakdown</div>', unsafe_allow_html=True)

    status_counts = {}
    for s in signals_f:
        st_ = s.get('status', 'unknown')
        status_counts[st_] = status_counts.get(st_, 0) + 1

    if status_counts:
        colors = {
            'traded': '#3fb950',
            'pending': '#d29922',
            'expired': '#8b949e',
            'trade_failed': '#f85149',
            'zone_reached': '#58a6ff',
        }
        fig = go.Figure(go.Pie(
            labels=list(status_counts.keys()),
            values=list(status_counts.values()),
            hole=0.55,
            marker_colors=[colors.get(k, '#58a6ff') for k in status_counts.keys()],
            textfont_size=13,
        ))
        fig.update_layout(
            paper_bgcolor='#1c1f26',
            plot_bgcolor='#1c1f26',
            font_color='#e6edf3',
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=True,
            legend=dict(font=dict(color='#e6edf3')),
            height=280,
        )
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("No signals in selected period")

with col_right:
    st.markdown('<div class="section-title">🏆 Win / Loss</div>', unsafe_allow_html=True)

    fig2 = go.Figure(go.Bar(
        x=['Winning', 'Losing'],
        y=[len(winning), len(losing)],
        marker_color=['#3fb950', '#f85149'],
        text=[len(winning), len(losing)],
        textposition='auto',
    ))
    fig2.update_layout(
        paper_bgcolor='#1c1f26',
        plot_bgcolor='#1c1f26',
        font_color='#e6edf3',
        margin=dict(t=10, b=10, l=10, r=10),
        height=280,
        showlegend=False,
        yaxis=dict(gridcolor='#2e3340'),
        xaxis=dict(gridcolor='#2e3340'),
    )
    st.plotly_chart(fig2, width='stretch')


# ── P&L over time ──────────────────────────────────────────────────────────────

st.markdown('<div class="section-title">💰 Cumulative P&L</div>', unsafe_allow_html=True)

closed_with_pl = [
    t for t in trades
    if t.get('status') == 'closed'
    and t.get('profit_loss') is not None
    and t.get('closed_at')
]
closed_with_pl.sort(key=lambda t: t.get('closed_at', ''))

if closed_with_pl:
    times = [t['closed_at'] for t in closed_with_pl]
    pl_vals = [t['profit_loss'] for t in closed_with_pl]
    cumpl = []
    running = 0
    for v in pl_vals:
        running += v
        cumpl.append(running)

    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=times, y=cumpl,
        fill='tozeroy',
        line=dict(color='#3fb950' if running >= 0 else '#f85149', width=2),
        fillcolor='rgba(63,185,80,0.15)' if running >= 0 else 'rgba(248,81,73,0.15)',
        name='Cumulative P&L'
    ))
    fig3.update_layout(
        paper_bgcolor='#1c1f26',
        plot_bgcolor='#1c1f26',
        font_color='#e6edf3',
        margin=dict(t=10, b=10, l=10, r=10),
        height=220,
        yaxis=dict(gridcolor='#2e3340', title='P&L ($)'),
        xaxis=dict(gridcolor='#2e3340'),
    )
    st.plotly_chart(fig3, width='stretch')
else:
    st.info("No closed trades with P&L data yet")


st.markdown("---")


# ── Open positions table ───────────────────────────────────────────────────────

st.markdown('<div class="section-title">🟢 Open Positions (Live from MT5)</div>', unsafe_allow_html=True)

if open_trades:
    rows = []
    # Calculate total P&L for open positions
    total_open_pl = sum(t.get('profit_loss', 0) for t in open_trades)
    st.metric("Total Open P&L", f"${total_open_pl:+.2f}", 
              delta=f"{total_open_pl:+.2f}" if total_open_pl != 0 else None)
    
    for t in open_trades:
        # Format values safely
        entry = t.get('entry_price')
        current = t.get('price_current')
        sl = t.get('stop_loss')
        tp = t.get('take_profits', [None])[0] if t.get('take_profits') else None
        pl = t.get('profit_loss')
        
        rows.append({
            'Ticket': t.get('ticket'),
            'Symbol': t.get('symbol'),
            'Action': t.get('action'),
            'Volume': f"{t.get('volume'):.2f}" if t.get('volume') else '—',
            'Entry': f"{entry:.2f}" if entry else '—',
            'Current': f"{current:.2f}" if current else '—',
            'P&L': f"${pl:+.2f}" if pl is not None else '—',
            'SL': f"{sl:.2f}" if sl else '—',
            'TP': f"{tp:.2f}" if tp else '—',
            'Opened': t.get('opened_at', '')[:16] if t.get('opened_at') else '',
        })
    st.dataframe(
        pd.DataFrame(rows),
        width='stretch',
        hide_index=True
    )
else:
    st.info("No open positions")


# ── Signals table ──────────────────────────────────────────────────────────────

st.markdown('<div class="section-title">📡 Signals (period)</div>', unsafe_allow_html=True)

def badge(status):
    cls = f"badge-{status.replace(' ', '_')}"
    return f'<span class="status-badge {cls}">{status}</span>'

if signals_f:
    rows = []
    for s in reversed(signals_f):
        rows.append({
            'ID': s.get('id'),
            'Symbol': s.get('symbol'),
            'Action': s.get('action'),
            'Status': s.get('status'),
            'Zone': f"{s.get('entry_zone_min')} – {s.get('entry_zone_max')}",
            'SL': s.get('stop_loss'),
            'Channel': s.get('channel', ''),
            'Received': s.get('received_at', '')[:16] if s.get('received_at') else '',
            'Parser': s.get('raw_format', ''),
        })
    df_sig = pd.DataFrame(rows)
    st.dataframe(df_sig, width='stretch', hide_index=True)
else:
    st.info("No signals in selected period")


# ── Trades history table ───────────────────────────────────────────────────────

st.markdown('<div class="section-title">📋 Trade History (Live from MT5)</div>', unsafe_allow_html=True)

if trades_f:
    rows = []
    for t in reversed(trades_f):
        pl = t.get('profit_loss')
        entry = t.get('entry_price')
        rows.append({
            'Ticket': t.get('ticket'),
            'Symbol': t.get('symbol'),
            'Action': t.get('action'),
            'Volume': f"{t.get('volume'):.2f}" if t.get('volume') else '—',
            'Entry': f"{entry:.2f}" if entry else '—',
            'P&L ($)': f"{pl:+.2f}" if pl is not None else '—',
            'Opened': t.get('opened_at', '')[:16] if t.get('opened_at') else '',
            'Closed': t.get('closed_at', '')[:16] if t.get('closed_at') else '—',
        })
    df_tr = pd.DataFrame(rows)

    def color_pl(val):
        if isinstance(val, str) and val != '—':
            try:
                v = float(val.replace('+', ''))
                return 'color: #3fb950' if v > 0 else 'color: #f85149'
            except Exception:
                pass
        return ''

    st.dataframe(
        df_tr.style.map(color_pl, subset=['P&L ($)']),
        width='stretch',
        hide_index=True
    )
else:
    st.info("No trades in selected period")


# ── Symbol breakdown ───────────────────────────────────────────────────────────

st.markdown("---")
col_a, col_b = st.columns(2)

with col_a:
    st.markdown('<div class="section-title">🪙 Trades by Symbol</div>', unsafe_allow_html=True)
    sym_counts = {}
    for t in trades_f:
        s = t.get('symbol', 'Unknown')
        sym_counts[s] = sym_counts.get(s, 0) + 1
    if sym_counts:
        fig4 = px.bar(
            x=list(sym_counts.keys()),
            y=list(sym_counts.values()),
            color=list(sym_counts.keys()),
            labels={'x': 'Symbol', 'y': 'Count'},
        )
        fig4.update_layout(
            paper_bgcolor='#1c1f26', plot_bgcolor='#1c1f26',
            font_color='#e6edf3', showlegend=False,
            margin=dict(t=10, b=10, l=10, r=10), height=220,
            yaxis=dict(gridcolor='#2e3340'),
            xaxis=dict(gridcolor='#2e3340'),
        )
        st.plotly_chart(fig4, width='stretch')
    else:
        st.info("No data")

with col_b:
    st.markdown('<div class="section-title">⚠️ Recent Errors</div>', unsafe_allow_html=True)
    if errors_f:
        for e in reversed(errors_f[-10:]):
            st.error(
                f"**{e.get('error_type', 'error')}** — {e.get('occurred_at', '')[:19]}\n\n"
                f"{e.get('error_message', '')[:200]}"
            )
    else:
        st.success("No errors in selected period ✅")


# ── Modifications log ──────────────────────────────────────────────────────────

if modifications:
    st.markdown("---")
    st.markdown('<div class="section-title">🔧 Modifications Log</div>', unsafe_allow_html=True)
    mods_in_range = [m for m in modifications if in_range(m.get('modified_at', ''))]
    if mods_in_range:
        rows = []
        for m in reversed(mods_in_range[-50:]):
            rows.append({
                'Ticket': m.get('ticket'),
                'Type': m.get('modification_type'),
                'Old': m.get('old_value'),
                'New': m.get('new_value'),
                'Reason': m.get('reason', ''),
                'Time': m.get('modified_at', '')[:16] if m.get('modified_at') else '',
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.info("No modifications in selected period")


# ── Debug Section ──────────────────────────────────────────────────────────────

with st.expander("🔍 Debug: Raw MT5 Data"):
    st.write(f"Total trades loaded: {len(trades)}")
    st.write(f"Open trades: {len(open_trades)}")
    st.write(f"Closed trades: {len(closed_trades)}")
    
    if trades:
        st.write("Sample trade (first 5):")
        st.dataframe(pd.DataFrame(trades[:5]), width='stretch')


# ── Footer ─────────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption("Trading Bot Dashboard • Trades from MT5 (live) • Signals from JSON • Cache refreshes every 5s • All times UTC")