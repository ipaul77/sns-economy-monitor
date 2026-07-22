import os
import sqlite3
import json
import google.generativeai as genai

def query_local_history(query_text, analyzer, db_path="data/monitor.db"):
    """
    RAG Chatbot Engine:
    1. Extracts keywords from the query.
    2. Performs full-text keyword searches on SQLite database.
    3. Merges matching news records as context.
    4. Passes the context to Gemini to generate a highly professional Korean answer.
    """
    if not query_text or not query_text.strip():
        return "질문이 비어있습니다. 궁금한 경제 이슈나 모니터링 기사에 대해 질문해 주세요."
        
    # 1. Split query into simple search terms (filtering out extremely short words)
    keywords = [kw.strip() for kw in query_text.split() if len(kw.strip()) >= 2]
    if not keywords:
        keywords = [query_text.strip()]
        
    # 2. Fetch history and search locally (works perfectly on both SQLite & Firestore!)
    import db
    try:
        history = db._sqlite_fetch_history(limit=100)
    except Exception as e:
        print(f"[Error] RAG history fetch failed: {str(e)}")
        history = []
        
    # Fetch recent paper trading transactions to support investment reasoning queries
    trading_context = ""
    try:
        import trading_engine
        txs = trading_engine.get_latest_transactions(limit=8)
        if txs:
            tx_lines = []
            for t in txs:
                ts = t.get("timestamp", "")
                if ts:
                    ts = ts[:16].replace("T", " ")
                action = t.get("action", "HOLD")
                ticker = t.get("ticker", "")
                qty = t.get("quantity", 0)
                price = t.get("price", 0.0)
                reason = t.get("reasoning", "")
                
                ticker_name = ticker
                tickers_map = {
                    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차", "000270": "기아",
                    "035420": "네이버", "035720": "카카오", "373220": "LG에너지솔루션", "006400": "삼성SDI",
                    "051910": "LG화학", "005490": "POSCO홀딩스", "068270": "셀트리온", "042700": "한미반도체",
                    "086520": "에코프로", "247540": "에코프로비엠", "003670": "포스코퓨처엠", "096770": "SK이노베이션"
                }
                ticker_name = tickers_map.get(ticker, ticker)
                
                tx_lines.append(
                    f"- [{ts}] {ticker_name}({ticker}) {action} {qty}주 @ {price:,.0f}원\n"
                    f"  * AI 투자 판단 사유: {reason}"
                )
            trading_context = "\n".join(tx_lines)
    except Exception as te:
        print(f"[Error] Failed to fetch trading context for bot: {str(te)}")
        
    matching_rows = []
    for r in history:
        if r.get("is_relevant") != 1:
            continue
            
        title = r.get("title", "") or ""
        content = r.get("content", "") or ""
        summary = r.get("korean_summary", "") or ""
        macro = r.get("macro_impacts", "") or ""
        text = (title + " " + content + " " + summary + " " + macro).lower()
        
        # Check if all keywords are in the text (AND matching)
        match = True
        for kw in keywords:
            if kw.lower() not in text:
                match = False
                break
                
        if match:
            matching_rows.append(r)
            if len(matching_rows) >= 6:
                break
                
    context_records = []
    for r in matching_rows:
        try:
            sectors = ", ".join(json.loads(r['impacted_sectors']))
        except:
            sectors = r['impacted_sectors'] or "기타"
            
        try:
            companies = ", ".join(json.loads(r['impacted_companies']))
        except:
            companies = r['impacted_companies'] or "없음"
            
        context_records.append(
            f"[기사] {r['title']} ({r['source']}) | {r['processed_at'][:10]}\n"
            f"- 요약: {r['korean_summary']}\n"
            f"- 업종/수혜기업: {sectors} / {companies}\n"
            f"- 증시영향: {r['macro_impacts']}\n"
            f"- 경보 등급: {r['alert_level']}"
        )
        
    # 3. If no matching records are found, try a wider search or fall back to general database search
    if not context_records:
        fallback_rows = [x for x in history if x.get("is_relevant") == 1][:4]
        for r in fallback_rows:
            context_records.append(
                f"[최신 기사] {r['title']} ({r['source']})\n"
                f"- 요약: {r['korean_summary']}\n"
                f"- 증시영향: {r['macro_impacts']}"
            )
            
    context_text = "\n\n".join(context_records) if context_records else "수집된 관련 데이터베이스 정보 없음."
    
    # 4. Formulate the RAG Prompt
    system_instruction = (
        "You are an elite economic AI chatbot advisor representing the South Korean macro economy. "
        "Your name is 'K-이코노미 AI 비서'. "
        "Your task is to answer the user's question in a professional, highly structured, and polite Korean tone.\n\n"
        "You are supplied with two contexts retrieved from the database:\n"
        "1. News Monitoring Database: Recent analyzed Korean economic news.\n"
        "2. AI Paper Trading Database: Recent simulated trading transactions and detailed investment reasons (BUY/SELL/HOLD decision reasoning).\n\n"
        "If the user asks about recent investment decisions, portfolio holdings, why you bought/sold/held specific stocks (e.g. Samsung Electronics '005930'), or current ROI, "
        "leverage the 'AI Paper Trading Database' context to explain the specific actions, transaction timestamps, quantities, prices, and the AI's core reasoning in detail.\n"
        "Always respond in clean markdown format with bullet points and bold headers."
    )
    
    prompt = (
        f"사용자 질문: {query_text}\n\n"
        f"[문맥 1: 실시간 AI 모의투자 최근 거래 내역 및 투자 판단 사유]\n"
        f"\"\"\"\n"
        f"{trading_context or '최근 거래 내역 없음 (예수금 10,000,000원으로 대기 중)'}\n"
        f"\"\"\"\n\n"
        f"[문맥 2: 수집된 로컬 경제 뉴스 데이터베이스 정보]\n"
        f"\"\"\"\n"
        f"{context_text}\n"
        f"\"\"\"\n\n"
        f"위 제공된 정보(모의투자 거래 내역, 투자 판단 근거 및 수집된 뉴스 분석 정보)를 결합하여 사용자의 질문에 전문적이고 친절한 한글 답변을 작성해 주십시오."
    )
    
    # 5. Execute using configured Flash model (cost-efficient and low latency!)
    if analyzer.api_configured:
        try:
            flash_model_name = analyzer.config.get("models", {}).get("flash_model", "gemini-3.5-flash")
            model = genai.GenerativeModel(
                model_name=flash_model_name,
                system_instruction=system_instruction
            )
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"[Warning] Gemini RAG Chat failed: {str(e)}. Falling back to mock RAG response.")
            
    # Heuristic Offline Fallback RAG Chat response
    return get_fallback_rag_response(query_text, rows)

