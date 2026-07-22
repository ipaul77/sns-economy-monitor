import os
import sys

# Force standard output and standard error to use UTF-8 to prevent CP949 encoding crashes on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

import json
import time
import sqlite3
import threading
import webbrowser
from datetime import datetime
from colorama import init, Fore, Back, Style
from flask import Flask, request, jsonify

# Initialize colorama for Windows and cross-platform colored terminal logs
init(autoreset=True)

import scraper
import report_scraper
from analyzer import GeminiEconomyAnalyzer
from market import get_market_indicators
from alerts import send_telegram_alert, send_slack_alert
import db

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "monitor.db")
LOG_PATH = "log.txt"

# Initialize Flask app
app = Flask(__name__)

# Global configurations to share between Flask thread and Scraping thread
global_config = {}
global_analyzer = None

def setup_database():
    db.setup_db()
    try:
        import investor
        investor.setup_investor_db()
    except Exception as e:
        print(f"[Error] Failed to initialize investor database: {e}")

def find_similar_in_db(title, analyzer=None):
    return db.find_similar(title, analyzer)

def update_other_sources_in_db(url, new_source):
    db.update_other_sources(url, new_source)

def log_boot_status():
    """
    Logs the server boot time to Firestore system/health asynchronously.
    """
    def _async_log():
        if db.USE_FIREBASE and db.db_client is not None:
            try:
                now_str = db.get_kst_now().isoformat()
                doc_ref = db.db_client.collection("system").document("health")
                doc_ref.set({
                    "last_boot": now_str,
                    "status": "online",
                    "message": "Render Container cold-started successfully."
                }, merge=True)
                print(f"[System] Logged boot status to Firestore at {now_str}")
            except Exception as e:
                print(f"[Warning] Failed to log boot status to Firestore: {e}")
    threading.Thread(target=_async_log, daemon=True).start()

def log_trigger_status(trigger_type, status, message=""):
    """
    Logs API trigger events to Firestore asynchronously to ensure instant HTTP response times.
    """
    def _async_log():
        if db.USE_FIREBASE and db.db_client is not None:
            try:
                now_str = db.get_kst_now().isoformat()
                doc_ref = db.db_client.collection("system").document("health")
                doc_ref.set({
                    "last_trigger_time": now_str,
                    "last_trigger_type": trigger_type,
                    "last_trigger_status": status,
                    "last_trigger_message": message
                }, merge=True)
                print(f"[System] Logged trigger event to Firestore: {trigger_type} ({status})")
            except Exception as e:
                pass
    threading.Thread(target=_async_log, daemon=True).start()

def generate_html_dashboard():
    from dashboard_generator import generate_html_dashboard as gen_html
    return gen_html()

def is_already_processed(url):
    return db.is_already_processed(url)

def save_analysis_result(item, rel_check, analysis, other_sources=None, analyzer=None):
    db.save_analysis_result(item, rel_check, analysis, other_sources, analyzer)

def append_to_logfile(item, rel_check, analysis, other_sources=None):
    """
    Appends cumulative logs to log.txt with beautiful timestamp headings.
    """
    timestamp = db.get_kst_now().strftime("[%Y-%m-%d %H:%M:%S]")
    log_lines = []
    
    log_lines.append(f"{timestamp} SOURCE: {item['source']}")
    if other_sources:
        log_lines.append(f"CO-REPORTING SOURCES: {', '.join(other_sources)}")
    log_lines.append(f"TITLE: {item['title']}")
    log_lines.append(f"URL: {item['url']}")
    log_lines.append(f"ST-1 Relevance: {'YES' if rel_check.relevant else 'NO'}")
    log_lines.append(f"ST-1 Reason: {rel_check.reason}")
    
    if rel_check.relevant and analysis:
        log_lines.append(f"ST-2 Sentiment: {analysis.sentiment} (Score: {analysis.sentiment_score})")
        log_lines.append(f"ST-2 Relevance Score: {analysis.relevance_score}/10")
        log_lines.append(f"ST-2 Sectors: {', '.join(analysis.impacted_sectors)}")
        log_lines.append(f"ST-2 Companies: {', '.join(analysis.impacted_companies)}")
        log_lines.append(f"ST-2 Macro Impact: {analysis.macro_impacts}")
        log_lines.append(f"ST-2 Summary (KR): {analysis.korean_summary}")
        log_lines.append(f"ST-2 Alert Level: {analysis.alert_level}")
        
    log_lines.append("=" * 60 + "\n")
    
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
    except Exception as e:
        print(f"[Error] Failed writing to log file: {str(e)}")

