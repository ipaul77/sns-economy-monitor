import os
import sys
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from typing import Literal
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import uuid


# Import the existing DB module to reuse Firestore configuration
import db
import investor

try:
    from firebase_admin import firestore
except ImportError:
    pass

# Sector Mapping for Risk Management
TICKER_TO_SECTOR = {
    "005930": "반도체/IT",      # 삼성전자
    "000660": "반도체/IT",      # SK하이닉스
    "042700": "반도체/IT",      # 한미반도체
    "373220": "이차전지",       # LG에너지솔루션
    "006400": "이차전지",       # 삼성SDI
    "051910": "이차전지",       # LG화학
    "086520": "이차전지",       # 에코프로
    "247540": "이차전지",       # 에코프로비엠
    "003670": "이차전지",       # 포스코퓨처엠
    "096770": "이차전지",       # SK이노베이션
    "005380": "자동차",         # 현대차
    "000270": "자동차",         # 기아
    "035420": "플랫폼",         # 네이버
    "035720": "플랫폼",         # 카카오
    "068270": "바이오",         # 셀트리온
    "207940": "바이오",         # 삼성바이오로직스
    "196170": "바이오",         # 알테오젠
    "028300": "바이오",         # HLB
    "000100": "바이오",         # 유한양행
    "105560": "금융/지주",      # KB금융
    "055550": "금융/지주",      # 신한지주
    "086790": "금융/지주",      # 하나금융지주
    "005490": "금융/지주",      # POSCO홀딩스
    "028260": "금융/지주"       # 삼성물산
}

# ---------------------------------------------------------------------------
# KST TIME HELPERS
# ---------------------------------------------------------------------------
def get_kst_now():
    """
    Returns the current datetime in KST (Korea Standard Time).
    """
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst)

# ---------------------------------------------------------------------------
# FIRESTORE STATE MANAGEMENT
# ---------------------------------------------------------------------------
def get_firestore_client():
    """
    Retrieves the Firestore client from the db module.
    Forces initialization if not already done.
    """
    if not db.FIREBASE_AVAILABLE:
        print("[Trading Engine] [Warning] firebase-admin package is not available!")
        return None
    if not db.USE_FIREBASE or db.db_client is None:
        db.init_db()
    return db.db_client

# ---------------------------------------------------------------------------
# LOCAL SQLITE TRADING CACHE AND WARM START
# ---------------------------------------------------------------------------
_trading_cache_warmed = False

