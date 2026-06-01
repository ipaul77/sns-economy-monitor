import os
import sys
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
from typing import Literal
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor


# Import the existing DB module to reuse Firestore configuration
import db

try:
    from firebase_admin import firestore
except ImportError:
    pass

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

def get_agent_state() -> Dict[str, Any]:
    """
    Fetches the agent's current balance, total_asset, start_date, and system_lock status from Firestore.
    Initializes them if the state document does not exist.
    """
    client = get_firestore_client()
    if client is None:
        # Fallback for offline demo mode
        return {
            "balance": 10000000.0,
            "total_asset": 10000000.0,
            "start_date": get_kst_now().isoformat(),
            "system_lock": False
        }
        
    try:
        state_ref = client.collection("agents").document("state")
        doc = state_ref.get()
        
        if not doc.exists:
            now_str = get_kst_now().isoformat()
            initial_state = {
                "balance": 10000000.0,  # 10,000,000 KRW
                "total_asset": 10000000.0,
                "start_date": now_str,
                "system_lock": False
            }
            state_ref.set(initial_state)
            print("[Trading Engine] Successfully initialized agent state in Firestore.")
            return initial_state
            
        return doc.to_dict()
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to fetch agent state from Firestore: {e}")
        # Return fallback state
        return {
            "balance": 10000000.0,
            "total_asset": 10000000.0,
            "start_date": get_kst_now().isoformat(),
            "system_lock": False
        }

