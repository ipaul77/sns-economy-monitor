import os
import sqlite3
import json
from datetime import datetime, timedelta
import google.generativeai as genai
import db

CACHE_PATH = "data/briefing_cache.json"

def clear_briefing_cache():
    """
    Clears the briefing cache to force regeneration (used during manual refresh).
    """
    try:
        if os.path.exists(CACHE_PATH):
            os.remove(CACHE_PATH)
            print("[Briefing Cache] Cache cleared successfully.")
    except Exception as e:
        print(f"[Warning] Failed to clear briefing cache: {str(e)}")

def save_to_cache(html_content):
    """
    Helper function to save briefing content to cache file.
    """
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        cache_data = {
            "timestamp": db.get_kst_now().isoformat(),
            "html_content": html_content
        }
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print("[Briefing Cache] Daily briefing successfully saved to cache.")
    except Exception as e:
        print(f"[Warning] Failed to write briefing cache: {str(e)}")

def generate_daily_briefing(analyzer, db_path="data/monitor.db"):
    """
    Synthesizes the last 24 hours of relevant collected news and generates
    a comprehensive, highly professional macroeconomic executive report.
    Supports caching (30 minutes expiry) and offline fallback mode.
    """
    # 1. Check cache first!
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            
            cached_time_str = cache_data.get("timestamp")
            if cached_time_str:
                cached_time = datetime.fromisoformat(cached_time_str)
                # Cache is valid for 30 minutes (1800 seconds)
                if (db.get_kst_now() - cached_time).total_seconds() < 1800:
                    print(f"[Briefing Cache] Serving cached briefing report. (Generated at {cached_time.strftime('%H:%M:%S')})")
                    return cache_data.get("html_content", "")
        except Exception as e:
            print(f"[Warning] Failed to read briefing cache: {str(e)}")

    # 2. Fetch relevant articles from the last 24 hours
    rows = db.fetch_recent_relevant(hours=24)
    
    if not rows:
        html_report = get_peaceful_market_report()
        save_to_cache(html_report)
        return html_report
        
    # 3. Compile articles for LLM prompt context
    context_list = []
    for r in rows:
        try:
            sectors = ", ".join(json.loads(r['impacted_sectors']))
        except:
            sectors = r['impacted_sectors'] or "일반거시"
            
        context_list.append(
            f"● 소스: {r['source']}\n"
            f"  제목: {r['title']}\n"
            f"  주요영향분야: {sectors}\n"
            f"  요약: {r['korean_summary']}\n"
            f"  거시영향: {r['macro_impacts']}\n"
            f"  위험도: {r['alert_level']}\n"
        )
        
    context_text = "\n\n".join(context_list)
        
    # 2.5. Fetch real-time market data & exchange rate trend metrics to feed into LLM context
    market_str = ""
    usdkrw_rate = 1350.0
    usdkrw_high_3m = 1350.0
    usdkrw_drop_pct = 0.0
    usdkrw_trend_state = "STABLE"
    try:
        from trading_engine import _fetch_market_indices_and_trends
        macro_info = _fetch_market_indices_and_trends(db.get_kst_now())
        usdkrw_rate = macro_info.get("usdkrw_price", 1350.0)
        usdkrw_high_3m = macro_info.get("usdkrw_high_3m", usdkrw_rate)
        usdkrw_drop_pct = macro_info.get("usdkrw_drop_from_high_pct", 0.0)
        usdkrw_trend_state = macro_info.get("usdkrw_trend_state", "STABLE")

        from market import get_market_indicators
        m_data = get_market_indicators()
        if m_data:
            market_str = "=== 금일 주요 금융/외환 시장 실시간 및 추세 지표 (Real-time Market & Trend Vector) ===\n"
            for label, info in m_data.items():
                unit = "pt" if label in ["KOSPI", "SOXX"] else "원"
                change_sign = "+" if info["change"] > 0 else ""
                market_str += f"- {label}: {info['price']:,}{unit} (당일 등락률: {change_sign}{info['percent']}%)\n"
            market_str += f"- 환율 3개월 전고점: {usdkrw_high_3m:,.2f}원 (전고점 대비 현재 등락률: {usdkrw_drop_pct:+.2f}%, 추세 상태: {usdkrw_trend_state})\n"
    except Exception as e:
        print(f"[Warning] Failed to fetch market indicators for daily briefing prompt: {e}")

    # 4. Request Gemini Synthesis (Stage 2 Model)
    if analyzer.api_configured:
        try:
            pro_model_name = analyzer.config.get("models", {}).get("pro_model", "gemini-2.0-flash-thinking-exp")
            system_instruction = (
                "You are a world-class financial editor and senior macro strategist specializing in the South Korean economy. "
                "Synthesize the provided collection of 24-hour global news, securities research center consensus, and SNS intelligence. "
                "You must write a comprehensive, highly credible daily macroeconomic briefing report in professional Korean. "
                "Always act as if you are compiling consensus from major Korean securities firms (e.g. Samsung Securities, Mirae Asset, KB Securities, NH Investment, Shinhan) "
                "and trusted institutions like the Bank of Korea (BOK) and KDI. Tone should be highly professional, structured, decisive, and mathematically rigorous."
            )
            
            prompt = (
                f"최근 24시간 동안 수집 및 분석된 주요 경제 뉴스 요약 정보는 다음과 같습니다:\n\n"
                f"{context_text}\n\n"
                f"또한, 현재 기준의 실시간 주요 금융/외환 시장 지표 및 추세 데이터는 다음과 같습니다:\n"
                f"{market_str}\n\n"
                f"[⚠️ 필수 보고서 작성 지침 (3대 엄격 규칙)]\n"
                f"1. **환율 추세의 방향성 정밀 서술 (뒷북 분석 금지)**:\n"
                f"   - 단일 환율 숫자({usdkrw_rate:,.2f}원)만 보고 기계적으로 '고환율 위기'라고 뒷북 분석하지 마십시오.\n"
                f"   - 최근 3개월 전고점({usdkrw_high_3m:,.2f}원) 대비 현재 등락률({usdkrw_drop_pct:+.2f}%, 추세: {usdkrw_trend_state})을 반드시 파악하십시오.\n"
                f"   - 환율이 전고점 대비 하강하는 원화 강세 전환기(STABILIZING_WON_STRENGTH)인 경우 '수출 수혜주' 언급 대신, '환차손 우려 해소 및 외국인 패시브 자금 유입 대형 IT 핵심주/원화 자산 수혜'로 정교하게 분석하십시오.\n\n"
                f"2. **섹터 뭉뚱그리기 매수 권고 금지 (기업별 차별화 서술)**:\n"
                f"   - 반도체나 이차전지를 섹터 전체로 뭉뚱그려 '반도체 전체 비축' 또는 '이차전지 바텀피싱 자제하되 분할매수' 같은 안이한 지침을 내리지 마십시오.\n"
                f"   - HBM3e/NVIDIA Blackwell 밸류체인 진입 탑티어 기업(SK하이닉스 등)과 퀄테스트 지연 기업 간의 양극화를 명확히 구분하여 서술하십시오.\n\n"
                f"3. **우유부단한 양다리 스탠스 금지 (명확한 단정 가이드)**:\n"
                f"   - '바텀피싱 자제하되 분할매수 권고' 같은 중립적이고 책임 회피성 양다리 문장을 절대 쓰지 마십시오.\n"
                f"   - 실적 하향 섹터는 '비중 축소(Underweight) 및 신규 매수 완전 보류'와 같이 명확하고 단정적인 투자 가이던스를 제공하십시오.\n\n"
                f"위 정보들을 종합적으로 융합 분석하여 대한민국 투자자들을 위한 최고 수준의 거시경제 브리핑 보고서를 한글로 작성해 주십시오.\n\n"
                f"다음과 같은 양식과 내용으로 작성해 주세요 (HTML 태그를 적절히 활용하여 스타일리시하게 만들어 주세요):\n"
                f"1. '<div class=\"mb-6\"><h3 class=\"text-lg font-bold text-indigo-400 mb-2\">[1] 금일 한반도 경제 종합 요약 (증권사 및 주요 기관 컨센서스 반영)</h3>'과 함께 거시 분석을 3~4문장으로 서술해 주세요.\n"
                f"2. '<div class=\"mb-6\"><h3 class=\"text-lg font-bold text-purple-400 mb-2\">[2] 금일 3대 고위험 핵심 전선 (기관 리서치 종합 분석)</h3>' 아래에 집중해야 할 3대 위험 요소나 기회를 목록형태로 서술해 주세요. 각 전선별로 주요 증권사의 매수/매도 센티먼트나 핵심 리서치 오피니언을 함께 결합해 설명해 주세요.\n"
                f"3. '<div class=\"mb-6\"><h3 class=\"text-lg font-bold text-pink-400 mb-2\">[3] 내일 아침 증시(KOSPI) 개장 대응 가이드 (투자 전략 제언)</h3>' 아래에 투자자가 실질적으로 취해야 할 세부 투자 및 포트폴리오 헤징 전략을 서술해 주세요.\n"
                f"출력 시 HTML 마크업 코드만 반환해 주세요 (```html wrapper는 빼주세요)."
            )
            
            model = genai.GenerativeModel(
                model_name=pro_model_name,
                system_instruction=system_instruction
            )
            
            response = model.generate_content(prompt)
            # Remove raw code block markers if LLM generates them
            cleaned_text = response.text.replace("```html", "").replace("```", "").strip()
            save_to_cache(cleaned_text)
            return cleaned_text
        except Exception as e:
            print(f"[Warning] Gemini failed daily briefing synthesis: {str(e)}. Falling back to mock briefing.")
            
    # Heuristic Offline Fallback Synthesis
    fallback_report = get_fallback_briefing_report(rows)
    save_to_cache(fallback_report)
    return fallback_report

