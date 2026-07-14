import os
import sqlite3
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

import db
from firebase_admin import firestore

_trading_cache_warmed = False

def get_kst_now():
    """
    Returns the current datetime in KST (Korea Standard Time).
    """
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst)

def get_firestore_client():
    """
    Retrieves the Firestore client from the db module.
    Forces initialization if not already done.
    """
    if not db.FIREBASE_AVAILABLE:
        print("[Trading DB] [Warning] firebase-admin package is not available!")
        return None
    if not db.USE_FIREBASE or db.db_client is None:
        db.init_db()
    return db.db_client

def _ensure_trading_tables(cursor):
    cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS portfolio (ticker TEXT PRIMARY KEY, quantity INTEGER, average_price REAL, highest_price_after_buy REAL, mode TEXT DEFAULT 'VALUE', last_scale_out_date TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, timestamp TEXT, ticker TEXT, action TEXT, quantity INTEGER, price REAL, reasoning TEXT, snapshot_context TEXT)")
    try:
        cursor.execute("ALTER TABLE portfolio ADD COLUMN mode TEXT DEFAULT 'VALUE'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE portfolio ADD COLUMN last_scale_out_date TEXT")
    except sqlite3.OperationalError:
        pass

def warm_start_trading_cache():
    """
    Synchronizes agent state, portfolio holdings, and transaction history
    from Firestore into the local SQLite database at startup.
    """
    global _trading_cache_warmed
    if _trading_cache_warmed:
        return
        
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        
        # Create trading cache tables and run migrations
        _ensure_trading_tables(cursor)
        conn.commit()
        
        client = get_firestore_client()
        if client is None:
            # Running in offline demo mode, no Firestore to sync from
            conn.close()
            _trading_cache_warmed = True
            return
         
        print("[Trading DB] Synchronizing SQLite cache with Firestore...")
        
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
                INSERT OR REPLACE INTO portfolio (ticker, quantity, average_price, highest_price_after_buy, mode, last_scale_out_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                doc.id,
                int(data.get("quantity", 0)),
                float(data.get("average_price", 0.0)),
                float(data.get("highest_price_after_buy", data.get("average_price", 0.0))),
                data.get("mode", "VALUE"),
                data.get("last_scale_out_date")
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
        print("[Trading DB] Successfully warm-started trading cache from Firestore.")
    except Exception as e:
        print(f"[Trading DB] [Warning] Failed to warm-start trading cache: {e}")

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
        print(f"[Trading DB] [Warning] Failed to fetch agent state from SQLite cache: {e}")
        
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
        print(f"[Trading DB] [Warning] Failed to update agent state in SQLite cache: {e}")
        
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
        print(f"[Trading DB] [Error] Failed to update agent state in Firestore: {e}")
        return False

def lock_system() -> bool:
    """
    Locks the trading system in both Firestore and local SQLite cache due to critical failures.
    """
    # 1. Lock SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.conn.cursor() # Wait, it is conn.cursor()
    except:
        pass
        
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS agent_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("system_lock", "True"))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Trading DB] [Warning] Failed to lock system in SQLite cache: {e}")
        
    # 2. Lock Firestore
    client = get_firestore_client()
    if client is None:
        return True
    try:
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "system_lock": True
        })
        print("[Trading DB] [ALERT] System has been locked successfully due to critical anomaly.")
        return True
    except Exception as e:
        print(f"[Trading DB] [Error] Failed to lock system in Firestore: {e}")
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
        print(f"[Trading DB] [Warning] Failed to extend start_date in SQLite cache: {e}")
        
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
        print(f"[Trading DB] [Error] Failed to extend start_date in Firestore: {e}")
        return False

def get_portfolio_holdings() -> Dict[str, Dict[str, Any]]:
    """
    Fetches the active stock portfolio holdings from local SQLite cache.
    """
    warm_start_trading_cache()
    
    try:
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_trading_tables(cursor)
        cursor.execute("SELECT ticker, quantity, average_price, highest_price_after_buy, mode, last_scale_out_date FROM portfolio")
        rows = cursor.fetchall()
        conn.close()
        
        holdings = {}
        for r in rows:
            qty = int(r["quantity"])
            if qty > 0:
                holdings[r["ticker"]] = {
                    "quantity": qty,
                    "average_price": float(r["average_price"]),
                    "highest_price_after_buy": float(r["highest_price_after_buy"]),
                    "mode": r["mode"] if r["mode"] else "VALUE",
                    "last_scale_out_date": r["last_scale_out_date"]
                }
        return holdings
    except Exception as e:
        print(f"[Trading DB] [Warning] Failed to fetch portfolio holdings from SQLite cache: {e}")
        return {}