def load_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        
        # Sync with Firestore persisted settings to handle Render instance resets
        firestore_cfg = db.load_system_config()
        if firestore_cfg:
            cfg.update(firestore_cfg)
            try:
                with open("config.json", "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
            except Exception as we:
                print(f"[Warning] Failed to write back firestore config to config.json: {we}")
                
        return cfg
    except Exception as e:
        print(f"[Error] Failed to load config.json: {str(e)}")
        sys.exit(1)

def run_pipeline(config, analyzer):
    from news_pipeline import run_pipeline as run_pipe
    return run_pipe(config, analyzer)

@app.route('/api/daily-feedback', methods=['GET', 'POST'])
def handle_daily_feedback():
    """
    Triggers the daily AI feedback and code improvement loop at KOSPI market close (15:40 KST).
    Gathers today's KOSPI index and disparity data, queries Firestore for today's transactions,
    sends this plus key code parts to Gemini API, and emails/telegrams the critique.
    """
    print("[Flask] Daily feedback endpoint triggered!")
    try:
        # 1. Gather Today's Transactions from Firestore
        import trading_engine
        txs = trading_engine.get_latest_transactions(limit=100)
        
        # Today's date cutoff (KST)
        now_kst = db.get_kst_now()
        cutoff_time = datetime(now_kst.year, now_kst.month, now_kst.day, 0, 0, 0)
        
        today_txs = []
        for tx in txs:
            ts_str = tx["timestamp"]
            try:
                if 'T' in ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    ts = datetime.strptime(ts_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                ts = cutoff_time
                
            if ts >= cutoff_time:
                today_txs.append(tx)
                
        # 2. Gather KOSPI / KOSDAQ Index data via yfinance
        import yfinance as yf
        kospi_close = 0.0
        kospi_disparity = 100.0
        try:
            ticker_yf = yf.Ticker("^KS11")
            df = ticker_yf.history(period="1mo")
            if not df.empty:
                kospi_close = df["Close"].iloc[-1]
                ma20 = df["Close"].rolling(20).mean().iloc[-1]
                kospi_disparity = (kospi_close / ma20) * 100
        except Exception as ex:
            print(f"[Warning] Failed to fetch live KOSPI info via yfinance: {ex}")
            
        # Format the gathered data into a clean text block
        data_summary = f"=== 당일 ({now_kst.date()}) 거래 데이터 및 지표 ===\n"
        data_summary += f"KOSPI 종가: {kospi_close:,.2f} | 20MA 이격도: {kospi_disparity:.2f}%\n"
        data_summary += f"오늘의 거래 검토 건수: {len(today_txs)}건\n\n"
        
        if not today_txs:
            data_summary += "오늘 발생한 모의투자 거래 내역이 없습니다.\n"
        else:
            for idx, tx in enumerate(today_txs):
                data_summary += f"[{idx+1}] 일시: {tx['timestamp']} | 종목: {tx['ticker']} | 주문: {tx['action']} | 수량: {tx['quantity']} | 가격: {tx['price']}\n"
                data_summary += f"    결정사유: {tx['reasoning']}\n\n"

        # 3. Read current core trading code part (Specifically the buy decision guardrails part)
        core_code = ""
        engine_path = "trading_engine.py"
        if os.path.exists(engine_path):
            try:
                with open(engine_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                # Extract key guardrail & macro circuit breaker segments from trading_engine.py
                core_code = "".join(lines[25:60]) + "\n\n# --- BUY GUARDRAILS ---\n\n" + "".join(lines[820:880])
            except Exception as e:
                core_code = f"# Failed to read trading_engine.py: {str(e)}"
        else:
            core_code = "# trading_engine.py not found locally"

        # 4. Construct Gemini API query with system instructions
        system_instruction = (
            "너는 냉철하고 엄격한 주식 투자 전문가이자 시니어 파이썬 개발자야. "
            "오늘 거래 로그에서 수수료를 낭비한 엇박자 매매(Whipsaw), 잘못된 타이밍의 물타기, 매크로 필터의 오작동을 찾아내고 비판해줘. "
            "그리고 이 문제를 해결하기 위해 어떤 변수(RSI 임계치, 이격도 기준 등)나 코드 로직을 수정해야 하는지 "
            "구체적인 파이썬 코드 수정본(diff 형태 또는 함수 재작성)을 출력해줘."
        )
        
        user_prompt = (
            f"=== 1. 오늘의 거래 데이터 및 시장 지표 ===\n{data_summary}\n"
            f"=== 2. 현재 작동 중인 핵심 매매 로직 코드 일부 ===\n```python\n{core_code}\n```\n\n"
            "위의 실제 데이터와 소스코드를 바탕으로 비판적인 투자 피드백과 소스코드 수정 제안을 작성해줘."
        )

        # Call Gemini via generator analyzer
        critique = "Critique generation failed."
        if global_analyzer.api_configured:
            try:
                import google.generativeai as genai
                model_name = global_config.get("models", {}).get("pro_model", "gemini-3.1-pro-preview")
                print(f"[Flask] Calling Gemini model '{model_name}' for daily critique...")
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_instruction
                )
                response = model.generate_content(user_prompt)
                critique = response.text
            except Exception as e:
                critique = f"Gemini API call failed: {str(e)}"
        else:
            critique = "Gemini API key is missing or invalid. Demonstration/Mock mode critique."

        # 5. Save 피드백 제안서 to Firestore (No local files, only Firestore)
        saved_to_db = False
        db_error = None
        if db.USE_FIREBASE and db.db_client is not None:
            try:
                doc_id = now_kst.date().isoformat()
                db.db_client.collection("daily_suggestions").document(doc_id).set({
                    "date": doc_id,
                    "suggestion": critique,
                    "applied": False,
                    "timestamp": now_kst.isoformat()
                })
                print(f"[Flask] 피드백 제안서 saved to Firestore: daily_suggestions/{doc_id}")
                saved_to_db = True
            except Exception as db_ex:
                db_error = str(db_ex)
                print(f"[Warning] Failed to save 피드백 제안서 to Firestore: {db_ex}")

            # Purge suggestions older than 7 days
            try:
                from datetime import timedelta
                cutoff_date = (now_kst - timedelta(days=7)).date().isoformat()
                old_docs = db.db_client.collection("daily_suggestions")\
                                      .where("date", "<", cutoff_date)\
                                      .stream()
                batch = db.db_client.batch()
                purge_count = 0
                for doc in old_docs:
                    batch.delete(doc.reference)
                    purge_count += 1
                if purge_count > 0:
                    batch.commit()
                    print(f"[Firestore Purge] Deleted {purge_count} old 피드백 제안서 (older than 7 days).")
            except Exception as purge_ex:
                print(f"[Warning] Failed to purge old 피드백 제안서 from Firestore: {purge_ex}")

        # Send Telegram notification (Short notice instead of full critique text)
        tg_token = global_config.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        tg_chat_id = global_config.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID")
        telegram_sent = False
        
        if tg_token and tg_chat_id:
            import requests
            short_msg = (
                f"📅 *[Daily AI Feedback]*\n"
                f"{now_kst.date().isoformat()} 피드백 제안서가 데이터베이스(Firestore)에 안전하게 기록되었습니다.\n\n"
                f"해당 피드백 내용을 조회하고 코드에 반영하시려면 에이전트에게 **\"오늘 피드백 제안서대로 수정 반영해줘\"**라고 요청해 주세요."
            )
            try:
                url = f"https://api.telegram.org/bot{tg_token.strip()}/sendMessage"
                requests.post(url, json={
                    "chat_id": tg_chat_id,
                    "text": short_msg,
                    "parse_mode": "Markdown"
                }, timeout=10)
                telegram_sent = True
            except Exception as ex:
                print(f"[Warning] Failed to send Telegram daily feedback notification: {ex}")

        return jsonify({
            "status": "success",
            "date": now_kst.date().isoformat(),
            "saved_to_db": saved_to_db,
            "db_error": db_error,
            "telegram_sent": telegram_sent,
            "report_preview": critique[:200] + "..."
        })
        
    except Exception as e:
        print(f"[Error] Daily feedback loop crash: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/daily-feedback/list', methods=['GET'])
def get_feedback_list():
    """
    Retrieves the last 7 daily feedback suggestions from Firestore for dashboard display.
    """
    if not db.USE_FIREBASE or db.db_client is None:
        return jsonify({"status": "error", "message": "Firebase is not configured"}), 400
    try:
        docs = db.db_client.collection("daily_suggestions")\
                           .order_by("date", direction=db.firestore.Query.DESCENDING)\
                           .limit(7)\
                           .stream()
        
        suggestions = []
        for doc in docs:
            d = doc.to_dict()
            suggestions.append({
                "date": d.get("date"),
                "suggestion": d.get("suggestion"),
                "applied": d.get("applied", False),
                "timestamp": d.get("timestamp")
            })
            
        return jsonify({
            "status": "success",
            "suggestions": suggestions
        })
    except Exception as e:
        print(f"[Error] Failed to fetch feedback list: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/ping')
def handle_ping():
    """
    Lightweight API endpoint for cron-job / ping services to wake up the server
    without fetching large HTML payload sizes.
    """
    log_trigger_status("/api/ping", "success", "Keep-alive ping received.")
    return jsonify({"status": "ok", "message": "pong"})

@app.route('/')
def serve_dashboard():
    """
    Serves the live HTML dashboard dynamically.
    """
    if os.path.exists("dashboard.html"):
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    return """
    <html>
        <body style="background-color: #0b0f19; color: #94a3b8; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
            <div style="text-align: center;">
                <h2>대시보드를 생성하고 있습니다...</h2>
                <p>초기 뉴스 수집이 1회 진행되는 동안 10~15초만 대기한 후 새로고침해 주십시오.</p>
                <script>setTimeout(() => window.location.reload(), 5000);</script>
            </div>
        </body>
    </html>
    """

@app.route('/briefing')
def serve_daily_briefing():
    """
    API endpoint: Synthesizes 24-hour relevant news and serves the executive report dynamically.
    """
    from briefing import generate_daily_briefing
    report_html = generate_daily_briefing(global_analyzer)
    return report_html

@app.route('/api/chat', methods=['POST'])
def handle_bot_chat():
    """
    API endpoint: RAG Chatbot query.
    """
    data = request.get_json() or {}
    query_text = data.get("query", "")
    from bot import query_local_history
    answer = query_local_history(query_text, global_analyzer)
    return jsonify({"answer": answer})

@app.route('/api/refresh', methods=['POST'])
def handle_manual_refresh():
    """
    API endpoint: Triggers a manual scraping and analysis cycle asynchronously.
    """
    try:
        # Clear daily briefing cache to ensure fresh report generation after manual refresh!
        from briefing import clear_briefing_cache
        clear_briefing_cache()
        
        # Clear paper trading state cache
        global _trading_state_cache
        _trading_state_cache = None
        
        # Run pipeline in a background thread to prevent Gunicorn/WSGI timeout crashes!
        t = threading.Thread(target=run_pipeline, args=(global_config, global_analyzer))
        t.start()
        return jsonify({"status": "success", "message": "Background refresh started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/count')
def handle_item_count():
    """
    API endpoint: Returns the total count of processed items to allow dynamic frontend reload triggers.
    """
    count = db.fetch_total_count()
    return jsonify({"count": count})

@app.route('/api/trade', methods=['POST', 'GET'])
def trigger_trading_simulation():
    """
    API endpoint: Triggers a single simulation cycle of the AI trading engine.
    Executed synchronously on the cloud to prevent background thread container suspension.
    """
    try:
        import trading_engine
        
        # Check bypass_hours flag (e.g. ?bypass_hours=true)
        bypass_hours = request.args.get("bypass_hours", "false").lower() == "true"
        
        # Check system lock first before executing
        state = trading_engine.get_agent_state()
        if state.get("system_lock", False):
            return jsonify({
                "status": "error",
                "message": "Trading engine is currently LOCKED due to an accounting integrity failure. System halt enforced."
            }), 423
            
        global is_trading_in_progress
        if 'is_trading_in_progress' not in globals():
            is_trading_in_progress = False
            
        if is_trading_in_progress:
            return jsonify({
                "status": "skipped",
                "message": "AI 모의투자 매매가 이미 분석 및 실행 중입니다. 잠시만 기다려주세요."
            })
            
        try:
            is_trading_in_progress = True
            print("[API] Starting synchronous trading cycle...")
            log_trigger_status("/api/trade", "started", "Simulated trading cycle requested.")
            
            # 1. Spawn news crawling asynchronously in the background to prevent 30s Render timeout.
            # It will update the database cache for subsequent trading executions.
            def run_async_crawl():
                try:
                    from briefing import clear_briefing_cache
                    clear_briefing_cache()
                    print("[API] Background trading: Crawling fresh news...")
                    run_pipeline(global_config, global_analyzer)
                    print("[API] Background trading: Crawling finished successfully.")
                except Exception as crawl_err:
                    print(f"[API] [Warning] Background crawling failed: {crawl_err}")
            
            t_crawl = threading.Thread(target=run_async_crawl, daemon=True)
            t_crawl.start()
            
            print("[API] Running trade simulation cycle directly on existing database news cache (async crawling triggered)...")
            
            # 2. Run simulation cycle on the fresh news!
            result = trading_engine.run_simulation_cycle(bypass_hours=bypass_hours)
            print("[API] Synchronous trading cycle finished successfully!")
            
            # Clear paper trading state cache to reflect transactions and updated balance immediately
            global _trading_state_cache
            _trading_state_cache = None
            
            if result.get("status") == "skipped":
                msg = result.get("message", "매매 조건이 충족되지 않아 건너뛰었습니다.")
                log_trigger_status("/api/trade", "skipped", msg)
                return jsonify({
                    "status": "skipped",
                    "message": msg
                })
                
            action = result.get("action", "HOLD")
            reasoning = result.get("reasoning", "")
            log_trigger_status("/api/trade", f"success: {action}", f"Ticker: {result.get('ticker', '')} | reasoning: {reasoning}")
            
            return jsonify({
                "status": "success",
                "message": "AI 모의투자 엔진이 성공적으로 구동되었습니다.",
                "background": False,
                "action": action,
                "ticker": result.get("ticker", ""),
                "quantity": result.get("quantity", 0),
                "price": result.get("price", 0.0),
                "reasoning": reasoning
            })
        finally:
            is_trading_in_progress = False
            
    except Exception as e:
        import traceback
        err_stack = traceback.format_exc()
        print(f"[Trading Engine] [API Error] {err_stack}")
        log_trigger_status("/api/trade", "error", f"{str(e)}\n{err_stack}")
        return jsonify({
            "status": "error",
            "message": f"Simulation cycle triggering failed: {str(e)}",
            "traceback": err_stack
        }), 500

# API State Caching Globals to prevent Firestore read limits exhaustion
_trading_state_cache = None
_trading_state_cache_time = 0
_trading_state_cache_duration = 15  # 15 seconds cache lifetime for real-time responsiveness

@app.route('/api/trading/state')
def get_trading_state():
    """
    API endpoint: Returns the current paper trading state, portfolio holdings,
    and recent transactions to populate the dashboard UI.
    
    [Optimized] 60초 동안의 서버 메모리 캐싱을 적용하여 대시보드 무한 폴링에 따른 Firestore 읽기 폭탄을 차단합니다.
    """
    global _trading_state_cache, _trading_state_cache_time
    import time
    now_time = time.time()
    
    if _trading_state_cache and (now_time - _trading_state_cache_time < _trading_state_cache_duration):
        # Cache hit! Return cached json immediately to save Firestore read limits!
        return jsonify(_trading_state_cache)
        
    try:
        import trading_engine
        state = trading_engine.get_agent_state()
        start_date_str = state.get("start_date")
        elapsed_days = 0
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str)
                if start_date.tzinfo is not None:
                    import datetime as dt_mod
                    kst_tz = dt_mod.timezone(dt_mod.timedelta(hours=9))
                    now_tz = dt_mod.datetime.now(kst_tz)
                    elapsed_days = (now_tz - start_date).days
                else:
                    now_naive = db.get_kst_now()
                    elapsed_days = (now_naive - start_date).days
            except Exception as e:
                print(f"[main.py] Failed to calculate elapsed_days: {e}")
        state["elapsed_days"] = max(0, elapsed_days)
        portfolio = trading_engine.get_portfolio_holdings()
        transactions = trading_engine.get_latest_transactions(limit=100)
        
        # HTML/JS Attribute injection safety formatting at the source
        for tx in transactions:
            reason = tx.get("reasoning", "")
            safe_reason = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;").replace("\n", " ")
            tx["reasoning_safe"] = safe_reason
            
        # Gather current stock prices to compute real-time value and ROI on front-end
        market_prices = {}
        for ticker in portfolio.keys():
            price = trading_engine.get_stock_price(ticker)
            if price > 0:
                market_prices[ticker] = price
                
        # Gather dynamic top 7 watchlist indicators
        dynamic_tickers = trading_engine.get_dynamic_top_7_stocks()
        watchlist_indicators = {}
        for tick in dynamic_tickers:
            ind = trading_engine.get_stock_indicators(tick)
            watchlist_indicators[tick] = ind
            if ind.get("current_price", 0.0) > 0 and tick not in market_prices:
                market_prices[tick] = ind["current_price"]
                
        # Calculate Leading Flow Score to return in the API response
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
        except Exception as ex:
            print(f"[main.py] Failed to calculate Leading Flow Score: {ex}")

        # Get dynamic news timeline and stats from SQLite
        news_rows = db._sqlite_fetch_history(limit=25)
        total_processed = len(news_rows)
        relevant_rows = [r for r in news_rows if r['is_relevant'] == 1]
        total_relevant = len(relevant_rows)
        high_alerts = len([r for r in relevant_rows if r['alert_level'] == 'HIGH'])
        sent_scores = [r['sentiment_score'] for r in relevant_rows if r['sentiment_score'] is not None]
        avg_sentiment = sum(sent_scores) / len(sent_scores) if sent_scores else 0.0

        # Get top market indicators
        top_market_data = {}
        try:
            top_market_data = get_market_indicators()
        except Exception as ex:
            print(f"[main.py] Failed to fetch top market indicators: {ex}")

        # Get risk profile from global config
        risk_profile = global_config.get("risk_profile", 3)

        response_data = {
            "status": "success",
            "risk_profile": risk_profile,
            "state": state,
            "portfolio": portfolio,
            "market_prices": market_prices,
            "transactions": transactions,
            "dynamic_tickers": dynamic_tickers,
            "watchlist": watchlist_indicators,
            "leading_flow_score": leading_flow_score,
            "soxx_change": soxx_change,
            "usdkrw_change": usdkrw_change,
            "news": news_rows,
            "stats": {
                "total_processed": total_processed,
                "total_relevant": total_relevant,
                "high_alerts": high_alerts,
                "avg_sentiment": avg_sentiment
            },
            "top_market_data": top_market_data
        }
        
        # Save cache
        _trading_state_cache = response_data
        _trading_state_cache_time = now_time
        
        return jsonify(response_data)
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to retrieve paper trading state: {str(e)}"
        }), 500


@app.route('/api/save-config', methods=['POST'])
def save_config():
    """
    API endpoint: Updates config parameters such as risk_profile.
    Saves to config.json and updates memory state.
    """
    global global_config, global_analyzer
    try:
        data = request.get_json() or {}
        if "risk_profile" in data:
            profile_val = int(data["risk_profile"])
            if profile_val < 1 or profile_val > 5:
                return jsonify({"status": "error", "message": "Risk profile must be between 1 and 5"}), 400
                
            # Update global config memory
            global_config["risk_profile"] = profile_val
            if global_analyzer:
                global_analyzer.config["risk_profile"] = profile_val
                
            # Save to config.json file
            if os.path.exists("config.json"):
                with open("config.json", "w", encoding="utf-8") as f:
                    json.dump(global_config, f, indent=2, ensure_ascii=False)
                    
            # Persist to Firestore settings/global_config
            try:
                db.save_system_config({"risk_profile": profile_val})
            except Exception as fe:
                print(f"[Warning] Failed to persist config to Firestore: {fe}")
                    
            print(f"[main.py] Successfully updated risk_profile to {profile_val}")
            
            # Clear API state cache to force immediate UI refresh on next poll
            global _trading_state_cache
            _trading_state_cache = None
            
            return jsonify({"status": "success", "message": "Configuration updated successfully"})
        return jsonify({"status": "error", "message": "Invalid request fields"}), 400
    except Exception as e:
        print(f"[Error] Failed to update config: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/trading/extend', methods=['POST'])
def extend_trading_period_endpoint():
    """
    API endpoint: Resets the simulated trading start date to today
    to extend the 30-day period.
    """
    try:
        import trading_engine
        # Check system lock first before executing
        state = trading_engine.get_agent_state()
        if state.get("system_lock", False):
            return jsonify({
                "status": "error",
                "message": "Trading engine is currently LOCKED. Cannot extend."
            }), 423
            
        success = trading_engine.extend_trading_period()
        if success:
            global _trading_state_cache
            _trading_state_cache = None # Clear cache to force refresh
            return jsonify({
                "status": "success",
                "message": "모의투자 기간이 성공적으로 30일 연장되었습니다."
            })
        else:
            return jsonify({
                "status": "error",
                "message": "기간 연장에 실패했습니다."
            }), 500
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"기간 연장 중 예외 발생: {str(e)}"
        }), 500


@app.route('/api/debug-import')
def debug_import_trading_engine():
    """
    Diagnostic API to dry-run import and basic logic of trading_engine on the cloud platform.
    Will never return HTTP 500, but rather structural diagnostic traceback info.
    """
    try:
        import sys
        import os
        import traceback
        
        diagnostic_info = {
            "python_version": sys.version,
            "cwd": os.getcwd(),
            "env_keys": [k for k in os.environ.keys() if "KEY" in k or "CRED" in k or "PORT" in k or "URL" in k],
            "firebase_creds_exists": "FIREBASE_CREDENTIALS" in os.environ,
            "gemini_api_key_exists": "GEMINI_API_KEY" in os.environ,
            "google_api_key_exists": "GOOGLE_API_KEY" in os.environ
        }
        
        try:
            print("[Diagnostic API] Attempting to import trading_engine...")
            if 'trading_engine' in sys.modules:
                # Reload module to enforce latest changes
                import importlib
                importlib.reload(sys.modules['trading_engine'])
            import trading_engine
            diagnostic_info["import_success"] = True
            
            # Dry run loading portfolio & state
            state = trading_engine.get_agent_state()
            portfolio = trading_engine.get_portfolio_holdings()
            diagnostic_info["db_read_success"] = True
            diagnostic_info["state_sample"] = state
            diagnostic_info["portfolio_sample"] = portfolio
            
            # List available models for their key on Render
            try:
                import google.generativeai as genai
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    with open("config.json", "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                        api_key = config_data.get("GEMINI_API_KEY")
                if api_key:
                    genai.configure(api_key=api_key.strip())
                    models = genai.list_models()
                    diagnostic_info["available_models"] = [m.name for m in models]
                else:
                    diagnostic_info["available_models_error"] = "API Key not found"
            except Exception as model_err:
                diagnostic_info["available_models_error"] = str(model_err)
        except Exception as inner_e:
            diagnostic_info["import_success"] = False
            diagnostic_info["import_error_message"] = str(inner_e)
            diagnostic_info["import_traceback"] = traceback.format_exc()
            
        return jsonify({
            "status": "diagnosed",
            "diagnostics": diagnostic_info
        })
    except Exception as outer_e:
        import traceback
        return jsonify({
            "status": "critical_diagnostic_failure",
            "error": str(outer_e),
            "traceback": traceback.format_exc()
        })


@app.route('/api/debug-run')
def debug_run_trading_engine():
    """
    Dry-runs the trading engine simulation cycle step-by-step with raw log capture
    to pinpoint exactly where the process crashes or gets blocked on the cloud.
    """
    import sys
    import io
    import traceback
    
    # Capture stdout
    old_stdout = sys.stdout
    captured_output = io.StringIO()
    sys.stdout = captured_output
    
    try:
        import trading_engine
        print("[Debug Run] Module imported successfully. Starting simulation cycle...")
        
        # We run the simulation cycle
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        
        # Restore stdout
        sys.stdout = old_stdout
        return jsonify({
            "status": "success_completed",
            "cycle_result": result,
            "logs": captured_output.getvalue()
        })
    except Exception as e:
        # Restore stdout
        sys.stdout = old_stdout
        return jsonify({
            "status": "simulation_failed",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "logs": captured_output.getvalue()
        })


# --- SCHEDULER & RUN THREAD ---

def scheduler_thread():
    """
    Background daemon thread that continuously crawls, analyzes, and saves news,
    and runs the trading simulation cycle on an interval.
    """
    interval = global_config.get("scraping_interval_seconds", 60)
    print(Fore.BLUE + f"[Scheduler] Background crawler thread active. (Interval: {interval} seconds)...")
    
    # Run once immediately on startup with a brief delay (15s) to allow Flask to return HTTP responses first
    try:
        import time
        time.sleep(15)
        run_pipeline(global_config, global_analyzer)
        try:
            import trading_engine
            print("[Scheduler] Running initial trading simulation cycle...")
            trading_engine.run_simulation_cycle(bypass_hours=False)
        except Exception as e:
            print(f"[Scheduler] [Error] Initial trading simulation failed: {str(e)}")
    except Exception as e:
        print(f"[Error] Initial startup pipeline failed: {str(e)}")
        
    while True:
        time.sleep(interval)
        try:
            run_pipeline(global_config, global_analyzer)
            try:
                import trading_engine
                print("[Scheduler] Running periodic trading simulation cycle...")
                trading_engine.run_simulation_cycle(bypass_hours=False)
            except Exception as e:
                print(f"[Scheduler] [Error] Periodic trading simulation failed: {str(e)}")
        except Exception as e:
            print(f"[Error] Periodic background pipeline failed: {str(e)}")

# Setup Database & Load Configurations at module level (WSGI / Cloud compatible)
setup_database()
try:
    log_boot_status()
except Exception as e:
    pass

global_config = load_config()
global_analyzer = GeminiEconomyAnalyzer()

# Pre-generate dashboard.html from cache on startup (Skipped heavy network call for fast cold-start)
# dashboard.html is already committed and will be refreshed dynamically by the background thread.

# --- LAZY SCHEDULER INITIALIZATION ---
scheduler_started = False
scheduler_lock = threading.Lock()

def start_scheduler_safely():
    global scheduler_started
    if scheduler_started:
        return
    with scheduler_lock:
        if not scheduler_started:
            if global_config.get("realtime_monitoring_enabled", False) and "--once" not in sys.argv:
                print("[System] Lazy Initializing background scheduler thread...")
                t = threading.Thread(target=scheduler_thread, daemon=True)
                t.start()
            scheduler_started = True

@app.before_request
def init_scheduler_on_first_request():
    start_scheduler_safely()

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit (for standard Cron triggers)")
    args = parser.parse_args()
    
    if args.once:
        print(Fore.BLUE + "\n[Mode] Running once (Cron triggered)...")
        run_pipeline(global_config, global_analyzer)
        try:
            import trading_engine
            print("[Cron] Running trading simulation cycle...")
            trading_engine.run_simulation_cycle(bypass_hours=False)
        except Exception as e:
            print(f"[Cron] [Error] Trading simulation failed: {str(e)}")
        sys.exit(0)
        
    # Check if analyzer is running in Mock/Demo mode and inform the user
    if not global_analyzer.api_configured:
        print(Back.YELLOW + Fore.BLACK + " WARNING: GEMINI_API_KEY not found in Environment or config.json. ")
        print(Fore.YELLOW + "Running in intelligent Offline Heuristic DEMO mode. Add your API key to test live Gemini reasoning.")
        
    print(Fore.GREEN + "\n=============================================")
    print(Fore.GREEN + "   SNS & NEWS ECONOMY MONITOR ACTIVE   ")
    print(Fore.GREEN + "=============================================")
    print(f"Monitoring Personalities : {', '.join(global_config.get('target_personalities', []))}")
    print(f"Monitoring Feeds         : {len(global_config.get('rss_feeds', []))} RSS targets")
    print(f"History Database         : {DB_PATH}")
    print(f"Cumulative Log File      : {LOG_PATH}")
    print(f"Web Dashboard URL        : http://localhost:5000")
    print(f"Real-time Auto Monitoring: {'ENABLED' if global_config.get('realtime_monitoring_enabled', False) else 'DISABLED (Manual Refresh Mode)'}")
    
    # 5. Automatically launch browser at http://localhost:5000 on startup
    try:
        webbrowser.open("http://localhost:5000")
        print(Fore.GREEN + "[System] Automatically opened Web Dashboard at http://localhost:5000")
    except Exception as e:
        print(f"[Warning] Failed to auto-launch browser: {str(e)}")
        
    # 6. Start Flask Web Server
    print(Fore.BLUE + "\n[System] Starting Flask Local Web Server...")
    print("Press Ctrl+C to terminate.")
    
    try:
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print(Fore.RED + "\n[System] Shutdown requested by user. Terminating process.")

if __name__ == "__main__":
    main()
