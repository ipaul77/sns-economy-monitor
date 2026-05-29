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
    Returns a dict: { ticker: { "quantity": int, "average_price": float } }
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
                "average_price": float(data.get("average_price", 0.0))
            }
        return holdings
    except Exception as e:
        print(f"[Trading Engine] [Error] Failed to fetch portfolio holdings from Firestore: {e}")
        return {}

def update_portfolio_holding_in_db(ticker: str, quantity: int, average_price: float) -> bool:
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
            holding_ref.set({
                "quantity": int(quantity),
                "average_price": float(average_price)
            })
            print(f"[Trading Engine] Updated holding for ticker {ticker}: Quantity={quantity}, AvgPrice={average_price:.1f}")
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

def get_active_tickers(portfolio: Dict[str, Any], news_context: List[Dict[str, Any]]) -> List[str]:
    """
    Dynamically constructs the stock ticker pool for the current simulation cycle:
    1. Baseline large caps: Samsung Electronics (005930) and SK Hynix (000660) are always included.
    2. Account holdings: Any stock currently owned in the portfolio is always included to allow selling.
    3. News context: Any South Korean company mentioned in the latest news context is mapped to a ticker.
    """
    # Always include baseline large-cap pillars
    active_tickers = {"005930", "000660"}
    
    # 1. Include currently owned portfolio holdings
    for ticker in portfolio.keys():
        active_tickers.add(ticker)
        
    # 2. Extract company mentions from the latest analyzed news
    for item in news_context:
        impacted_val = item.get("impacted_companies")
        if not impacted_val:
            continue
            
        try:
            # Check if it is a JSON list string: '["삼성전자", "한미반도체"]'
            companies = json.loads(impacted_val)
            if isinstance(companies, list):
                for comp in companies:
                    ticker = COMPANY_TO_TICKER.get(str(comp).strip())
                    if ticker:
                        active_tickers.add(ticker)
            else:
                ticker = COMPANY_TO_TICKER.get(str(companies).strip())
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
    quantity: int = Field(description="The integer quantity of shares to buy or sell (must be >= 0). For HOLD, this must be 0.")
    reasoning: str = Field(description="Specific, detailed investment logic in Korean justifying the decision based on provided news sentiment and price analysis.")