def update_portfolio_holding_in_db(ticker: str, quantity: int, average_price: float, highest_price_after_buy: Optional[float] = None, mode: Optional[str] = None, last_scale_out_date: Optional[str] = None) -> bool:
    """
    Updates or deletes a specific stock holding in both Firestore and SQLite cache.
    """
    # 1. Update SQLite cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        _ensure_trading_tables(cursor)
        
        if quantity <= 0:
            cursor.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))
            conn.commit()
            conn.close()
            print(f"[Trading DB] [SQLite] Deleted holding for ticker {ticker}.")
            sqlite_success = True
        else:
            # Get existing values if not provided
            cursor.execute("SELECT highest_price_after_buy, mode, last_scale_out_date FROM portfolio WHERE ticker = ?", (ticker,))
            row = cursor.fetchone()
            
            h_price = highest_price_after_buy
            p_mode = mode
            p_scale_out = last_scale_out_date
            
            if row:
                if h_price is None:
                    h_price = float(row[0]) if row[0] is not None else average_price
                if p_mode is None:
                    p_mode = row[1]
                if p_scale_out is None:
                    p_scale_out = row[2]
            else:
                if h_price is None:
                    h_price = average_price
                if p_mode is None:
                    p_mode = "VALUE"
            
            cursor.execute("""
                INSERT OR REPLACE INTO portfolio (ticker, quantity, average_price, highest_price_after_buy, mode, last_scale_out_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ticker, int(quantity), float(average_price), float(h_price), p_mode, p_scale_out))
            conn.commit()
            conn.close()
            print(f"[Trading DB] [SQLite] Updated holding for ticker {ticker}: Quantity={quantity}, AvgPrice={average_price:.1f}, Highest={h_price:.1f}, Mode={p_mode}, ScaleOut={p_scale_out}")
            sqlite_success = True
    except Exception as e:
        print(f"[Trading DB] [Warning] Failed to update portfolio holding in SQLite cache: {e}")
        sqlite_success = False

    # 2. Update Firestore
    client = get_firestore_client()
    if client is None:
        return sqlite_success
    try:
        holding_ref = client.collection("agents").document("state").collection("portfolio").document(ticker)
        if quantity <= 0:
            holding_ref.delete()
            print(f"[Trading DB] [Firestore] Deleted holding for ticker {ticker}.")
        else:
            payload = {
                "quantity": int(quantity),
                "average_price": float(average_price),
                "mode": p_mode if p_mode else "VALUE"
            }
            if h_price is not None:
                payload["highest_price_after_buy"] = float(h_price)
            if p_scale_out is not None:
                payload["last_scale_out_date"] = p_scale_out
            else:
                payload["last_scale_out_date"] = None
                
            holding_ref.set(payload)
            print(f"[Trading DB] [Firestore] Updated holding for ticker {ticker}: Quantity={quantity}, Mode={p_mode}")
        return True
    except Exception as e:
        print(f"[Trading DB] [Error] Failed to update portfolio holding in Firestore: {e}")
        return False

def get_last_sell_transaction(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Queries the database for the last sell-related transaction of a ticker.
    """
    warm_start_trading_cache()
    try:
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_trading_tables(cursor)
        cursor.execute("""
            SELECT timestamp, price, action FROM transactions 
            WHERE ticker = ? AND action IN ('SELL', 'STOP_LOSS_EXIT', 'TRAILING_STOP_EXIT')
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker.strip(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[Trading DB] [Warning] Failed to query last sell transaction for {ticker}: {e}")
        return None

def get_last_transaction_of_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Queries the database for the last transaction of any action for a ticker.
    """
    warm_start_trading_cache()
    try:
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        _ensure_trading_tables(cursor)
        cursor.execute("""
            SELECT timestamp, price, action FROM transactions 
            WHERE ticker = ? 
            ORDER BY timestamp DESC LIMIT 1
        """, (ticker.strip(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[Trading DB] [Warning] Failed to query last transaction for {ticker}: {e}")
        return None

def save_transaction_to_db(ticker: str, action: str, quantity: int, price: float, reasoning: str, snapshot_context: Dict[str, Any]) -> bool:
    """
    Saves a trading transaction record to both Firestore and SQLite cache.
    """
    now_str = get_kst_now().isoformat()
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
        print(f"[Trading DB] [Warning] Failed to save transaction to SQLite cache: {e}")
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
        print(f"[Trading DB] Logged transaction to Firestore: {action} {quantity} shares of {ticker} at {price:,.0f} KRW.")
        return True
    except Exception as e:
        print(f"[Trading DB] [Error] Failed to save transaction to Firestore: {e}")
        return False

def trigger_telegram_trade_alert(ticker: str, action: str, quantity: int, price: float, reasoning: str, balance: float, total_asset: float):
    """
    Loads Telegram bot settings and triggers a trade alert if configured.
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
            
        # Fallback to environment variables
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
        print(f"[Trading DB] [Warning] Telegram trade alert trigger failed: {e}")

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
        print(f"[Trading DB] [Warning] Failed to fetch transaction logs from SQLite cache: {e}")
        
    # Fallback to Firestore
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
        print(f"[Trading DB] [Error] Failed to fetch transaction logs from Firestore: {e}")
        return []