def warm_start_trading_cache():
    """
    Synchronizes agent state, portfolio holdings, and transaction history
    from Firestore to local SQLite once on startup to enable 100% offline/local read caching.
    """
    global _trading_cache_warmed
    if _trading_cache_warmed:
        return
        
    client = get_firestore_client()
    # Ensure local directory for DB exists
    if not os.path.exists(db.DB_DIR):
        os.makedirs(db.DB_DIR)
        
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        
        # Create trading cache tables if they don't exist
        cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS portfolio (ticker TEXT PRIMARY KEY, quantity INTEGER, average_price REAL, highest_price_after_buy REAL)")
        cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, timestamp TEXT, ticker TEXT, action TEXT, quantity INTEGER, price REAL, reasoning TEXT, snapshot_context TEXT)")
        conn.commit()
        
        if client is None:
            # Running in offline demo mode, no Firestore to sync from
            conn.close()
            _trading_cache_warmed = True
            return

        print("[Trading Engine] Synchronizing SQLite cache with Firestore...")
        
        # 1. Warm start agent state
        cursor.execute("DELETE FROM agent_state")
        state_ref = client.collection("agents").document("state")
        doc = state_ref.get()
        if doc.exists:
            state_data = doc.to_dict()
            for k, v in state_data.items():
                cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", (k, str(v)))
            conn.commit()
        
        # 2. Warm start portfolio
        cursor.execute("DELETE FROM portfolio")
        portfolio_ref = client.collection("agents").document("state").collection("portfolio")
        docs = portfolio_ref.stream()
        for doc in docs:
            data = doc.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO portfolio (ticker, quantity, average_price, highest_price_after_buy)
                VALUES (?, ?, ?, ?)
            """, (
                doc.id,
                int(data.get("quantity", 0)),
                float(data.get("average_price", 0.0)),
                float(data.get("highest_price_after_buy", data.get("average_price", 0.0)))
            ))
        conn.commit()
            
        # 3. Warm start transactions (load latest 100)
        cursor.execute("DELETE FROM transactions")
        docs = client.collection("transactions").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100).stream()
        for doc in docs:
            data = doc.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO transactions (id, timestamp, ticker, action, quantity, price, reasoning, snapshot_context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc.id,
                data.get("timestamp", ""),
                data.get("ticker", ""),
                data.get("action", ""),
                int(data.get("quantity", 0)),
                float(data.get("price", 0.0)),
                data.get("reasoning", ""),
                json.dumps(data.get("snapshot_context", {}))
            ))
        conn.commit()
            
        conn.close()
        _trading_cache_warmed = True
        print("[Trading Engine] Successfully warm-started trading cache from Firestore.")
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to warm-start trading cache: {e}")

def get_agent_state() -> Dict[str, Any]:
    """
    Fetches the agent's current balance, total_asset, start_date, and system_lock status from local SQLite cache.
    """
    warm_start_trading_cache()
    
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("SELECT key, value FROM agent_state")
        rows = cursor.fetchall()
        conn.close()
        
        if rows:
            state = {}
            for r in rows:
                k, v = r[0], r[1]
                if k in ["balance", "total_asset"]:
                    state[k] = float(v)
                elif k == "system_lock":
                    state[k] = (v.lower() == 'true')
                else:
                    state[k] = v
            return state
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to fetch agent state from SQLite cache: {e}")
        
    # Offline fallback if DB fetch fails
    return {
        "balance": 10000000.0,
        "total_asset": 10000000.0,
        "start_date": get_kst_now().isoformat(),
        "system_lock": False
    }

def update_agent_state_in_db(balance: float, total_asset: float, system_lock: bool = False) -> bool:
    """
    Updates the agent's state document in both Firestore and local SQLite cache.
    """
    # 1. Update SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("balance", str(float(balance))))
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("total_asset", str(float(total_asset))))
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("system_lock", str(system_lock)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to update agent state in SQLite cache: {e}")
        
    # 2. Update Firestore
    client = get_firestore_client()
    if client is None:
        return True
    try:
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "balance": float(balance),
            "total_asset": float(total_asset),
            "system_lock": system_lock
        })
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to update agent state in Firestore: {e}")
        return False

def lock_system() -> bool:
    """
    Locks the trading system in both Firestore and local SQLite cache due to critical failures.
    """
    # 1. Lock SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("system_lock", "True"))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to lock system in SQLite cache: {e}")
        
    # 2. Lock Firestore
    client = get_firestore_client()
    if client is None:
        return True
    try:
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "system_lock": True
        })
        print("[Trading Engine] [ALERT] System has been locked successfully due to critical anomaly.")
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to lock system in Firestore: {e}")
        return False

def extend_trading_period() -> bool:
    """
    Resets the trading start date to current time to extend the period.
    """
    now_str = get_kst_now().isoformat()
    
    # 1. Update SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("start_date", now_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to extend start_date in SQLite cache: {e}")
        
    # 2. Update Firestore
    client = get_firestore_client()
    if client is None:
        return True
    try:
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "start_date": now_str
        })
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to extend start_date in Firestore: {e}")
        return False

def get_portfolio_holdings() -> Dict[str, Dict[str, Any]]:
    """
    Fetches the active stock portfolio holdings from local SQLite cache.
    Returns a dict: { ticker: { "quantity": int, "average_price": float, "highest_price_after_buy": float } }
    """
    warm_start_trading_cache()
    
    try:
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS portfolio (ticker TEXT PRIMARY KEY, quantity INTEGER, average_price REAL, highest_price_after_buy REAL)")
        cursor.execute("SELECT ticker, quantity, average_price, highest_price_after_buy FROM portfolio")
        rows = cursor.fetchall()
        conn.close()
        
        holdings = {}
        for r in rows:
            qty = int(r["quantity"])
            if qty > 0:
                holdings[r["ticker"]] = {
                    "quantity": qty,
                    "average_price": float(r["average_price"]),
                    "highest_price_after_buy": float(r["highest_price_after_buy"])
                }
        return holdings
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to fetch portfolio holdings from SQLite cache: {e}")
        return {}

def update_portfolio_holding_in_db(ticker: str, quantity: int, average_price: float, highest_price_after_buy: Optional[float] = None) -> bool:
    """
    Updates or deletes a specific stock holding in both Firestore and SQLite cache.
    """
    # 1. Update SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS portfolio (ticker TEXT PRIMARY KEY, quantity INTEGER, average_price REAL, highest_price_after_buy REAL)")
        
        if quantity <= 0:
            cursor.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
            conn.commit()
            conn.close()
            print(f"[Trading Engine] [SQLite] Deleted holding for ticker {ticker}.")
            sqlite_success = True
        else:
            # Get existing highest_price_after_buy if not provided
            cursor.execute("SELECT highest_price_after_buy FROM portfolio WHERE ticker = ?", (ticker,))
            row = cursor.fetchone()
            h_price = highest_price_after_buy
            if h_price is None:
                if row:
                    h_price = float(row[0])
                else:
                    h_price = average_price
            
            cursor.execute("""
                INSERT OR REPLACE INTO portfolio (ticker, quantity, average_price, highest_price_after_buy)
                VALUES (?, ?, ?, ?)
            """, (ticker, int(quantity), float(average_price), float(h_price)))
            conn.commit()
            conn.close()
            print(f"[Trading Engine] [SQLite] Updated holding for ticker {ticker}: Quantity={quantity}, AvgPrice={average_price:.1f}, Highest={h_price:.1f}")
            sqlite_success = True
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to update portfolio holding in SQLite cache: {e}")
        sqlite_success = False

    # 2. Update Firestore
    client = get_firestore_client()
    if client is None:
        return sqlite_success
    try:
        holding_ref = client.collection("agents").document("state").collection("portfolio").document(ticker)
        if quantity <= 0:
            holding_ref.delete()
            print(f"[Trading Engine] [Firestore] Deleted holding for ticker {ticker}.")
        else:
            payload = {
                "quantity": int(quantity),
                "average_price": float(average_price)
            }
            if highest_price_after_buy is not None:
                payload["highest_price_after_buy"] = float(highest_price_after_buy)
            else:
                doc = holding_ref.get()
                if doc.exists:
                    payload["highest_price_after_buy"] = float(doc.to_dict().get("highest_price_after_buy", average_price))
                else:
                    payload["highest_price_after_buy"] = float(average_price)
            holding_ref.set(payload)
            print(f"[Trading Engine] [Firestore] Updated holding for ticker {ticker}: Quantity={quantity}")
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to update portfolio holding in Firestore: {e}")
        return False

def save_transaction_to_db(ticker: str, action: str, quantity: int, price: float, reasoning: str, snapshot_context: Dict[str, Any]) -> bool:
    """
    Saves a trading transaction record to both Firestore and SQLite cache.
    """
    now_str = get_kst_now().isoformat()
    import uuid
    tx_id = str(uuid.uuid4())
    
    # 1. Save to SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY, timestamp TEXT, ticker TEXT, action TEXT,
                quantity INTEGER, price REAL, reasoning TEXT, snapshot_context TEXT
            )
        """)
        cursor.execute("""
            INSERT OR REPLACE INTO transactions (id, timestamp, ticker, action, quantity, price, reasoning, snapshot_context)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (tx_id, now_str, ticker, action, int(quantity), float(price), reasoning, json.dumps(snapshot_context)))
        conn.commit()
        conn.close()
        sqlite_success = True
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to save transaction to SQLite cache: {e}")
        sqlite_success = False

    # 2. Save to Firestore
    client = get_firestore_client()
    if client is None:
        return sqlite_success
    try:
        tx_ref = client.collection("transactions").document(tx_id)
        tx_data = {
            "timestamp": now_str,
            "ticker": ticker,
            "action": action,
            "quantity": int(quantity),
            "price": float(price),
            "reasoning": reasoning,
            "snapshot_context": snapshot_context
        }
        tx_ref.set(tx_data)
        print(f"[Trading Engine] Logged transaction to Firestore: {action} {quantity} shares of {ticker} at {price:,.0f} KRW.")
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to save transaction to Firestore: {e}")
        return False

def trigger_telegram_trade_alert(ticker: str, action: str, quantity: int, price: float, reasoning: str, balance: float, total_asset: float):
    """
    Loads Telegram bot settings from config.json or environment variables and triggers a trade alert if configured.
    """
    try:
        token = ""
        chat_id = ""
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                token = config.get("telegram_bot_token", "")
                chat_id = config.get("telegram_chat_id", "")
        except Exception:
            pass
            
        # Fallback to environment variables (useful for cloud platforms like Render)
        if not token or not token.strip():
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not chat_id or not chat_id.strip():
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
            
        if token and chat_id and token.strip() and chat_id.strip():
            from alerts import send_telegram_trade_alert
            send_telegram_trade_alert(
                token=token,
                chat_id=chat_id,
                ticker=ticker,
                action=action,
                quantity=quantity,
                price=price,
                reasoning=reasoning,
                balance=balance,
                total_asset=total_asset
            )
    except Exception as e:
        print(f"[Trading Engine] [Warning] Telegram trade alert trigger failed: {e}")

def get_latest_transactions(limit: int = 15) -> List[Dict[str, Any]]:
    """
    Retrieves the latest transaction logs from SQLite cache sorted by timestamp descending.
    """
    warm_start_trading_cache()
    
    try:
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, timestamp TEXT, ticker TEXT, action TEXT, quantity INTEGER, price REAL, reasoning TEXT, snapshot_context TEXT)")
        cursor.execute("SELECT timestamp, ticker, action, quantity, price, reasoning, snapshot_context FROM transactions ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        txs = []
        for r in rows:
            try:
                snapshot = json.loads(r["snapshot_context"] or "{}")
            except:
                snapshot = {}
            txs.append({
                "timestamp": r["timestamp"],
                "ticker": r["ticker"],
                "action": r["action"],
                "quantity": int(r["quantity"]),
                "price": float(r["price"]),
                "reasoning": r["reasoning"],
                "snapshot_context": snapshot
            })
        return txs
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to fetch transaction logs from SQLite cache: {e}")
        
    # Fallback to Firestore (original logic)
    client = get_firestore_client()
    if client is None:
        return []
    try:
        docs = client.collection("transactions")\
                     .order_by("timestamp", direction=firestore.Query.DESCENDING)\
                     .limit(limit)\
                     .stream()
        txs = []
        for doc in docs:
            txs.append(doc.to_dict())
        return txs
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to fetch transaction logs from Firestore: {e}")
        return []

# ---------------------------------------------------------------------------
# DYNAMIC AI STOCK CANDIDATE PIPELINE MAPPING
# ---------------------------------------------------------------------------
COMPANY_TO_TICKER = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "하이닉스": "000660",
    "현대차": "005380",
    "현대자동차": "005380",
    "기아": "000270",
    "기아차": "000270",
    "NAVER": "035420",
    "네이버": "035420",
    "카카오": "035720",
    "LG에너지솔루션": "373220",
    "LG엔솔": "373220",
    "삼성SDI": "006400",
    "LG화학": "051910",
    "포스코홀딩스": "005490",
    "POSCO홀딩스": "005490",
    "셀트리온": "068270",
    "한미반도체": "042700",
    "에코프로": "086520",
    "에코프로비엠": "247540",
    "포스코퓨처엠": "003670",
    "SK이노베이션": "096770",
    "삼성물산": "028260",
    "KB금융": "105560",
    "KB금융지주": "105560",
    "신한지주": "055550",
    "신한금융지주": "055550",
    "하나금융지주": "086790",
    "삼성바이오로직스": "207940",
    "알테오젠": "196170",
    "HLB": "028300",
    "HMM": "011200",
    "대한항공": "003490",
    "두산에너빌리티": "034020",
    "HD현대중공업": "329180",
    "유한양행": "000100"
}

# Static mapping of KOSDAQ tickers to bypass slow yfinance network checks
KOSDAQ_TICKERS = {"086520", "247540", "196170", "028300", "066970"}

def is_kospi_bear_market() -> bool:
    """
    KOSPI 지수가 최근 5일 이동평균선(5-day MA)보다 아래에 있는 하락 약세장 여부를 판별합니다.
    """
    try:
        yt = yf.Ticker("^KS11")
        hist = yt.history(period="10d")
        if not hist.empty and len(hist) >= 5:
            current_kospi = float(hist["Close"].iloc[-1])
            ma_5 = float(hist["Close"].iloc[-5:].mean())
            is_bear = current_kospi < ma_5
            print(f"[Trading Engine] KOSPI Bear Filter: Current = {current_kospi:,.2f} | 5 MA = {ma_5:,.2f} | Bear Market = {is_bear}")
            return is_bear
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to fetch KOSPI 5 MA: {e}")
    return False

def get_dynamic_top_7_stocks() -> List[str]:
    """
    최근 24시간 내 수집된 관련성 높은 기사(is_relevant=1)를 바탕으로 가장 많이 언급된 종목 7개를 선정합니다.
    언급된 종목이 7개 미만인 경우, 국내 증시 주요 대형주(삼성전자, SK하이닉스, LG에너지솔루션, 현대차, 삼성바이오로직스, 기아, 셀트리온)로 채워
    항상 7개의 감시 대상 종목을 반환합니다.
    """
    recent_news = db.fetch_recent_relevant(hours=24)
    
    ticker_counts = {}
    for item in recent_news:
        tickers_val = item.get("impacted_tickers")
        if tickers_val:
            try:
                if isinstance(tickers_val, str):
                    tickers_list = json.loads(tickers_val)
                elif isinstance(tickers_val, list):
                    tickers_list = tickers_val
                else:
                    tickers_list = []
                
                if isinstance(tickers_list, list):
                    for t in tickers_list:
                        t = str(t).strip()
                        if len(t) == 6 and t.isdigit():
                            ticker_counts[t] = ticker_counts.get(t, 0) + 1
            except Exception:
                pass
                
        companies_val = item.get("impacted_companies")
        if companies_val:
            try:
                if isinstance(companies_val, str):
                    companies = json.loads(companies_val)
                elif isinstance(companies_val, list):
                    companies = companies_val
                else:
                    companies = []
                
                if isinstance(companies, list):
                    for comp in companies:
                        ticker = COMPANY_TO_TICKER.get(str(comp).strip())
                        if ticker:
                            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
            except Exception:
                pass

    sorted_tickers = [t for t, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)]
    
    default_tickers = ["005930", "000660", "373220", "005380", "207940", "000270", "068270"]
    
    dynamic_7 = []
    for t in sorted_tickers:
        if t not in dynamic_7 and len(dynamic_7) < 7:
            dynamic_7.append(t)
            
    for t in default_tickers:
        if t not in dynamic_7 and len(dynamic_7) < 7:
            dynamic_7.append(t)
            
    return dynamic_7

def get_active_tickers(portfolio: Dict[str, Any], news_context: List[Dict[str, Any]]) -> List[str]:
    """
    Dynamically constructs the stock ticker pool for the current simulation cycle:
    1. Dynamic Top 7 stocks are always included for priority monitoring.
    2. Account holdings: Any stock currently owned in the portfolio is always included to allow selling.
    """
    dynamic_7 = get_dynamic_top_7_stocks()
    active_tickers = set(dynamic_7)
    
    # 1. Include currently owned portfolio holdings
    for ticker in portfolio.keys():
        active_tickers.add(ticker)
        
    print(f"[Trading Engine] Dynamic candidate ticker pool generated: {list(active_tickers)}")
    return list(active_tickers)


# ---------------------------------------------------------------------------
# MARKET DATA FETCHING (yfinance)
# ---------------------------------------------------------------------------
def get_market_index_change() -> Dict[str, float]:
    """
    Fetches the daily return (%) for KOSPI (^KS11) and KOSDAQ (^KQ11) from yfinance.
    Returns: { "KOSPI": float, "KOSDAQ": float } (e.g., { "KOSPI": -0.85, "KOSDAQ": 0.45 })
    """
    indices = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    results = {"KOSPI": 0.0, "KOSDAQ": 0.0}
    for name, ticker in indices.items():
        try:
            yt = yf.Ticker(ticker)
            # Fetch 2 days of history to calculate the daily change
            hist = yt.history(period="2d")
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                curr_close = float(hist["Close"].iloc[-1])
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                results[name] = round(pct_change, 2)
            else:
                info = yt.fast_info
                change = info.get("regularMarketChangePercent") or info.get("regular_market_change_percent")
                if change is not None:
                    results[name] = round(float(change), 2)
        except Exception as e:
            print(f"[Trading Engine] [Warning] Failed to fetch index {name}: {e}")
    return results

def get_market_trend_regime() -> Dict[str, Any]:
    """
    Fetches the last 20 days of historical data for KOSPI (^KS11)
    and determines if the market is in a Downtrend (current < 20 MA) or Uptrend.
    """
    try:
        yt = yf.Ticker("^KS11")
        # Fetch 1 month of data to safely calculate a 20-day moving average
        hist = yt.history(period="1mo")
        if not hist.empty and len(hist) >= 20:
            close_slice = hist["Close"].iloc[-20:]
            ma_20 = float(close_slice.mean())
            current_price = float(hist["Close"].iloc[-1])
            is_downtrend = current_price < ma_20
            return {
                "status": "success",
                "current_price": round(current_price, 2),
                "ma_20": round(ma_20, 2),
                "is_downtrend": is_downtrend,
                "message": f"KOSPI: {current_price:.2f} | 20 MA: {ma_20:.2f} ({'íë½ êµ­ë©´' if is_downtrend else 'ìì¹ êµ­ë©´'})"
            }
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to fetch market trend regime: {e}")
    return {
        "status": "fallback",
        "current_price": 2650.0,
        "ma_20": 2650.0,
        "is_downtrend": False,
        "message": "시장 국면 분석 실패 (기본값 상승 국면으로 우회)"
    }

def get_stock_indicators(ticker: str) -> Dict[str, Any]:

    """
    Fetches all advanced technical indicators for a given stock ticker:
    1. Current Price
    2. 20-day Moving Average (20 MA)
    3. 20-day Disparity Index (%)
    4. Daily Volume
    5. 5-day Average Volume (excluding today)
    6. Volume Breakout Ratio (daily_vol / avg_5day_vol)
    """
    ticker = ticker.strip()
    result = {
        "current_price": 0.0,
        "ma_20": 0.0,
        "disparity": 100.0,
        "daily_volume": 0,
        "avg_volume_5d": 0.0,
        "volume_ratio": 1.0,
        "volume_breakout": False,
        "market": "KOSPI"  # Default to KOSPI
    }
    if not ticker:
        return result

    # Standard suffix translation logic optimized using static KOSDAQ set
    resolved_suffix = ".KS"
    if len(ticker) == 6 and ticker.isdigit():
        if ticker in KOSDAQ_TICKERS:
            resolved_suffix = ".KQ"
            result["market"] = "KOSDAQ"
        else:
            resolved_suffix = ".KS"
            result["market"] = "KOSPI"
            
    full_ticker = ticker + resolved_suffix if (len(ticker) == 6 and ticker.isdigit()) else ticker

    try:
        yt = yf.Ticker(full_ticker)
        hist = yt.history(period="1mo")
        # Try fallback if history is empty (e.g. new ticker or wrong suffix mapping)
        if hist.empty and len(ticker) == 6 and ticker.isdigit():
            fallback_suffix = ".KQ" if resolved_suffix == ".KS" else ".KS"
            yt = yf.Ticker(ticker + fallback_suffix)
            hist = yt.history(period="1mo")
            if not hist.empty:
                result["market"] = "KOSDAQ" if fallback_suffix == ".KQ" else "KOSPI"
        if hist.empty:
            price = investor.get_latest_cached_price(ticker)
            if price > 0:
                result["current_price"] = price
                result["ma_20"] = price
                result["disparity"] = 100.0
            return result

        # 1. Current Price (Try KIS first)
        kis_price = None
        try:
            from kis_client import kis_client
            kis_price = kis_client.get_current_price(ticker)
        except Exception as e:
            print(f"[Trading Engine] [Warning] KIS price fetch failed for indicators: {e}")

        current_price = kis_price if kis_price is not None else float(hist["Close"].iloc[-1])
        result["current_price"] = current_price

        # 2. 20-day Moving Average (20 MA)
        ma_length = min(len(hist), 20)
        close_slice = hist["Close"].iloc[-ma_length:].tolist()
        if len(close_slice) > 0 and kis_price is not None:
            close_slice[-1] = kis_price  # Replace today's close with KIS real-time price
        ma_20 = sum(close_slice) / len(close_slice)
        result["ma_20"] = ma_20

        # 3. 20-day Disparity Index (%)
        if ma_20 > 0:
            result["disparity"] = round((current_price / ma_20) * 100, 2)

        # 4. Daily Volume
        daily_volume = int(hist["Volume"].iloc[-1])
        result["daily_volume"] = daily_volume

        # 5. 5-day Average Volume (excluding today)
        if len(hist) >= 6:
            vol_slice = hist["Volume"].iloc[-6:-1]
            avg_vol_5d = float(vol_slice.mean())
        else:
            avg_vol_5d = float(hist["Volume"].iloc[:-1].mean()) if len(hist) > 1 else float(daily_volume)
        
        result["avg_volume_5d"] = avg_vol_5d

        # 6. Volume Breakout Ratio
        if avg_vol_5d > 0:
            vol_ratio = daily_volume / avg_vol_5d
            result["volume_ratio"] = round(vol_ratio, 2)
            result["volume_breakout"] = vol_ratio > 2.0
            
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to calculate indicators for {ticker}: {e}")
        price = investor.get_latest_cached_price(ticker)
        result["current_price"] = price
        result["ma_20"] = price
        result["disparity"] = 100.0

    # Fetch investor (sugeup) indicators
    try:
        import investor
        inv_ind = investor.get_investor_indicators(ticker)
        result.update(inv_ind)
    except Exception as ex:
        print(f"[Trading Engine] [Warning] Failed to merge investor indicators for {ticker}: {ex}")
        result.update({
            "frgn_net_5d": 0, "inst_net_5d": 0, "frgn_net_10d": 0, "inst_net_10d": 0,
            "dual_buy_5d_count": 0, "frgn_ratio": 0.0, "frgn_trend_sig": "HOLD", "inst_trend_sig": "HOLD"
        })

    return result

def get_stock_volatility_multiplier(ticker: str, fallback_vol: float = 0.045) -> float:
    """
    Fetches historical close prices for the past 20 trading days,
    calculates the standard deviation of daily returns,
    and multiplies it by 2.5 to set a volatility-based stop-loss percentage.
    Returns the stop-loss percentage (e.g. 0.065 for 6.5%).
    """
    ticker = ticker.strip()
    if not ticker:
        return fallback_vol
        
    full_ticker = ticker
    if len(ticker) == 6 and ticker.isdigit():
        full_ticker = ticker + ".KS"  # Assume KOSPI first
        
    try:
        yt = yf.Ticker(full_ticker)
        hist = yt.history(period="1mo")
        if (hist.empty or len(hist) < 10) and len(ticker) == 6:
            # Try KOSDAQ
            yt = yf.Ticker(ticker + ".KQ")
            hist = yt.history(period="1mo")
            
        if not hist.empty and len(hist) >= 10:
            close_prices = hist["Close"].tolist()
            # Calculate daily fractional changes
            returns = []
            for i in range(1, len(close_prices)):
                if close_prices[i-1] > 0:
                    returns.append((close_prices[i] - close_prices[i-1]) / close_prices[i-1])
            if returns:
                import math
                # Calculate mean
                mean_ret = sum(returns) / len(returns)
                # Calculate variance
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std_dev = math.sqrt(variance)
                
                # Cap standard deviation between 1% and 6% per day to avoid extreme stops
                std_dev = max(min(std_dev, 0.06), 0.01)
                
                # 2.5 * standard deviation
                vol_stop = std_dev * 2.5
                print(f"[Trading Volatility] {ticker}: Daily StdDev = {std_dev:.2%}, VolStop = {vol_stop:.2%}")
                return vol_stop
    except Exception as e:
        print(f"[Trading Engine] [Warning] Volatility calculation failed for {ticker}: {e}")
        
    return fallback_vol

def get_stock_price(ticker: str) -> float:

    """
    Fetches the current market price for a given 6-digit stock ticker code (e.g. 005930).
    Automatically translates it to .KS (KOSPI) or .KQ (KOSDAQ).
    If ticker has no suffix, tries KOSPI first, then KOSDAQ as a fallback.
    """
    ticker = ticker.strip()
    if not ticker:
        return 0.0

    # Handle standard 6-digit Korean stock tickers
    if len(ticker) == 6 and ticker.isdigit():
        # --- KIS Open API real-time price attempt ---
        try:
            from kis_client import kis_client
            kis_price = kis_client.get_current_price(ticker)
            if kis_price is not None and kis_price > 0:
                return kis_price
        except Exception as e:
            print(f"[Trading Engine] [Warning] KIS API price query failed for {ticker}: {e}")

        # --- Fallback to yfinance ---
        resolved_suffix = ".KQ" if ticker in KOSDAQ_TICKERS else ".KS"
        full_ticker = ticker + resolved_suffix
        try:
            # Use fast_info first (extremely fast, low overhead)
            yt = yf.Ticker(full_ticker)
            info = yt.fast_info
            price = info.get("lastPrice") or info.get("last_price")
            if price is not None and price > 0:
                return float(price)
            
            # Fallback to history
            hist = yt.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            # Try the alternative suffix as fallback
            alt_suffix = ".KS" if resolved_suffix == ".KQ" else ".KQ"
            try:
                yt = yf.Ticker(ticker + alt_suffix)
                info = yt.fast_info
                price = info.get("lastPrice") or info.get("last_price")
                if price is not None and price > 0:
                    return float(price)
                hist = yt.history(period="1d")
                if not hist.empty:
                    return float(hist["Close"].iloc[-1])
            except Exception:
                pass
        
        # Dynamic cached price fallback from SQLite DB
        fallback = investor.get_latest_cached_price(ticker)
        if fallback > 0:
            print(f"[Trading Engine] [Warning] yfinance failed for K-ticker {ticker}. Using SQLite cached fallback price: {fallback:,.0f} KRW.")
            return fallback
            
    else:
        # For non-standard tickers (e.g. US stocks or indexes)
        try:
            yt = yf.Ticker(ticker)
            info = yt.fast_info
            price = info.get("lastPrice") or info.get("last_price")
            if price is not None and price > 0:
                return float(price)
            hist = yt.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            print(f"[Trading Engine] [Error] Failed to fetch price for ticker {ticker}: {e}")
            
    return 0.0

# ---------------------------------------------------------------------------
# PHASE 2: GEMINI API STRUCTURED INVESTMENT DECISION FORMULATION
# ---------------------------------------------------------------------------
class TradingDecision(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="The trading action to execute: BUY, SELL, or HOLD.")
    ticker: str = Field(description="A 6-digit stock ticker code to trade (e.g. '005930' for Samsung Electronics, '000660' for SK Hynix).")
    allocation_pct: float = Field(description="Percentage of available cash to allocate to this BUY trade (from 0.0 to 100.0). For SELL, represent the percentage of owned shares to sell (from 0.0 to 100.0). For HOLD, this must be 0.0.")
    reasoning: str = Field(description="Specific, detailed investment logic in Korean justifying the decision based on provided news sentiment and price analysis.")


def generate_trading_decision(portfolio: Dict[str, Dict[str, Any]], balance: float, market_prices: Dict[str, float], news_context: List[Dict[str, Any]], market_indicators: Optional[Dict[str, Dict[str, Any]]] = None, index_changes: Optional[Dict[str, float]] = None, api_key: Optional[str] = None) -> TradingDecision:
    """
    Calls the Gemini API to formulate a trading decision using strict Pydantic response schema.
    Injects system guardrails to avoid hallucinations and enforce capital constraints.
    """
    import google.generativeai as genai
    
    # Configure API key
    if api_key:
        genai.configure(api_key=api_key.strip())
    else:
        # Load key from environment or config
        env_key = os.getenv("GEMINI_API_KEY")
        if env_key:
            genai.configure(api_key=env_key.strip())
        else:
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                    cfg_key = config.get("GEMINI_API_KEY")
                    if cfg_key:
                        genai.configure(api_key=cfg_key.strip())
            except Exception:
                pass
                
    # 0. Calculate Leading Flow Score from SOXX & USD_KRW changes
    leading_flow_score = 5
    soxx_change = 0.0
    usdkrw_change = 0.0
    try:
        import market
        import investor
        m_data = market.get_market_indicators()
        if m_data:
            soxx_change = m_data.get("SOXX", {}).get("percent", 0.0)
            usdkrw_change = m_data.get("USD_KRW", {}).get("percent", 0.0)
            leading_flow_score = investor.calculate_leading_flow_score(soxx_change, usdkrw_change)
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to calculate Leading Flow Score: {e}")

    # 1. Goal-Based Investing (ROI Target: +50% in 30 days)
    initial_asset = 10000000.0
    state = get_agent_state()
    start_date_str = state.get("start_date", get_kst_now().isoformat())
    try:
        start_date = datetime.fromisoformat(start_date_str)
        elapsed_days = (get_kst_now() - start_date).days
    except Exception:
        elapsed_days = 0
        
    remaining_days = max(30 - elapsed_days, 1)
    
    # Calculate current total asset (balance + current holdings value)
    portfolio_value = sum(
        portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) 
        for t in portfolio
    )
    current_total_asset = balance + portfolio_value
    current_roi = ((current_total_asset - initial_asset) / initial_asset) * 100
    target_roi = 50.0 # +50% ROI Target
    target_asset = initial_asset * (1.0 + (target_roi / 100.0))

    # Format portfolio state for the prompt
    portfolio_str = ""
    if not portfolio:
        portfolio_str = "보유하고 있는 주식이 없습니다."
    else:
        for tick, info in portfolio.items():
            current_price = market_prices.get(tick, 0.0)
            avg_price = info["average_price"]
            qty = info["quantity"]
            pl_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            portfolio_str += f"- 종목코드: {tick} | 보유수량: {qty}주 | 평균 매수가: {avg_price:,.0f}원 | 현재가: {current_price:,.0f}원 (수익률: {pl_rate:+.2f}%)\n"

    # Format market prices
    prices_str = "\n".join([f"- 종목코드: {tick} | 현재 체결가: {price:,.0f}원" for tick, price in market_prices.items()])

    # Format index changes
    index_str = "지수 정보 없음"
    if index_changes:
        index_str = ", ".join([f"{name}: {val:+.2f}%" for name, val in index_changes.items()])

    # Format indicators (Populated to give Gemini AI the actual technical signals!)
    indicators_str = ""
    for tick, ind in market_indicators.items():
        comp_name = tick
        for c, t in COMPANY_TO_TICKER.items():
            if t == tick:
                comp_name = c
                break
        indicators_str += (
            f"- 종목명: {comp_name} ({tick}) | "
            f"현재가: {ind.get('current_price', 0.0):,.0f}원 | "
            f"20일선 MA: {ind.get('ma_20', 0.0):,.0f}원 | "
            f"이격도: {ind.get('disparity', 100.0):.1f}% | "
            f"당일거래량: {ind.get('daily_volume', 0):,}주 | "
            f"5일평균거래량: {ind.get('avg_volume_5d', 0.0):,.0f}주 | "
            f"거래량 돌파 비율: {ind.get('volume_ratio', 1.0):.1f}x | "
            f"외인5일누적: {ind.get('frgn_net_5d', 0):+d}주 | "
            f"기관5일누적: {ind.get('inst_net_5d', 0):+d}주 | "
            f"양매수일수(5일): {ind.get('dual_buy_5d_count', 0)}일 | "
            f"외인보유율: {ind.get('frgn_ratio', 0.0):.2f}%\n"
        )

    # Format news analysis context
    news_str = ""
    if not news_context:
        news_str = "최근 24시간 동안 수집된 한국 경제 관련 신규 뉴스가 없습니다. 뉴스 호재가 없더라도 이격도, 거래량 돌파 비율 등 기술적 지표가 뚜렷하면 모멘텀 거래를 고려할 수 있습니다."
    else:
        for idx, item in enumerate(news_context[:10]):  # Limit to top 10 relevant stories
            news_str += (
                f"{idx+1}. [{item.get('source', '뉴스')}] {item.get('title', '')} (중요도: {item.get('relevance_score', 5)}/10) \n"
                f"   - 감성수준: {item.get('sentiment', 'NEUTRAL')} (점수: {item.get('sentiment_score', 0.0):+.2f}) \n"
                f"   - AI 분석 요약: {item.get('korean_summary', '')} \n"
                f"   - 증시 영향 평가: {item.get('macro_impacts', '')} \n"
            )

    # Define system instructions (Guardrails)
    system_instruction = (
        "   - **이익 보존 모드(Capital Preservation)**: 이미 목표 수익률을 초과 달성했거나 목표 페이스를 안정적으로 상회하고 있는 경우, 새로운 추격 매수를 매우 자제하고 이익을 실현하여 얻은 수익을 안전하게 지키는 관망(HOLD) 위주로 조심스럽게 방어하라."
    )

    prompt = f"""
현재 시각: {get_kst_now().strftime("%Y-%m-%d %H:%M:%S")} (KST)
현재 사용 가능한 예수금(Cash): {balance:,.0f}원

[포트폴리오 자산 운용 목표 (30일 누적 목표 수익률: +{target_roi}%)]
- 투자 시작일: {start_date.strftime("%Y-%m-%d")}
- 현재 경과 일수: 30일 중 {elapsed_days}일차 (남은 일수: {remaining_days}일)
- 초기 운용 자산: {initial_asset:,.0f}원
- 30일 목표 자산: {target_asset:,.0f}원 (+{target_roi}%)
- 현재 평가 자산: {current_total_asset:,.0f}원 (현재 누적 수익률: {current_roi:+.2f}%)
- 일별 권장 진척 속도: +1.67% / 일

[시장 전체 Macro 지수 동향]
- {index_str}

[현재 보유 주식 현황 (Portfolio)]
{portfolio_str}

[거래 대상 종목 실시간 기술적/거래량 지표]
{indicators_str}

[최근 24시간 실시간 경제 뉴스 분석 컨텍스트]
{news_str}

위 자산 상태, 거시 경제 지수, 실시간 기술 지표, 그리고 뉴스 분석 데이터를 정밀 종합 분석하여 최고의 의사결정을 내리고, 지정된 JSON 스키마에 따라 응답하세요.
"""
    # Load model name from config.json or default to gemini-3.5-flash (active 2026 model)
    model_name = "gemini-3.5-flash"
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
            model_name = cfg.get("models", {}).get("pro_model", "gemini-3.5-flash")
    except:
        pass

    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction
        )
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=TradingDecision,
                temperature=0.2
            )
        )
        # Parse Pydantic object
        decision = TradingDecision.model_validate_json(response.text)
        return decision
    except Exception as e:
        print(f"[Trading Engine] [Error] Gemini API or schema validation failed: {e}. Falling back to HOLD.")
        # Fallback to HOLD
        return TradingDecision(
            action="HOLD",
            ticker="005930",
            allocation_pct=0.0,
            reasoning=f"Gemini API 호출 및 스키마 검증 과정에서 예외가 발생하여 자산 안전을 위해 HOLD 처리했습니다. (에러: {str(e)})"
        )


def run_simulation_cycle(bypass_hours: bool = False) -> dict:
    """
    Executes a single end-to-end trading simulation cycle:
    1. Check and Load database state (Check for system locks).
    2. Check KST Market Hours (09:00 - 15:30) with optional test bypass.
    3. Apply Idempotency Lock (30 min minimum gap or news ID validation).
    4. Fetch target stock market prices & technical indicators in parallel.
    5. Evaluate Mechanical Rules (Stop-Loss -4.5% & Trailing-Stop -3%) and update Firestore.
    6. Retrieve latest news context from DB.
    7. Call Gemini Agent with indicators context for decision formulation.
    8. backend Order Verification (Execution Filter, Shock & Disparity Override).
    9. Process Account Updates.
    10. Run **Accounting Assert** (strict mathematical verification or lock and sys.exit).
    11. Log transaction & Update Firestore state.
    """
    # 1. State Load & Lock Check
    state = get_agent_state()
    if state.get("system_lock", False):
        print("[Trading Engine] CRITICAL: System is locked! Aborting simulation run.")
        return {"status": "error", "message": "System is locked due to past accounting anomalies."}

    # 2. KST Market Hours Check
    now = get_kst_now()
    # Weekday check: Monday=0, Sunday=6
    is_weekday = now.weekday() < 5
    # Hour check: 09:00 to 15:30
    market_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    is_market_open = is_weekday and (market_start <= now <= market_end)
    
    if not is_market_open and not bypass_hours:
        print(f"[Trading Engine] Out of market hours ({now.strftime('%Y-%m-%d %H:%M:%S')} KST). Simulation skipped.")
        return {"status": "skipped", "message": "Market is closed. Simulated runs only occur on weekdays between 09:00 and 15:30 KST."}

    # 3. Get Portfolio, State Snapshots, and News Context Early
    portfolio = get_portfolio_holdings()
    news_context = db.fetch_recent_relevant(hours=24)
    balance = float(state.get("balance", 10000000.0))
    prev_total_asset = float(state.get("total_asset", 10000000.0))

    # 4. Idempotency Lock Check (Time Interval)
    last_txs = get_latest_transactions(limit=1)
    if last_txs:
        last_tx = last_txs[0]
        try:
            last_time = datetime.fromisoformat(last_tx["timestamp"])
            time_diff = now - last_time
            # Cooldown duration: 15 minutes (Safe limit to avoid yfinance rate limiting)
            cooldown = timedelta(minutes=15)
            if time_diff < cooldown and not bypass_hours:
                print(f"[Trading Engine] Idempotency Lock: Trade within 15 minutes cooldown is blocked. Last trade was {time_diff.total_seconds() / 60:.1f} mins ago.")
                return {"status": "skipped", "message": "Idempotency Lock: Minimum 15-minute interval between trades required."}
        except Exception as e:
            print(f"[Trading Engine] Failed to parse last transaction timestamp: {e}")

    # 6. Fetch Market Prices & Indicators (Monitored candidates) in parallel using ThreadPoolExecutor!
    index_changes = get_market_index_change()
    print(f"[Trading Engine] Market Indices changes: {index_changes}")
    
    # KOSPI or KOSDAQ 급락 쇼크 경보 (-1.5% 이하)
    is_market_shock = False
    shock_reason = ""
    for idx_name, val in index_changes.items():
        if val <= -1.5:
            is_market_shock = True
            shock_reason = f"지수 급락 쇼크 경보 ({idx_name} 당일 등락률: {val:+.2f}%)"
            break

    monitored_tickers = get_active_tickers(portfolio, news_context)
    market_indicators = {}
    market_prices = {}
    
    def fetch_indicators(tick):
        return tick, get_stock_indicators(tick)
        
    try:
        with ThreadPoolExecutor(max_workers=max(len(monitored_tickers), 1)) as executor:
            results = list(executor.map(fetch_indicators, monitored_tickers))
            for tick, ind in results:
                market_indicators[tick] = ind
                price = ind.get("current_price", 0.0)
                if price > 0:
                    market_prices[tick] = price
    except Exception as e:
        print(f"[Trading Engine] [Warning] Parallel indicator fetching failed: {e}. Falling back to sequential.")
        for tick in monitored_tickers:
            ind = get_stock_indicators(tick)
            market_indicators[tick] = ind
            price = ind.get("current_price", 0.0)
            if price > 0:
                market_prices[tick] = price

    # 5. Idempotency Lock Check (Duplicate News URL Check)
    has_technical_trigger = False
    for tick, ind in market_indicators.items():
        if ind.get("volume_breakout", False) or abs(ind.get("disparity", 100.0) - 100.0) >= 10.0:
            has_technical_trigger = True
            break
            
    if news_context and not has_technical_trigger:
        latest_news_url = news_context[0].get("url", "")
        already_processed_news = False
        for tx in get_latest_transactions(limit=5):
            snapshot = tx.get("snapshot_context", {})
            if snapshot.get("latest_news_url") == latest_news_url and tx.get("action") != "HOLD" and not bypass_hours:
                already_processed_news = True
                break
        
        if already_processed_news:
            print(f"[Trading Engine] Idempotency Lock: Already processed and acted upon the latest news URL: {latest_news_url}")
            return {"status": "skipped", "message": "Idempotency Lock: Latest news context has already been acted upon."}

    # 6.5. Mechanical Stop-Loss (-4.5%) & Trailing-Stop (-3.0%) Evaluation
    for ticker, holding in portfolio.items():
        current_price = market_prices.get(ticker, 0.0)
        if current_price <= 0:
            continue
            
        avg_price = holding["average_price"]
        prev_highest = holding["highest_price_after_buy"]
        
        # 1. Update highest price since buy
        new_highest = max(current_price, prev_highest)
        if new_highest > prev_highest:
            update_portfolio_holding_in_db(ticker, holding["quantity"], avg_price, new_highest)
            holding["highest_price_after_buy"] = new_highest
            
        # 2. Stop-Loss Trigger Check (-4.5%)
        stop_loss_limit = avg_price * (1 - 0.045)
        if current_price <= stop_loss_limit:
            print(f"[Trading Engine] [EX-SL] Stop-Loss triggered for {ticker}! Price {current_price:,.0f} <= Limit {stop_loss_limit:,.0f} KRW.")
            qty = holding["quantity"]
            total_sell_val = qty * current_price
            fee_rate = 0.001
            tx_fee = total_sell_val * fee_rate
            new_balance = balance + (total_sell_val - tx_fee)
            
            # DB Reset
            update_portfolio_holding_in_db(ticker, 0, avg_price)
            new_total_asset = new_balance + sum(
                p_info["quantity"] * market_prices.get(p_tick, 0.0)
                for p_tick, p_info in portfolio.items() if p_tick != ticker
            )
            update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
            
            reasoning = f"[기계적 손절매 청산] 주가가 매수가({avg_price:,.0f}원) 대비 -4.5% 손실 한계선({stop_loss_limit:,.0f}원)에 도달하여 추가 손실 차단을 위해 전량 시장가 매도 처리하였습니다. (현재가: {current_price:,.0f}원)"
            
            snapshot = {
                "prev_balance": balance,
                "new_balance": new_balance,
                "prev_total_asset": prev_total_asset,
                "new_total_asset": new_total_asset,
                "transaction_fee": tx_fee,
                "latest_news_url": news_context[0].get("url", "") if news_context else "",
                "market_prices": market_prices,
                "highest_price_after_buy": new_highest
            }
            
            save_transaction_to_db(ticker, "STOP_LOSS_EXIT", qty, current_price, reasoning, snapshot)
            trigger_telegram_trade_alert(
                ticker=ticker,
                action="STOP_LOSS_EXIT",
                quantity=qty,
                price=current_price,
                reasoning=reasoning,
                balance=new_balance,
                total_asset=new_total_asset
            )
            return {
                "status": "success",
                "action": "SELL",
                "ticker": ticker,
                "quantity": qty,
                "price": current_price,
                "reasoning": reasoning,
                "balance": new_balance,
                "total_asset": new_total_asset
            }
            
        # 3. Trailing-Stop Trigger Check (-3.0% from peak)
        trailing_stop_limit = new_highest * (1 - 0.03)
        if current_price <= trailing_stop_limit:
            print(f"[Trading Engine] [EX-TS] Trailing-Stop triggered for {ticker}! Price {current_price:,.0f} <= Limit {trailing_stop_limit:,.0f} KRW (Highest: {new_highest:,.0f}).")
            qty = holding["quantity"]
            total_sell_val = qty * current_price
            fee_rate = 0.001
            tx_fee = total_sell_val * fee_rate
            new_balance = balance + (total_sell_val - tx_fee)
            
            # DB Reset
            update_portfolio_holding_in_db(ticker, 0, avg_price)
            new_total_asset = new_balance + sum(
                p_info["quantity"] * market_prices.get(p_tick, 0.0)
                for p_tick, p_info in portfolio.items() if p_tick != ticker
            )
            update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
            
            reasoning = f"[기계적 추적손절매 익절] 주가가 매수 후 최고점({new_highest:,.0f}원) 대비 -3.0% 수익보존 한계선({trailing_stop_limit:,.0f}원) 이하로 하락하여, 이익 보존을 위해 전량 시장가 매도 처리하였습니다. (현재가: {current_price:,.0f}원)"
            
            snapshot = {
                "prev_balance": balance,
                "new_balance": new_balance,
                "prev_total_asset": prev_total_asset,
                "new_total_asset": new_total_asset,
                "transaction_fee": tx_fee,
                "latest_news_url": news_context[0].get("url", "") if news_context else "",
                "market_prices": market_prices,
                "highest_price_after_buy": new_highest
            }
            
            save_transaction_to_db(ticker, "TRAILING_STOP_EXIT", qty, current_price, reasoning, snapshot)
            trigger_telegram_trade_alert(
                ticker=ticker,
                action="TRAILING_STOP_EXIT",
                quantity=qty,
                price=current_price,
                reasoning=reasoning,
                balance=new_balance,
                total_asset=new_total_asset
            )
            return {
                "status": "success",
                "action": "SELL",
                "ticker": ticker,
                "quantity": qty,
                "price": current_price,
                "reasoning": reasoning,
                "balance": new_balance,
                "total_asset": new_total_asset
            }

    # Pre-trade asset evaluation for validation logic
    prev_portfolio_value_at_current_prices = sum(
        portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) 
        for t in portfolio
    )
    expected_prev_total_asset_at_current_prices = balance + prev_portfolio_value_at_current_prices

    # 7. Gemini Decision Formulation
    decision = generate_trading_decision(
        portfolio=portfolio,
        balance=balance,
        market_prices=market_prices,
        news_context=news_context,
        market_indicators=market_indicators,
        index_changes=index_changes
    )

    action = decision.action
    ticker = decision.ticker
    allocation_pct = decision.allocation_pct
    reasoning = decision.reasoning
    current_price = market_prices.get(ticker, 0.0)
    
    quantity = 0
    transaction_fee = 0.0
    fee_rate = 0.001  # 0.1% transaction fee / slippage allowance

    # 8. backend Order Override & Validation (Beta Market Shock & Disparity Check)
    if action == "BUY":
        disparity = market_indicators.get(ticker, {}).get("disparity", 100.0) if ticker else 100.0
        
        # Guardrail 4: News Sentiment Filter (Negative News <= -0.3)
        has_bad_news = False
        bad_news_reason = ""
        ticker_news = []
        for n in news_context:
            try:
                tickers_list = json.loads(n.get("impacted_tickers") or "[]")
                if ticker in tickers_list:
                    ticker_news.append(n)
            except:
                pass
                
        if ticker_news:
            avg_sent = sum(n.get("sentiment_score", 0.0) for n in ticker_news) / len(ticker_news)
            if avg_sent <= -0.3:
                has_bad_news = True
                bad_news_reason = f"최근 24시간 감성 점수 극도 악재 ({avg_sent:+.2f})"
        
        # Targeted Market Shock: Block ONLY if the stock's specific home exchange (KOSPI vs KOSDAQ) crashed by -1.5% or more!
        ticker_market = market_indicators.get(ticker, {}).get("market", "KOSPI") if ticker else "KOSPI"
        market_change = index_changes.get(ticker_market, 0.0)
        is_ticker_market_shock = market_change <= -1.5
        shock_reason = f"소속 거래소: {ticker_market} | 지수 당일 등락률: {market_change:+.2f}%"

        # Sugeup Dump Guardrail: Override BUY if both foreigner and institution are selling heavily
        frgn_net_5d = market_indicators.get(ticker, {}).get("frgn_net_5d", 0)
        inst_net_5d = market_indicators.get(ticker, {}).get("inst_net_5d", 0)
        avg_vol_5d = market_indicators.get(ticker, {}).get("avg_volume_5d", 0)
        
        is_sugeup_dump = False
        combined_net_sell = 0
        if frgn_net_5d < 0 and inst_net_5d < 0:
            combined_net_sell = abs(frgn_net_5d + inst_net_5d)
            if combined_net_sell > (avg_vol_5d * 0.5):
                is_sugeup_dump = True

        if is_ticker_market_shock:
            print(f"[Trading Engine] BUY Order Overridden by Market Shock: {shock_reason}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 시장 쇼크] Gemini AI가 매수를 결정했으나 해당 주식의 소속 거래소({ticker_market}) 지수가 -1.5% 이상 패닉 급락 중이므로 추가 대방어 기각 규칙이 작동하여 HOLD 처리했습니다. ({shock_reason})"
        elif disparity >= 115.0:
            print(f"[Trading Engine] BUY Order Overridden by Disparity Limit: {disparity}% >= 115.0%")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 가격 과열] Gemini AI가 매수를 결정했으나 20일선 이격도가 {disparity}%로 과열 임계치(115%)를 초과하여 상단 꼭대기 설거지 방지 기각 규칙이 작동하여 HOLD 처리했습니다."
        elif has_bad_news:
            print(f"[Trading Engine] BUY Order Overridden by Bad News Filter: {bad_news_reason}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 악재 뉴스 필터] Gemini AI가 매수를 결정했으나 {bad_news_reason} 우려로 백엔드 필터가 매수를 전면 차단하였습니다."
        elif is_sugeup_dump:
            print(f"[Trading Engine] BUY Order Overridden by Sugeup Dump: Frgn={frgn_net_5d}, Inst={inst_net_5d}, 5dAvgVol={avg_vol_5d}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 수급 폭락] Gemini AI가 매수를 결정했으나 최근 5일간 외국인({frgn_net_5d:+,}주)과 기관({inst_net_5d:+,}주)의 동시 순매도 합산량({combined_net_sell:,}주)이 5일 평균 거래량({avg_vol_5d:,.0f}주)의 50%를 초과하는 수급 폭락 상태이므로 대방어 기각 규칙이 작동하여 HOLD 처리했습니다."
        else:
            # Sizing & Guardrails cash calculation
            allocated_cash = balance * (allocation_pct / 100.0)
            
            # Guardrail 1: 30% Sizing Limit of Total Asset
            portfolio_value = sum(portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) for t in portfolio)
            total_asset = balance + portfolio_value
            max_allowed_cash = total_asset * 0.3
            
            # Already owned value check
            owned_value = portfolio.get(ticker, {}).get("quantity", 0) * current_price
            max_new_cash = max(max_allowed_cash - owned_value, 0.0)
            
            spend_cash = min(allocated_cash, max_new_cash)
            sizing_triggered = allocated_cash > max_new_cash
            
            # Guardrail 2: KOSPI 5일선 연동 약세장 방어
            bear_triggered = False
            if is_kospi_bear_market():
                spend_cash *= 0.5
                bear_triggered = True
                
            # Guardrail 3: 이격도 108%~115% 비례 매수 제한 (50% 감감)
            disparity_50_triggered = False
            if 108.0 <= disparity < 115.0:
                spend_cash *= 0.5
                disparity_50_triggered = True

            # Guardrail 4: Sector Allocation Limit (45%)
            target_sector = TICKER_TO_SECTOR.get(ticker, "기타")
            current_sector_value = sum(
                info.get("quantity", 0) * market_prices.get(t, 0.0)
                for t, info in portfolio.items()
                if TICKER_TO_SECTOR.get(t, "기타") == target_sector
            )
            max_sector_allowed_value = total_asset * 0.45
            max_additional_sector_cash = max(max_sector_allowed_value - current_sector_value, 0.0)
            
            sector_cap_triggered = False
            if spend_cash > max_additional_sector_cash:
                spend_cash = max_additional_sector_cash
                sector_cap_triggered = True
                
            # Final quantity calculation
            quantity = int(spend_cash / (current_price * (1 + fee_rate)))
            
            # Reasoning logging
            gate_reasons = []
            if sizing_triggered:
                gate_reasons.append("30% 보유 한도 제한")
            if bear_triggered:
                gate_reasons.append("약세장 방어")
            if disparity_50_triggered:
                gate_reasons.append("이격 과열 50% 감폭")
            if sector_cap_triggered:
                gate_reasons.append("섹터 비중 45% 제한")
                
            if gate_reasons:
                reasoning += f" [가드레일 작동: {', '.join(gate_reasons)}]"
                
            if quantity <= 0:
                action = "HOLD"
                if sector_cap_triggered:
                    reasoning += " (섹터 비중 45% 초과로 인해 HOLD 처리됨)"
                else:
                    reasoning += " (매수 가용 자금 또는 수량 부족으로 HOLD 처리됨)"

    elif action == "SELL":
        owned_quantity = portfolio.get(ticker, {}).get("quantity", 0)
        quantity = int(owned_quantity * (allocation_pct / 100.0))
        if quantity <= 0:
            action = "HOLD"
            reasoning += " (매도 가능 수량 부족으로 HOLD 처리됨)"

    # 8.5. Standard Execution Filter
    if action in ["BUY", "SELL"] and (current_price <= 0 or not ticker or quantity <= 0):
        if action in ["BUY", "SELL"]:
            print(f"[Trading Engine] Order Rejected: Price for ticker {ticker} is invalid or quantity is 0.")
            action = "HOLD"
            reasoning = f"시스템오류: 종목코드 {ticker}의 시세 조회가 불가능하거나 거래 수량이 0이어서 HOLD 처리했습니다."
            quantity = 0

    if action == "BUY" and quantity > 0:
        required_cash = quantity * current_price * (1 + fee_rate)
        if required_cash > balance:
            print(f"[Trading Engine] REJECTED_BY_BACKEND: BUY order of {quantity} shares of {ticker} requires {required_cash:,.0f} KRW but balance is only {balance:,.0f} KRW.")
            action = "HOLD"
            reasoning = f"REJECTED_BY_BACKEND: 매입 필요 자금({required_cash:,.0f}원)이 가용 예수금({balance:,.0f}원)을 초과하여 주문이 거부되었습니다."
            quantity = 0
            
    elif action == "SELL" and quantity > 0:
        owned_quantity = portfolio.get(ticker, {}).get("quantity", 0)
        if quantity > owned_quantity:
            print(f"[Trading Engine] REJECTED_BY_BACKEND: SELL order of {quantity} shares of {ticker} exceeds owned quantity ({owned_quantity} shares).")
            action = "HOLD"
            reasoning = f"REJECTED_BY_BACKEND: 매도 요청 수량({quantity}주)이 실제 보유 수량({owned_quantity}주)을 초과하여 주문이 거부되었습니다."
            quantity = 0

    # 9. Perform Accounting & Process Updates
    new_balance = balance
    new_portfolio = {t: dict(info) for t, info in portfolio.items()}

    if action == "BUY" and quantity > 0:
        total_buy_cost = quantity * current_price
        transaction_fee = total_buy_cost * fee_rate
        
        new_balance = balance - (total_buy_cost + transaction_fee)
        
        # Recalculate average price
        current_holding = portfolio.get(ticker, {"quantity": 0, "average_price": 0.0})
        prev_qty = current_holding["quantity"]
        prev_avg = current_holding["average_price"]
        
        new_qty = prev_qty + quantity
        new_avg = ((prev_qty * prev_avg) + (quantity * current_price)) / new_qty
        
        new_portfolio[ticker] = {
            "quantity": new_qty,
            "average_price": new_avg,
            "highest_price_after_buy": max(current_price, current_holding.get("highest_price_after_buy", current_price))
        }
        
        # Save to DB
        update_portfolio_holding_in_db(ticker, new_qty, new_avg, new_portfolio[ticker]["highest_price_after_buy"])

    elif action == "SELL" and quantity > 0:
        total_sell_val = quantity * current_price
        transaction_fee = total_sell_val * fee_rate
        
        new_balance = balance + (total_sell_val - transaction_fee)
        
        current_holding = portfolio.get(ticker, {"quantity": 0, "average_price": 0.0})
        prev_qty = current_holding["quantity"]
        prev_avg = current_holding["average_price"]
        
        new_qty = prev_qty - quantity
        
        if new_qty <= 0:
            if ticker in new_portfolio:
                del new_portfolio[ticker]
        else:
            new_portfolio[ticker] = {
                "quantity": new_qty,
                "average_price": prev_avg,
                "highest_price_after_buy": current_holding.get("highest_price_after_buy", current_price)
            }
            
        # Save to DB
        update_portfolio_holding_in_db(ticker, new_qty, prev_avg, current_holding.get("highest_price_after_buy", current_price))

    # Calculate new total asset based on current prices
    new_portfolio_value_at_current_prices = sum(
        new_portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) 
        for t in new_portfolio
    )
    new_total_asset = new_balance + new_portfolio_value_at_current_prices

    # 10. Accounting Assert Check
    expected_new_total_asset = expected_prev_total_asset_at_current_prices - transaction_fee
    discrepancy = abs(new_total_asset - expected_new_total_asset)

    print(f"[Trading Engine] Accounting Check: Calculated New Asset = {new_total_asset:,.2f} KRW | Expected New Asset = {expected_new_total_asset:,.2f} KRW")
    
    if discrepancy > 10.0 or new_balance < 0:
        error_msg = f"CRITICAL_ACCOUNTING_FAULT: Discrepancy of {discrepancy:,.2f} KRW detected or Negative Balance ({new_balance:,.2f} KRW) reached! Mathematical safety breach."
        print(f"[Trading Engine] {error_msg}")
        lock_system()
        # Log transaction as a critical failure
        save_transaction_to_db(
            ticker=ticker,
            action="SYSTEM_LOCK_ERROR",
            quantity=quantity,
            price=current_price,
            reasoning=error_msg,
            snapshot_context={
                "prev_balance": balance,
                "new_balance": new_balance,
                "discrepancy": discrepancy,
                "expected_new_total_asset": expected_new_total_asset,
                "new_total_asset": new_total_asset
            }
        )
        sys.exit(error_msg)

    # 11. Log Transaction & Update State in Database
    update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
    
    # Save transaction history doc
    snapshot_context = {
        "prev_balance": balance,
        "new_balance": new_balance,
        "prev_total_asset": prev_total_asset,
        "new_total_asset": new_total_asset,
        "transaction_fee": transaction_fee,
        "latest_news_url": news_context[0].get("url", "") if news_context else "",
        "market_prices": market_prices
    }
    
    save_transaction_to_db(
        ticker=ticker,
        action=action,
        quantity=quantity,
        price=current_price,
        reasoning=reasoning,
        snapshot_context=snapshot_context
    )

    if action in ["BUY", "SELL"]:
        trigger_telegram_trade_alert(
            ticker=ticker,
            action=action,
            quantity=quantity,
            price=current_price,
            reasoning=reasoning,
            balance=new_balance,
            total_asset=new_total_asset
        )

    return {
        "status": "success",
        "action": action,
        "ticker": ticker,
        "quantity": quantity,
        "price": current_price,
        "reasoning": reasoning,
        "balance": new_balance,
        "total_asset": new_total_asset
    }

if __name__ == "__main__":
    print("[Trading Engine] Initialized as standalone. Testing yfinance connection...")
    price = get_stock_price("005930")
    print(f"Samsung Electronics (005930) Price: {price:,.0f} KRW")