def update_agent_state_in_db(balance: float, total_asset: float, system_lock: bool = False) -> bool:
    """
    Updates the agent's state document in Firestore.
    """
    client = get_firestore_client()
    if client is None:
        return False
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
    Locks the trading system in Firestore due to critical failures.
    """
    client = get_firestore_client()
    if client is None:
        return False
    try:
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "system_lock": True
        })
        print("[Trading Engine] [ALERT] System has been locked successfully due to critical anomaly.")
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to lock system: {e}")
        return False

def get_portfolio_holdings() -> Dict[str, Dict[str, Any]]:
    """
    Fetches the agent's active stock portfolio holdings from Firestore subcollection.
    Path: agents/state/portfolio/{ticker}
    Returns a dict: { ticker: { "quantity": int, "average_price": float, "highest_price_after_buy": float } }
    """
    client = get_firestore_client()
    if client is None:
        return {}
        
    holdings = {}
    try:
        portfolio_ref = client.collection("agents").document("state").collection("portfolio")
        docs = portfolio_ref.stream()
        for doc in docs:
            data = doc.to_dict()
            ticker = doc.id
            holdings[ticker] = {
                "quantity": int(data.get("quantity", 0)),
                "average_price": float(data.get("average_price", 0.0)),
                "highest_price_after_buy": float(data.get("highest_price_after_buy", data.get("average_price", 0.0)))
            }
        return holdings
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to fetch portfolio holdings from Firestore: {e}")
        return {}

def update_portfolio_holding_in_db(ticker: str, quantity: int, average_price: float, highest_price_after_buy: Optional[float] = None) -> bool:
    """
    Updates or deletes a specific stock holding in Firestore portfolio subcollection.
    If quantity <= 0, deletes the holding document.
    """
    client = get_firestore_client()
    if client is None:
        return False
    try:
        holding_ref = client.collection("agents").document("state").collection("portfolio").document(ticker)
        if quantity <= 0:
            holding_ref.delete()
            print(f"[Trading Engine] Deleted holding for ticker {ticker} (Quantity reached 0).")
        else:
            payload = {
                "quantity": int(quantity),
                "average_price": float(average_price)
            }
            if highest_price_after_buy is not None:
                payload["highest_price_after_buy"] = float(highest_price_after_buy)
            else:
                # Fallback to existing or initialize with average_price
                doc = holding_ref.get()
                if doc.exists:
                    payload["highest_price_after_buy"] = float(doc.to_dict().get("highest_price_after_buy", average_price))
                else:
                    payload["highest_price_after_buy"] = float(average_price)
                    
            holding_ref.set(payload)
            print(f"[Trading Engine] Updated holding for ticker {ticker}: Quantity={quantity}, AvgPrice={average_price:.1f}, Highest={payload['highest_price_after_buy']:.1f}")
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to update portfolio holding in Firestore: {e}")
        return False

def save_transaction_to_db(ticker: str, action: str, quantity: int, price: float, reasoning: str, snapshot_context: Dict[str, Any]) -> bool:
    """
    Saves a trading transaction record to Firestore in the 'transactions' collection.
    """
    client = get_firestore_client()
    if client is None:
        return False
    try:
        now_str = get_kst_now().isoformat()
        tx_ref = client.collection("transactions").document()
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
        print(f"[Trading Engine] Logged transaction: {action} {quantity} shares of {ticker} at {price:,.0f} KRW.")
        return True
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to save transaction to Firestore: {e}")
        return False

def get_latest_transactions(limit: int = 15) -> List[Dict[str, Any]]:
    """
    Retrieves the latest transaction logs from Firestore sorted by timestamp descending.
    """
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
        print(f"[Trading Engine] [Error] Failed to fetch transaction logs: {e}")
        return []

# ---------------------------------------------------------------------------
# DYNAMIC AI STOCK CANDIDATE PIPELINE MAPPING
# ---------------------------------------------------------------------------
COMPANY_TO_TICKER = {
    "ì¼ì±ì ì": "005930",
    "SKíì´ëì¤": "000660",
    "íì´ëì¤": "000660",
    "íëì°¨": "005380",
    "íëìëì°¨": "005380",
    "ê¸°ì": "000270",
    "ê¸°ìì°¨": "000270",
    "NAVER": "035420",
    "ë¤ì´ë²": "035420",
    "ì¹´ì¹´ì¤": "035720",
    "LGìëì§ìë£¨ì": "373220",
    "LGìì": "373220",
    "ì¼ì±SDI": "006400",
    "LGíí": "051910",
    "í¬ì¤ì½íë©ì¤": "005490",
    "POSCOíë©ì¤": "005490",
    "ìí¸ë¦¬ì¨": "068270",
    "íë¯¸ë°ëì²´": "042700",
    "ìì½íë¡": "086520",
    "ìì½íë¡ë¹ì ": "247540",
    "í¬ì¤ì½í¨ì²ì ": "003670",
    "ë„¤ì ´ë²„": "035420",
    "ì¹´ì¹´ì˜¤": "035720",
    "LGì— ë„ˆì§€ì†”ë£¨ì…˜": "373220",
    "LGì—”ì†”": "373220",
    "ì‚¼ì„±SDI": "006400",
    "LGí™”í•™": "051910",
    "í ¬ìŠ¤ì½”í™€ë”©ìŠ¤": "005490",
    "POSCOí™€ë”©ìŠ¤": "005490",
    "ì…€íŠ¸ë¦¬ì˜¨": "068270",
    "í•œë¯¸ë°˜ë „ì²´": "042700",
    "ì— ì½”í”„ë¡œ": "086520",
    "ì— ì½”í”„ë¡œë¹„ì— ": "247540",
    "í ¬ìŠ¤ì½”í“¨ì²˜ì— ": "003670",
    "SKì ´ë…¸ë² ì ´ì…˜": "096770",
    "ì‚¼ì„±ë¬¼ì‚°": "028260",
    "KBê¸ˆìœµ": "105560",
    "KBê¸ˆìœµì§€ì£¼": "105560",
    "ì‹ í•œì§€ì£¼": "055550",
    "ì‹ í•œê¸ˆìœµì§€ì£¼": "055550",
    "í•˜ë‚˜ê¸ˆìœµì§€ì£¼": "086790",
    "ì‚¼ì„±ë°”ì ´ì˜¤ë¡œì§ ìŠ¤": "207940",
    "ì•Œí…Œì˜¤ì  ": "196170",
    "HLB": "028300",
    "HMM": "011200",
    "ëŒ€í•œí•­ê³µ": "003490",
    "ë‘ ì‚°ì— ë„ˆë¹Œë¦¬í‹°": "034020",
    "HDí˜„ëŒ€ì¤‘ê³µì—…": "329180",
    "ìœ í•œì–‘í–‰": "000100"
}

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
    3. News context: Any South Korean company mentioned in the latest news context is mapped to a ticker.
    4. Ticker context: Tickers dynamically resolved by Gemini are directly added.
    """
    dynamic_7 = get_dynamic_top_7_stocks()
    active_tickers = set(dynamic_7)
    
    # 1. Include currently owned portfolio holdings
    for ticker in portfolio.keys():
        active_tickers.add(ticker)
        
    # 2. Extract tickers dynamically resolved by Gemini Deep Analysis
    for item in news_context:
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
                            active_tickers.add(t)
            except Exception:
                pass

    # 3. Extract company mentions from the latest analyzed news (Legacy fallback)
    for item in news_context:
        impacted_val = item.get("impacted_companies")
        if not impacted_val:
            continue
            
        try:
            if isinstance(impacted_val, str):
                companies = json.loads(impacted_val)
            elif isinstance(impacted_val, list):
                companies = impacted_val
            else:
                companies = []
                
            if isinstance(companies, list):
                for comp in companies:
                    ticker = COMPANY_TO_TICKER.get(str(comp).strip())
                    if ticker:
                        active_tickers.add(ticker)
            else:
                ticker = COMPANY_TO_TICKER.get(str(impacted_val).strip())
                if ticker:
                    active_tickers.add(ticker)
        except Exception:
            # Heuristic parsing for comma-separated or plain text company names
            parts = [x.strip() for x in str(impacted_val).split(",") if x.strip()]
            for part in parts:
                ticker = COMPANY_TO_TICKER.get(part)
                if ticker:
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
        "message": "ìì¥ êµ­ë©´ ë¶ì ì¤í¨ (ê¸°ë³¸ê° ìì¹ êµ­ë©´ì¼ë¡ ì°í)"
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
        "volume_breakout": False
    }
    if not ticker:
        return result

    # Standard suffix translation logic (KS/KQ)
    full_ticker = ticker
    if len(ticker) == 6 and ticker.isdigit():
        for suffix in [".KS", ".KQ"]:
            t_obj = yf.Ticker(ticker + suffix)
            try:
                hist = t_obj.history(period="1mo")
                if not hist.empty and len(hist) >= 2:
                    full_ticker = ticker + suffix
                    break
            except:
                pass

    try:
        yt = yf.Ticker(full_ticker)
        hist = yt.history(period="1mo")
        if hist.empty:
            fallback_prices = {
                "005930": 78200.0, "000660": 195400.0, "005380": 265000.0,
                "000270": 121000.0, "035420": 182000.0, "035720": 48500.0
            }
            price = fallback_prices.get(ticker, 0.0)
            if price > 0:
                result["current_price"] = price
                result["ma_20"] = price
                result["disparity"] = 100.0
            return result

        # 1. Current Price
        current_price = float(hist["Close"].iloc[-1])
        result["current_price"] = current_price

        # 2. 20-day Moving Average (20 MA)
        ma_length = min(len(hist), 20)
        close_slice = hist["Close"].iloc[-ma_length:]
        ma_20 = float(close_slice.mean())
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
        fallback_prices = {"005930": 78200.0, "000660": 195400.0}
        price = fallback_prices.get(ticker, 50000.0)
        result["current_price"] = price
        result["ma_20"] = price
        result["disparity"] = 100.0

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
        suffixes = [".KS", ".KQ"]
        for suffix in suffixes:
            full_ticker = ticker + suffix
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
            except Exception as e:
                # Silently try next suffix
                pass
        
        # Static mock pricing fallbacks if network is down or yfinance fails completely
        fallback_prices = {
            "005930": 78200.0,  # Samsung Electronics
            "000660": 195400.0, # SK Hynix
            "005380": 265000.0, # Hyundai Motor
            "000270": 121000.0, # Kia
            "035420": 182000.0, # Naver
            "035720": 48500.0,  # Kakao
            "373220": 365000.0, # LG Energy Solution
            "006400": 395000.0, # Samsung SDI
            "005490": 382000.0, # POSCO Holdings
            "068270": 188000.0  # Celltrion
        }
        fallback = fallback_prices.get(ticker)
        if fallback:
            print(f"[Trading Engine] [Warning] yfinance failed for K-ticker {ticker}. Using static fallback price: {fallback:,.0f} KRW.")
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
                
    # 1. Goal-Based Investing (ROI Target: +10% in 30 days)
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
    target_roi = 10.0 # +10% ROI Target
    target_asset = initial_asset * (1.0 + (target_roi / 100.0))

    # Format portfolio state for the prompt
    portfolio_str = ""
    if not portfolio:
        portfolio_str = "ë³´ì íê³  ìë ì£¼ìì´ ììµëë¤."
    else:
        for tick, info in portfolio.items():
            current_price = market_prices.get(tick, 0.0)
            avg_price = info["average_price"]
            qty = info["quantity"]
            pl_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            portfolio_str += f"- ì¢ëª©ì½ë: {tick} | ë³´ì ìë: {qty}ì£¼ | íê·  ë§¤ìê°: {avg_price:,.0f}ì | íì¬ê°: {current_price:,.0f}ì (ììµë¥ : {pl_rate:+.2f}%)\n"

    # Format market prices
    prices_str = "\n".join([f"- ì¢ëª©ì½ë: {tick} | íì¬ ì²´ê²°ê°: {price:,.0f}ì" for tick, price in market_prices.items()])

    # Format index changes
    index_str = "ì§ì ì ë³´ ìì"
    if index_changes:
        index_str = ", ".join([f"{name}: {val:+.2f}%" for name, val in index_changes.items()])

    # Format indicators
    indicators_str = ""
    # Format news analysis context
    news_str = ""
    if not news_context:
        news_str = "ìµê·¼ 24ìê° ëì ìì§ë íêµ­ ê²½ì  ê´ë ¨ ì ê· ë´ì¤ê° ììµëë¤. ë´ì¤ í¸ì¬ê° ìëë¼ë ì´ê²©ë, ê±°ëë ëí ë¹ì¨ ë± ê¸°ì ì  ì§íê° ëë ·íë©´ ëª¨ë©í ê±°ëë¥¼ ê³ ë ¤í  ì ììµëë¤."
    else:
        for idx, item in enumerate(news_context[:10]):  # Limit to top 10 relevant stories
            news_str += (
                f"{idx+1}. [{item.get('source', 'ë´ì¤')}] {item.get('title', '')} (ì¤ìë: {item.get('relevance_score', 5)}/10) \n"
                f"   - ê°ì±ìì¤: {item.get('sentiment', 'NEUTRAL')} (ì ì: {item.get('sentiment_score', 0.0):+.2f}) \n"
                f"   - AI ë¶ì ìì½: {item.get('korean_summary', '')} \n"
                f"   - ì¦ì ìí¥ íê°: {item.get('macro_impacts', '')} \n"
            )

    # Define system instructions (Guardrails)
    system_instruction = (
        "ëë ì£¼ì´ì§ ê°ì ìì° ë²ì ë´ììë§ ìê¸ì ì´ì©íë ë§¤ì° ë³´ìì ì´ê³  í©ë¦¬ì ì¸ AI ì£¼ì í¬ì ìì´ì í¸ì¼.\n"
        "ëì ì­í ì ìì¥ ê°ê²©, ì§ì ëí¥, ê°ë³ ê¸°ì  ì§í ë° ìµì  ë´ì¤ ì»¨íì¤í¸ë¥¼ ê¸°ë°ì¼ë¡ ìµì ì ë§¤ì/ë§¤ë/ê´ë§(BUY/SELL/HOLD) ìì¬ ê²°ì ì ë´ë¦¬ë ê²ì´ë¤.\n\n"
        "--- ìê²©í íë ê°ë ¹ (Guardrails) ---\n"
        "1. ëìê²ë ìì°ì ì§ì  ê³ì°íê±°ë ì²´ê²° ì¥ë¶ë¥¼ ë³ê²½í  ê¶íì´ ìë¤. ì¤ì§ 'í¬ì íë¨ ìê·¸ë'ë§ ì¬ë°ë¥¸ JSON êµ¬ì¡°ë¡ ë°íí  ì ìë¤.\n"
        "2. ë´ì¤ ë¶ìì´ ìê³  ê¸°ì ì  ì§í(ì´ê²©ë, ê±°ëë) ì¸¡ë©´ììë ê±°ëí  ëë ·í ìê·¸ë(ëí ëë ëí­ ê³¼ë ë°ë±)ì´ ìë¤ë©´ 'HOLD'ë¥¼ ì íí´ë¼.\n"
        "3. ë§¤ìë¥¼ í  ëë íì¬ ë³´ì  ì¤ì¸ ììê¸(Cash Balance) ëë¹ ì§ìí  ë¹ì¨(allocation_pct, 0.0% ~ 100.0%)ì ìë ¥í´ë¼. ì ë ììê¸ì ì´ê³¼í  ì ìë¤.\n"
        "4. ë§¤ëë¥¼ í  ëë íì¬ ë³´ì  ì¤ì¸ í¹ì  ì£¼ìì ìë ëë¹ ë§¤ëí  ë¹ì¨(allocation_pct, 0.0% ~ 100.0%)ì ìë ¥í´ë¼. ì ë ë§¤ëë 100.0%, ì ë° ë§¤ëë 50.0% ë±ì¼ë¡ ê¸°ìíë¤. ê³µë§¤ëë ì ë ë¶ê°ë¥íë¤.\n"
        "5. ìì¬ ê²°ì  ì¬ì (reasoning)ë ì´ë¤ ë´ì¤ ë¶ì ì»¨íì¤í¸ë¥¼ ê·¼ê±°ë¡ ì¼ìëì§, íì¬ì ê¸°ì ì  ì§í ìí©ê³¼ ë§¤ì¹íì¬ íê¸ë¡ êµ¬ì²´ì ì´ê³  ë¼ë¦¬ì ì¼ë¡ ìì í´ë¼.\n"
        "6. í¹ì  ì¢ëª©ì 20ì¼ ì´ê²©ë(Disparity)ê° 115% ì´ìì¼ë¡ ê¸ë±í´ ê³¼ì´ êµ¬ê°ì¼ ëë ì ê· ë§¤ì(BUY)ë¥¼ ê°íê² ì°¨ë¨íê±°ë ê´ë§(HOLD) ì¡°ì¹í´ë¼.\n"
        "7. í¸ì¬ ë´ì¤ê° ë´ëë¼ë, ê±°ëë ëí ë¹ì¨ì´ 2.0ë°° ì´í(Volume Breakout ë¯¸ì¶©ì¡±)ì´ê³  ê±°ëëì´ ì¤ë¦¬ì§ ìì ìì¹ì¼ ëë ë§¤ìë¥¼ ì ê·¹ ìì í´ë¼.\n"
        "8. ë´ì¤ê° ìë íì ìí©ììë 'ê±°ëë ëí ë¹ì¨ 2.0ë°° ëí(Volume Breakout)' ì ìê¸ ì ìì ë°ë¥¸ ëª¨ë©í ë§¤ì(BUY)ë¥¼ ê³ ë ¤íê±°ë, '20ì¼ì  ì´ê²©ë(Disparity)ê° 90% ì´í'ë¡ ê·¹ëì ê³¼ë§¤ë(ëí­ ê³¼ë) êµ¬ê°ì¼ ë ê¸°ì ì  ë°ë±ì ë¸ë¦° ì ê° ë§¤ì(BUY)ë¥¼ ìíí  ì ìë¤.\n"
        f"9. ëë 30ì¼ ë´ì ëì  ììµë¥  +{target_roi}%ë¥¼ ë¬ì±í´ì¼ íë ëªíí í¬í¸í´ë¦¬ì¤ ëª©íë¥¼ ê°ì§ê³  ìë¤. íì¬ ê²½ê³¼ ì¼ì({elapsed_days}ì¼ì°¨)ì íì¬ ììµë¥ ({current_roi:.2f}%)ì ê³ ë ¤íì¬ í¬ì ì±í¥ì ëì ì¼ë¡ ì¡°ì íë¼:\n"
        "   - **ì¶ê²© ëª¨ë(Aggressive Catch-up)**: ëª©í ë§ê°ì¼ì´ ë¤ê°ì¤ëë° íì¬ ììµë¥ ì´ ëª©í íì´ì¤(+0.33%/ì¼) ëë¹ ë¯¸ë¬ ìíì¸ ê²½ì°, ì°ë ì¢ëª©ì ê¸°ì ì  ê±°ëë ëíë ê·¹ì¬í ëí­ ê³¼ë êµ¬ê°ìì ë§¤ì ë¹ì¤ì ëì¬ ì ê·¹ì ì¼ë¡ ììµì ì¶êµ¬íë¼.\n"
        "   - **ì´ìµ ë³´ì¡´ ëª¨ë(Capital Preservation)**: ì´ë¯¸ ëª©í ììµë¥ ì ì´ê³¼ ë¬ì±íê±°ë ëª©í íì´ì¤ë¥¼ ìì ì ì¼ë¡ ìííê³  ìë ê²½ì°, ìë¡ì´ ì¶ê²© ë§¤ìë¥¼ ë§¤ì° ìì íê³  ì´ìµì ì¤ííì¬ ì»ì ììµì ìì íê² ì§í¤ë ê´ë§(HOLD) ìì£¼ë¡ ì¡°ì¬ì¤ë½ê² ë°©ì´íë¼."
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
- 일별 권장 진척 속도: +0.33% / 일

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
    # We use gemini-3.5-flash or fallback
    try:
        model = genai.GenerativeModel(
            model_name="gemini-3.5-flash",
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
            # Cooldown duration: 30 minutes
            cooldown = timedelta(minutes=30)
            if time_diff < cooldown and not bypass_hours:
                print(f"[Trading Engine] Idempotency Lock: Trade within 30 minutes cooldown is blocked. Last trade was {time_diff.total_seconds() / 60:.1f} mins ago.")
                return {"status": "skipped", "message": "Idempotency Lock: Minimum 30-minute interval between trades required."}
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
        
        if is_market_shock:
            print(f"[Trading Engine] BUY Order Overridden by Market Shock: {shock_reason}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 시장 쇼크] Gemini AI가 매수를 결정했으나 종합지수가 -1.5% 이상 패닉 급락 중이므로 추가 대방어 기각 규칙이 작동하여 HOLD 처리했습니다. ({shock_reason})"
        elif disparity >= 115.0:
            print(f"[Trading Engine] BUY Order Overridden by Disparity Limit: {disparity}% >= 115.0%")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 가격 과열] Gemini AI가 매수를 결정했으나 20일선 이격도가 {disparity}%로 과열 임계치(115%)를 초과하여 상단 꼭대기 설거지 방지 기각 규칙이 작동하여 HOLD 처리했습니다."
        elif has_bad_news:
            print(f"[Trading Engine] BUY Order Overridden by Bad News Filter: {bad_news_reason}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 악재 뉴스 필터] Gemini AI가 매수를 결정했으나 {bad_news_reason} 우려로 백엔드 필터가 매수를 전면 차단하였습니다."
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
                
            if gate_reasons:
                reasoning += f" [가드레일 작동: {', '.join(gate_reasons)}]"
                
            if quantity <= 0:
                action = "HOLD"
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