def generate_trading_decision(portfolio: Dict[str, Dict[str, Any]], balance: float, market_prices: Dict[str, float], news_context: List[Dict[str, Any]], api_key: Optional[str] = None) -> TradingDecision:
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
            portfolio_str += f"- 종목코드: {tick} | 보유수량: {qty}주 | 평균 매수가: {avg_price:,.0f}원 | 현재가: {current_price:,.0f}원 (손익률: {pl_rate:+.2f}%)\n"

    # Format market prices
    prices_str = "\n".join([f"- 종목코드: {tick} | 현재 체결가: {price:,.0f}원" for tick, price in market_prices.items()])

    # Format news analysis context
    news_str = ""
    if not news_context:
        news_str = "최근 24시간 동안 수집된 한국 경제 관련 신규 뉴스가 없습니다. 시장 모멘텀이 모호하므로 HOLD를 고려하세요."
    else:
        for idx, item in enumerate(news_context):
            news_str += f"[{idx+1}] 제목: {item.get('title', '')}\n"
            news_str += f"  - 감성(Sentiment): {item.get('sentiment', 'NEUTRAL')} (점수: {item.get('sentiment_score', 0.0)})\n"
            news_str += f"  - 관련성 점수: {item.get('relevance_score', 0)}/10 | 경보 레벨: {item.get('alert_level', 'LOW')}\n"
            news_str += f"  - 수혜/영향 기업: {item.get('impacted_companies', '[]')}\n"
            news_str += f"  - AI 요약 내용: {item.get('korean_summary', '')}\n\n"

    # Define system instructions (Guardrails)
    system_instruction = (
        "너는 주어진 가상 자산 범위 내에서만 자금을 운용하는 매우 보수적이고 합리적인 AI 주식 투자 에이전트야.\n"
        "너의 역할은 시장 가격 및 최신 뉴스 컨텍스트(감성 점수, 영향 수준 등)를 기반으로 최선의 매수/매도/관망(BUY/SELL/HOLD) 의사 결정을 내리는 것이다.\n\n"
        "--- 엄격한 행동 강령 (Guardrails) ---\n"
        "1. 너에게는 자산을 직접 계산하거나 체결 장부를 변경할 권한이 없다. 오직 '투자 판단 시그널'만 올바른 JSON 구조로 반환할 수 있다.\n"
        "2. 뉴스 분석이 누락되거나, 시장 왜곡이 의심되거나, 거래 대상 기업에 대한 충분한 호재/악재 정보가 없을 경우 반드시 'HOLD'를 선택해라.\n"
        "3. 매수를 할 때는 현재 보유 중인 예수금(Cash Balance) 범위 내에서만 가능한 수량(quantity)을 입력해야 해. 무리한 과다 매수는 필터링되어 거부된다.\n"
        "4. 매도를 할 때는 반드시 현재 보유 중인 주식 포트폴리오 상의 수량 이하로만 수량을 설정해야 해. 공매도는 절대 불가능하다.\n"
        "5. 의사 결정 사유(reasoning)는 어떤 뉴스 분석 컨텍스트를 근거로 삼았는지, 현재의 손익 현황과 매치하여 한글로 구체적이고 논리적으로 서술해라."
    )

    prompt = f"""
현재 시각: {get_kst_now().strftime("%Y-%m-%d %H:%M:%S")} (KST)
현재 사용 가능한 예수금(Cash): {balance:,.0f}원

[현재 보유 주식 현황 (Portfolio)]
{portfolio_str}

[거래 대상 종목 실시간 시세]
{prices_str}

[최근 24시간 실시간 경제 뉴스 분석 컨텍스트]
{news_str}

위 자산 상태, 시세 및 뉴스 분석 데이터를 정밀 분석하여 최고의 의사결정을 내리고, 지정된 JSON 스키마에 따라 응답하세요.
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
            quantity=0,
            reasoning=f"Gemini API 호출 및 스키마 검증 과정에서 예외가 발생하여 자산 안전을 위해 HOLD 처리했습니다. (에러: {str(e)})"
        )

# ---------------------------------------------------------------------------
# PHASE 3: CORE RULES ENGINE & DEFENSIVE PROGRAMMING
# ---------------------------------------------------------------------------
def run_simulation_cycle(bypass_hours: bool = False) -> Dict[str, Any]:
    """
    Executes a single end-to-end trading simulation cycle:
    1. Check and Load database state (Check for system locks).
    2. Check KST Market Hours (09:00 - 15:30) with optional test bypass.
    3. Apply Idempotency Lock (30 min minimum gap or news ID validation).
    4. Fetch target stock market prices via yfinance.
    5. Retrieve latest news context from DB.
    6. Call Gemini Agent for decision formulation.
    7. backend Order Verification (Execution Filter).
    8. Process Account Updates.
    9. Run **Accounting Assert** (strict mathematical verification or lock and sys.exit).
    10. Log transaction & Update Firestore state.
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

    # 5. Idempotency Lock Check (Duplicate News URL Check)
    if news_context:
        latest_news_url = news_context[0].get("url", "")
        # Scan last few transactions to see if we already traded based on this url
        already_processed_news = False
        for tx in get_latest_transactions(limit=5):
            snapshot = tx.get("snapshot_context", {})
            if snapshot.get("latest_news_url") == latest_news_url and tx.get("action") != "HOLD" and not bypass_hours:
                already_processed_news = True
                break
        
        if already_processed_news:
            print(f"[Trading Engine] Idempotency Lock: Already processed and acted upon the latest news URL: {latest_news_url}")
            return {"status": "skipped", "message": "Idempotency Lock: Latest news context has already been acted upon."}

    # 6. Fetch Market Prices (Monitored candidates) in parallel using ThreadPoolExecutor to prevent Gunicorn worker timeouts!
    # We dynamically compile the candidate list based on news & portfolio holdings!
    monitored_tickers = get_active_tickers(portfolio, news_context)
    market_prices = {}
    
    def fetch_price(tick):
        return tick, get_stock_price(tick)
        
    try:
        with ThreadPoolExecutor(max_workers=max(len(monitored_tickers), 1)) as executor:
            results = list(executor.map(fetch_price, monitored_tickers))
            for tick, price in results:
                if price > 0:
                    market_prices[tick] = price
    except Exception as e:
        print(f"[Trading Engine] [Warning] Parallel price fetching failed: {e}. Falling back to sequential.")
        # Fallback to sequential in case of thread pool issues
        for tick in monitored_tickers:
            price = get_stock_price(tick)
            if price > 0:
                market_prices[tick] = price

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
        news_context=news_context
    )

    action = decision.action
    ticker = decision.ticker
    quantity = decision.quantity
    reasoning = decision.reasoning
    current_price = market_prices.get(ticker, 0.0)

    # 8. Execution Filter & Order Validation
    # If ticker price is 0 (fetch failed), we must treat it as HOLD
    if action in ["BUY", "SELL"] and (current_price <= 0 or not ticker):
        print(f"[Trading Engine] Order Rejected: Price for ticker {ticker} is invalid or 0.")
        action = "HOLD"
        reasoning = f"시스템오류: 종목코드 {ticker}의 시세 조회가 불가능하여 거래를 보류하고 HOLD 처리했습니다."
        quantity = 0

    transaction_fee = 0.0
    fee_rate = 0.001  # 0.1% transaction fee / slippage allowance

    if action == "BUY":
        required_cash = quantity * current_price * (1 + fee_rate)
        if required_cash > balance:
            print(f"[Trading Engine] REJECTED_BY_BACKEND: BUY order of {quantity} shares of {ticker} requires {required_cash:,.0f} KRW but balance is only {balance:,.0f} KRW.")
            action = "HOLD"
            reasoning = f"REJECTED_BY_BACKEND: 매입 필요 자금({required_cash:,.0f}원)이 가용 예수금({balance:,.0f}원)을 초과하여 주문이 거부되었습니다."
            quantity = 0
            
    elif action == "SELL":
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
            "average_price": new_avg
        }
        
        # Save to DB
        update_portfolio_holding_in_db(ticker, new_qty, new_avg)

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
                "average_price": prev_avg  # Average buying cost stays the same upon selling
            }
            
        # Save to DB
        update_portfolio_holding_in_db(ticker, new_qty, prev_avg)

    # Calculate new total asset based on current prices
    new_portfolio_value_at_current_prices = sum(
        new_portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) 
        for t in new_portfolio
    )
    new_total_asset = new_balance + new_portfolio_value_at_current_prices

    # 10. Accounting Assert Check
    # Total Asset Equation: Total = Balance + Sum(Qty * Price)
    # The new calculated asset must match: Expected = ExpectedPrevTotalAssetAtCurrentPrices - TransactionFee
    expected_new_total_asset = expected_prev_total_asset_at_current_prices - transaction_fee
    discrepancy = abs(new_total_asset - expected_new_total_asset)

    print(f"[Trading Engine] Accounting Check: Calculated New Asset = {new_total_asset:,.2f} KRW | Expected New Asset = {expected_new_total_asset:,.2f} KRW")
    
    if discrepancy > 10.0 or new_balance < 0:
        # Trigger CRITICAL_ACCOUNTING_FAULT
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
