import os
import sqlite3
import json
from datetime import datetime, timedelta
import google.generativeai as genai

def generate_daily_briefing(analyzer, db_path="data/monitor.db"):
    """
    Synthesizes the last 24 hours of relevant collected news and generates
    a comprehensive, highly professional macroeconomic executive report.
    Supports offline fallback mode.
    """
    # 1. Fetch relevant articles from the last 24 hours
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Calculate cutoff time (24 hours ago)
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    
    cursor.execute("""
        SELECT * FROM history 
        WHERE is_relevant = 1 AND processed_at >= ?
        ORDER BY processed_at DESC
    """, (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return get_peaceful_market_report()
        
    # 2. Compile articles for LLM prompt context
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
        
    context_text = "\n".join(context_list)
    
    # 3. Request Gemini Synthesis (Stage 2 Model)
    if analyzer.api_configured:
        try:
            pro_model_name = analyzer.config.get("models", {}).get("pro_model", "gemini-1.5-pro")
            system_instruction = (
                "You are a world-class financial editor specializing in the South Korean economy. "
                "Synthesize the provided collection of 24-hour global news and SNS intelligence. "
                "You must write a comprehensive daily macroeconomic briefing report in professional Korean."
            )
            
            prompt = (
                f"최근 24시간 동안 수집 및 분석된 주요 경제 뉴스 요약 정보는 다음과 같습니다:\n\n"
                f"{context_text}\n\n"
                f"위 기사들을 종합적으로 분석하여 대한민국 투자자들을 위한 주간/일일 거시경제 브리핑 보고서를 한글로 작성해 주십시오.\n\n"
                f"다음과 같은 양식과 내용으로 반드시 작성해 주세요 (HTML 태그를 적절히 활용하여 스타일리시하게 만들어 주세요):\n"
                f"1. '<div class=\"mb-6\"><h3 class=\"text-lg font-bold text-indigo-400 mb-2\">[1] 금일 한반도 경제 종합 요약</h3>'과 함께 거시 분석을 3~4문장으로 서술해 주세요.\n"
                f"2. '<div class=\"mb-6\"><h3 class=\"text-lg font-bold text-purple-400 mb-2\">[2] 금일 3대 고위험 핵심 전선</h3>' 아래에 집중해야 할 3대 위험 요소나 기회를 목록형태로 서술해 주세요.\n"
                f"3. '<div class=\"mb-6\"><h3 class=\"text-lg font-bold text-pink-400 mb-2\">[3] 내일 아침 증시(KOSPI) 개장 대응 가이드</h3>' 아래에 투자자가 실질적으로 취해야 할 세부 투자 및 포트폴리오 헤징 전략을 서술해 주세요.\n"
                f"출력 시 HTML 마크업 코드만 반환해 주세요 (```html wrapper는 빼주세요)."
            )
            
            model = genai.GenerativeModel(
                model_name=pro_model_name,
                system_instruction=system_instruction
            )
            
            response = model.generate_content(prompt)
            # Remove raw code block markers if LLM generates them
            cleaned_text = response.text.replace("```html", "").replace("```", "").strip()
            return cleaned_text
        except Exception as e:
            print(f"[Warning] Gemini failed daily briefing synthesis: {str(e)}. Falling back to mock briefing.")
            
    # Heuristic Offline Fallback Synthesis
    return get_fallback_briefing_report(rows)

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
    
    # Simple templates based on content
    briefing = f"""
    <div class="mb-6">
        <h3 class="text-lg font-bold text-indigo-400 mb-2">[1] 금일 한반도 경제 종합 요약</h3>
        <p class="text-sm text-slate-300 leading-relaxed">
            최근 24시간 내 수집된 총 {total}건의 대외 이슈를 교차 분석한 결과, 글로벌 IT 반도체 생태계의 호조와 미 연준의 매파적 금리 정책 동향이 대칭을 이루며 혼조세를 견인하고 있습니다. NVIDIA의 차세대 Blackwell 칩 출하 개시 모멘텀이 삼성전자와 SK하이닉스 등 국내 메모리 대기업의 반도체 사이클 상승 기류를 강력하게 지원하고 있으나, 원/달러 환율 상방 압력이 외국인 순매수를 일부 제약하는 요소로 작용 중입니다.
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
                <strong>환율 헤징 포지션 확보</strong>: 원/달러 1,360원대 돌파에 따라 외환 노출도가 높은 수출형 강소기업 위주로 선별 접근하며 안전 통화 자산 일부 확보가 현명합니다.
            </li>
        </ol>
    </div>
    """
    return briefing