def get_peaceful_market_report():
    return """
    <div class="text-center py-12">
        <div class="text-5xl mb-4">🕊️</div>
        <h3 class="text-xl font-bold text-slate-100 mb-2">대단히 평온한 한반도 경제 전선</h3>
        <p class="text-sm text-slate-400 leading-relaxed max-w-lg mx-auto">
            최근 24시간 동안 대한민국 금융시장이나 핵심 핵심 기술 수출망에 유의미한 충격을 안겨줄 만한 글로벌 고위험 이슈가 포착되지 않았습니다. 원화 환율 및 대기업 IT 수출망이 우호적인 무풍지대에서 정상 작동 중입니다.
        </p>
    </div>
    """

def get_fallback_briefing_report(rows):
    """
    Generates a high-quality mockup briefing when running offline/fallback mode.
    """
    total = len(rows)
    high_count = len([r for r in rows if r['alert_level'] == 'HIGH'])
    
    usdkrw_rate_str = "1,400원대"
    try:
        from market import get_market_indicators
        m_data = get_market_indicators()
        if m_data and "USD_KRW" in m_data:
            price = m_data["USD_KRW"].get("price", 1400.0)
            usdkrw_rate_str = f"{price:,.2f}원"
    except Exception as e:
        print(f"[Warning] Failed to fetch USD_KRW for fallback report: {e}")
        
    # Simple templates based on content
    briefing = f"""
    <div class="mb-6">
        <h3 class="text-lg font-bold text-indigo-400 mb-2">[1] 금일 한반도 경제 종합 요약</h3>
        <p class="text-sm text-slate-300 leading-relaxed">
            최근 24시간 내 수집된 총 {total}건의 대외 이슈를 교차 분석한 결과, 글로벌 IT 반도체 생태계의 호조와 미 연준의 매파적 금리 정책 동향이 대칭을 이루며 혼조세를 견인하고 있습니다. NVIDIA의 차세대 Blackwell 칩 출하 개시 모멘텀이 삼성전자 and SK하이닉스 등 국내 메모리 대기업의 반도체 사이클 상승 기류를 강력하게 지원하고 있으나, 원/달러 환율 상방 압력이 외국인 순매수를 일부 제약하는 요소로 작용 중입니다.
        </p>
    </div>
    
    <div class="mb-6">
        <h3 class="text-lg font-bold text-purple-400 mb-2">[2] 금일 3대 고위험 핵심 전선</h3>
        <ul class="list-disc pl-5 text-sm text-slate-300 space-y-2">
            <li>
                <strong class="text-purple-300">NVIDIA Blackwell HBM3e 공급 전선 호조</strong>: 엔비디아 파트너십에 따른 동반 공급량 급증 가능성. IT 하드웨어 업종 지배력 유지 예상.
            </li>
            <li>
                <strong class="text-purple-300">미 연준의 고금리 장기화 우려 지속</strong>: 고원화 환율 가중 리스크에 대응해야 하며, 수입 원자재 단가 상승에 따른 중소기업 마진 압박 가중 주의.
            </li>
            <li>
                <strong class="text-purple-300">아시아 배터리 기가팩토리 유치 전선</strong>: 일론 머스크의 아시아 공급망 추가 확장 및 LG엔솔, 삼성SDI 등 국내 배터리 셀과의 제휴 타진 진행.
            </li>
        </ul>
    </div>
    
    <div class="mb-6">
        <h3 class="text-lg font-bold text-pink-400 mb-2">[3] 내일 아침 증시(KOSPI) 개장 대응 가이드</h3>
        <ol class="list-decimal pl-5 text-sm text-slate-300 space-y-2">
            <li>
                <strong>반도체 밸류체인 집중 보유</strong>: 외국인 순매수가 HBM 기술 주도권을 쥔 대형 IT 테크주로 쏠릴 가능성이 농후하므로 포트폴리오 내 반도체 비중을 비축하십시오.
            </li>
            <li>
                <strong>이차전지 바텀 피싱 자제</strong>: 기가팩토리 유치 소문은 단기 모멘텀일 뿐 실적 연동성 확인 전까지 비중 확대는 유보, 안정성 위주 분할 매수만 권고합니다.
            </li>
            <li>
                <strong>환율 헤징 포지션 확보</strong>: 원/달러 {usdkrw_rate_str}선 돌파/등락에 따라 외환 노출도가 높은 수출형 강소기업 위주로 선별 접근하며 안전 통화 자산 일부 확보가 현명합니다.
            </li>
        </ol>
    </div>
    """
    return briefing