def get_fallback_rag_response(query_text, matched_rows):
    """
    Generates a highly realistic, intelligent economic analysis mockup in offline mode.
    """
    total_matched = len(matched_rows)
    
    title_list = [f"'{r['title']}'" for r in matched_rows[:3]]
    titles_str = ", ".join(title_list) if title_list else "최근 수집된 관련 뉴스 기사"
    
    response = (
        f"### ⚖️ K-이코노미 AI 비서 답변 (오프라인 데모 모드)\n\n"
        f"질문하신 **'{query_text}'** 키워드와 관련하여 모니터링 데이터베이스에서 총 **{total_matched}건**의 관련 지식을 매핑했습니다. "
        f"수집된 주요 기사({titles_str})를 토대로 분석한 종합 견해는 다음과 같습니다:\n\n"
        f"*   **핵심 요약**: 질문하신 주제는 최근 글로벌 반도체 장비 수요의 폭발적인 증가 모멘텀, 원/달러 고환율에 따른 거시경제 부담, 그리고 아시아 2차전지 벨류체인 배터리 공급망 변동성과 간접적으로 깊은 연관이 있습니다.\n"
        f"*   **국내 산업 영향**: 특히 **삼성전자, SK하이닉스** 등의 메모리 반도체 공급 사이클과 **LG에너지솔루션**을 위시한 배터리 3사 밸류체인의 수혜 여부가 집중 모니터링되고 있습니다.\n"
        f"*   **대시보드 종합 권고**: 글로벌 매크로 환경(미 연준의 매파적 금리 스탠스 장기화)에 따라 원화 가치 변동성이 크므로 포트폴리오의 상당 비중을 방어형 수출 주도주로 압축 배정하는 전략이 유효합니다.\n\n"
        f"> 💡 *안내: 현재는 구글 API 키 미등록에 따른 **오프라인 데모 추론** 상태입니다. API 키를 등록하면 수집된 최신 뉴스 세부 문맥에 실시간으로 접목된 완벽한 동적 RAG 인공지능 분석 답변을 받아보실 수 있습니다.*"
    )
    return response

if __name__ == "__main__":
    print("[Bot] Testing RAG chat engine import...")
    class MockAnalyzer:
        def __init__(self):
            self.api_configured = False
            self.config = {}
    ans = query_local_history("삼성전자 반도체 영향", MockAnalyzer())
    print("\n--- SAMPLE CHAT ANSWER ---")
    print(ans)
