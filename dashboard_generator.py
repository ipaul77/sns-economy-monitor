import json
import os
from market import get_market_indicators
import db

def generate_html_dashboard():
    """
    Reads SQLite analysis history and generates a stunning, premium, modern HTML dashboard.
    Fetches real-time stock/exchange rate market indicators dynamically on generation!
    """
    try:
        # Read only the latest 25 items from local SQLite for zero Firestore cost
        rows = db._sqlite_fetch_history(limit=25)
    except Exception as e:
        print(f"[Error] Failed to read database for HTML generation: {str(e)}")
        return

    # Calculate basic stats
    total_processed = len(rows)
    relevant_rows = [r for r in rows if r['is_relevant'] == 1]
    total_relevant = len(relevant_rows)
    high_alerts = len([r for r in relevant_rows if r['alert_level'] == 'HIGH'])
    
    # Collect all unique sectors from relevant rows for client-side filtering
    unique_sectors = set()
    for r in relevant_rows:
        try:
            sectors = json.loads(r.get('impacted_sectors') or '[]')
            if isinstance(sectors, list):
                for s in sectors:
                    if s.strip():
                        unique_sectors.add(s.strip())
            else:
                unique_sectors.add(str(sectors).strip())
        except Exception:
            val = r.get('impacted_sectors')
            if val:
                for s in val.split(','):
                    if s.strip():
                        unique_sectors.add(s.strip())
                        
    sector_buttons_html = """
        <button onclick="filterSector('ALL')" id="filter-all" class="px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 text-white border border-indigo-500/20 transition duration-200 shadow-lg shadow-indigo-950/50 hover:scale-105 active:scale-95">
            전체보기
        </button>
    """
    for sector in sorted(list(unique_sectors)):
        safe_id = "".join([c for c in sector if c.isalnum() or c in ["-", "_"]])
        sector_buttons_html += f"""
        <button onclick="filterSector('{sector}')" id="filter-{safe_id}" class="sector-btn px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-slate-900/60 text-slate-400 border border-slate-800/80 hover:bg-slate-800/60 hover:text-slate-200 transition duration-200 hover:scale-105 active:scale-95">
            {sector}
        </button>
        """
    
    # Average sentiment
    sent_scores = [r['sentiment_score'] for r in relevant_rows if r['sentiment_score'] is not None]
    avg_sentiment = sum(sent_scores) / len(sent_scores) if sent_scores else 0.0
    
    # Classify average sentiment text
    if avg_sentiment > 0.2:
        sentiment_label = "긍정적 (Positive)"
        sentiment_class = "text-emerald-400"
    elif avg_sentiment < -0.2:
        sentiment_label = "부정적 (Negative)"
        sentiment_class = "text-rose-400"
    else:
        sentiment_label = "중립적 (Neutral)"
        sentiment_class = "text-slate-400"

    # Fetch real-time market data
    market_data = get_market_indicators()
    market_html = ""
    for label, info in market_data.items():
        change_sign = "+" if info["change"] > 0 else ""
        text_color = "text-emerald-400" if info["change"] >= 0 else "text-rose-400"
        bg_glow = "glow-green" if info["change"] >= 0 else "glow-red"
        unit = "pt" if label in ["KOSPI", "SOXX"] else "원"
        
        display_label = (
            "코스피 지수" if label == "KOSPI" 
            else ("원/달러 환율" if label == "USD_KRW" 
            else ("삼성전자" if label == "SAMSUNG" 
            else ("SK하이닉스" if label == "HYNIX" 
            else ("필라델피아 반도체 지수" if label == "SOXX" 
            else label))))
        )
        
        market_html += f"""
        <div class="glass-card rounded-2xl p-4 {bg_glow} border border-slate-800/80" id="market-card-{label}">
            <p class="text-xs font-semibold text-slate-500">{display_label} ({info['symbol']})</p>
            <div class="flex items-baseline justify-between mt-1">
                <span class="text-lg font-bold text-slate-100" id="market-price-{label}">{info['price']:,}{unit}</span>
                <span class="text-xs font-bold {text_color}" id="market-change-{label}">{change_sign}{info['change']:,} ({change_sign}{info['percent']}%)</span>
            </div>
        </div>
        """

    # HTML header & template
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>한반도 경제 모니터링 대시보드</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Outfit', 'Noto Sans KR', sans-serif;
            background-color: #0b0f19;
            background-image: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #0b0f19 70%);
        }}
        .glass-card {{
            background: rgba(17, 24, 39, 0.7);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.06);
        }}
        .glow-green {{ box-shadow: 0 0 15px rgba(16, 185, 129, 0.12); }}
        .glow-red {{ box-shadow: 0 0 15px rgba(244, 63, 94, 0.12); }}
        .glow-orange {{ box-shadow: 0 0 15px rgba(249, 115, 22, 0.12); }}
        
        /* Chatbot styling */
        .chat-container {{
            max-height: 400px;
            overflow-y: auto;
        }}
    </style>
</head>
<body class="text-slate-200 min-h-screen pb-24">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        
        <!-- Header -->
        <header class="flex flex-col md:flex-row md:items-center md:justify-between pb-6 border-b border-slate-800">
            <div>
                <h1 class="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                    한반도 경제 모니터링 실시간 대시보드
                </h1>
                <p class="mt-2 text-sm text-slate-400">
                    글로벌 저명인사 SNS 포스팅 및 실시간 비즈니스 뉴스의 대한민국 거시/미시 영향 평가 시스템
                </p>
            </div>
            <div class="mt-4 md:mt-0 flex flex-wrap items-center gap-3">
                <button onclick="openBriefing()" class="px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition duration-200 shadow-lg shadow-indigo-900/40 flex items-center">
                    📄 일일 AI 종합 브리핑 보기
                </button>
                <button onclick="openFeedbackModal()" class="px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white transition duration-200 shadow-lg shadow-amber-900/40 flex items-center">
                    💡 피드백 제안서 보기
                </button>
                <button onclick="forceRefresh()" id="refreshBtn" class="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition duration-200 flex items-center gap-1">
                    🔄 실시간 수동 갱신
                </button>
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400">
                    ● 실시간 감시 중 (Active)
                </span>
            </div>
        </header>

        <!-- Market Indicators Widget -->
        <h3 class="text-sm font-semibold text-slate-500 mt-6 mb-3">📈 실시간 금융 시장 지표 (Yahoo Finance 연동)</h3>
        <section class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {market_html}
        </section>

        <!-- Stats Grid (Compact) -->
        <section class="grid grid-cols-2 lg:grid-cols-4 gap-3 my-4">
            <div class="glass-card rounded-xl p-3 glow-orange">
                <p class="text-xs font-semibold text-slate-400">수집 및 검사 피드</p>
                <p class="mt-1 text-lg font-extrabold text-slate-100" id="stat-processed">{total_processed} 건</p>
            </div>
            <div class="glass-card rounded-xl p-3 glow-green">
                <p class="text-xs font-semibold text-slate-400">연관 기사</p>
                <p class="mt-1 text-lg font-extrabold text-emerald-400" id="stat-relevant">{total_relevant} 건</p>
            </div>
            <div class="glass-card rounded-xl p-3 glow-red">
                <p class="text-xs font-semibold text-slate-400">고위험 경보 (HIGH)</p>
                <p class="mt-1 text-lg font-extrabold text-rose-500" id="stat-high-alerts">{high_alerts} 건</p>
            </div>
            <div class="glass-card rounded-xl p-3 glow-blue">
                <p class="text-xs font-semibold text-slate-400">평균 감성 지수</p>
                <p class="mt-1 text-lg font-extrabold {sentiment_class}" id="stat-avg-sentiment">{avg_sentiment:+.2f}</p>
            </div>
        </section>

        <!-- AI Dynamic Watchlist Widget -->
        <section id="dynamicWatchlistWidget" class="mb-4">
            <h3 class="text-sm font-semibold text-slate-500 mt-6 mb-3">🔥 실시간 AI 선정 Dynamic 감시 7대 종목</h3>
            <div class="flex overflow-x-auto gap-3 pb-3 snap-x snap-mandatory scrollbar-none md:grid md:grid-cols-4 lg:grid-cols-7" id="dynamicWatchlistBody">
                <!-- Dynamic stock cards will be rendered here by JS -->
            </div>
        </section>

        <!-- AI Paper Trading Simulator Widget -->
        <section id="tradingSimulatorWidget" class="mb-8">
            <h3 class="text-sm font-semibold text-slate-500 mt-6 mb-3">🤖 AI-Driven 실시간 주식 모의투자 에이전트</h3>
            <div class="glass-card rounded-2xl p-6 border border-slate-800/80">
                <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-slate-800/80">
                    <div class="flex items-center space-x-3">
                        <span class="h-3 w-3 rounded-full bg-emerald-500 animate-pulse" id="tradingEngineStatusDot"></span>
                        <div>
                            <span class="text-base font-bold text-slate-100">AI 에이전트 모의투자 계좌 (v1.0.3-risk-patched)</span>
                            <span class="text-xs text-slate-500 ml-2">(초기 가상 자산: 10,000,000원 | 운용 30일 제한)</span>
                        </div>
                    </div>
                    <div>
                        <button onclick="triggerManualTrade()" id="tradeTriggerBtn" class="px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white shadow-lg transition duration-200 flex items-center gap-1.5">
                            ⚡ AI 모의투자 매매 1사이클 강제 구동
                        </button>
                    </div>
                </div>

                <!-- Dynamic Risk Profile Controls -->
                <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 my-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div class="flex-1">
                        <div class="flex items-center space-x-2">
                            <span class="text-xs font-bold text-slate-400">🛡️ 실시간 AI 투자 리스크 성향 제어</span>
                            <span id="riskProfileBadge" class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">중립형 (3단계)</span>
                        </div>
                        <p class="text-[11px] text-slate-500 mt-1" id="riskProfileDesc">완만한 조정장 매수를 허용하며, Half-Kelly 비중 조절(0.50배) 및 40% 예수금 의무 보존 필터를 유지합니다.</p>
                    </div>
                    <div class="w-full md:w-72 flex flex-col items-center">
                        <div class="w-full flex justify-between text-[10px] text-slate-500 mb-1 px-1 font-medium">
                            <span>극단안정</span>
                            <span>안정</span>
                            <span>중립</span>
                            <span>공격</span>
                            <span>극단공격</span>
                        </div>
                        <input type="range" id="riskProfileRange" min="1" max="5" value="3" class="w-full h-2 rounded-lg appearance-none cursor-pointer focus:outline-none bg-gradient-to-r from-emerald-500 via-amber-500 to-rose-500" style="accent-color: #f59e0b;" oninput="updateRiskProfileUI(this.value)" onchange="saveRiskProfile(this.value)">
                    </div>
                </div>

                <div class="grid grid-cols-2 lg:grid-cols-6 gap-4 my-6">
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">예수금 (Cash)</p>
                        <p class="mt-1 text-base font-extrabold text-slate-100" id="tradingCash">10,000,000원</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">보유 주식 평가금액</p>
                        <p class="mt-1 text-base font-extrabold text-slate-100" id="tradingStockValue">0원</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">총 평가 자산 (Total Asset)</p>
                        <p class="mt-1 text-base font-extrabold text-slate-100" id="tradingTotalAsset">10,000,000원</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">누적 수익률 (Total ROI)</p>
                        <p class="mt-1 text-base font-extrabold text-slate-100" id="tradingROI">+0.00%</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5 glow-orange">
                        <p class="text-xs font-semibold text-slate-500">수급선행지수 (Leading Score)</p>
                        <p class="mt-1 text-base font-extrabold text-slate-100" id="leadingFlowScore">5점 / 10점</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5 glow-orange">
                        <p class="text-xs font-semibold text-slate-500">모의투자 경과일</p>
                        <p class="mt-1 text-base font-extrabold text-slate-100" id="tradingElapsedDays">0일차 / 30일</p>
                    </div>
                </div>

                <div id="systemLockBanner" class="hidden bg-rose-950/30 border border-rose-500/20 p-4 rounded-xl flex items-center space-x-3 mb-6">
                    <svg class="h-5 w-5 text-rose-500 flex-shrink-0 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m0 0v3m0-3h3m-3 0H9m12-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <div>
                        <p class="text-xs font-bold text-rose-400">🚨 시스템 강제 잠금 상태 (Accounting Assert Safety Lock Active)</p>
                        <p class="text-[11px] text-rose-500 mt-0.5">최근 매매 실행 후 자산 무결성 검증 실패(10원 초과 오차 검출)로 오작동 방지 시스템이 작동하여 모든 에이전트 거래가 정지되었습니다.</p>
                    </div>
                </div>

                <div id="periodEndedBanner" class="hidden bg-indigo-950/40 border border-indigo-500/30 p-4 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3 mb-6 glow-orange">
                    <div class="flex items-center space-x-3">
                        <span class="text-xl">⏳</span>
                        <div>
                            <p class="text-xs font-bold text-indigo-300">⏳ 모의투자 30일 운용 기간 만료</p>
                            <p class="text-[11px] text-slate-400 mt-0.5">30일 운용 기간이 종료되었습니다. 에이전트 운용 성과 분석 및 모니터링 연장을 결정해 주세요.</p>
                        </div>
                    </div>
                    <div>
                        <button onclick="extendTradingPeriod()" class="px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg transition duration-200">
                            🔄 현재 상태로 30일 연장하기
                        </button>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-4">
                    <div>
                        <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">📊 현재 포트폴리오 (Holdings)</h4>
                        <div class="overflow-x-auto rounded-xl border border-slate-800/80 bg-slate-950/20">
                            <table class="min-w-full divide-y divide-slate-800/80 text-[11px]">
                                <thead class="bg-slate-950/50 text-slate-400">
                                    <tr>
                                        <th class="px-3 py-2 text-left font-semibold">종목명</th>
                                        <th class="px-3 py-2 text-right font-semibold">수량</th>
                                        <th class="px-3 py-2 text-right font-semibold">평단가</th>
                                        <th class="px-3 py-2 text-right font-semibold">현재가</th>
                                        <th class="px-3 py-2 text-right font-semibold">평가손익</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-slate-800/50 text-slate-300" id="holdingsTableBody">
                                    <tr>
                                        <td colspan="5" class="px-3 py-4 text-center text-slate-500">현재 보유 포트폴리오가 없습니다.</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div>
                        <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">📜 최근 AI 거래 기록 (Transactions Log)</h4>
                        <div class="overflow-x-auto rounded-xl border border-slate-800/80 bg-slate-950/20 max-h-[250px] overflow-y-auto">
                            <table class="min-w-full divide-y divide-slate-800/80 text-[11px]">
                                <thead class="bg-slate-950/50 text-slate-400 sticky top-0">
                                    <tr>
                                        <th class="px-3 py-2 text-left font-semibold">체결시간</th>
                                        <th class="px-3 py-2 text-left font-semibold">구분</th>
                                        <th class="px-3 py-2 text-left font-semibold">종목</th>
                                        <th class="px-3 py-2 text-right font-semibold">수량/가격</th>
                                        <th class="px-3 py-2 text-left font-semibold">투자 판단 근거</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-slate-800/50 text-slate-300" id="transactionsTableBody">
                                    <tr>
                                        <td colspan="5" class="px-3 py-4 text-center text-slate-500">최근 거래 기록이 없습니다.</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- List Section -->
        <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6">
            <h2 class="text-xl font-bold text-slate-100 flex items-center">
                <svg class="w-5 h-5 mr-2 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1M19 20a2 2 0 002-2V8a2 2 0 00-2-2h-5M19 20a2 2 0 002-2V8m-5 4h3m-3 4h3m-6-4h.01M9 16h.01"></path></svg>
                최신 분석 타임라인
            </h2>
            
            <!-- Sleek Search Input -->
            <div class="relative w-full lg:w-80">
                <input type="text" id="searchInput" oninput="filterTimeline()" placeholder="키워드 또는 기업명 실시간 검색..." class="w-full bg-slate-900/60 border border-slate-800/80 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 transition placeholder-slate-600" />
                <svg class="absolute left-3 top-2.5 h-4 w-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                </svg>
            </div>
        </div>

        <!-- Sector Filter Badges -->
        <div class="flex flex-wrap gap-2 mb-6" id="sectorFilters">
            {sector_buttons_html}
        </div>
        
        <div class="space-y-6" id="timelineContainer">
    """
    
    if not rows:
        html += """
            <div class="glass-card rounded-2xl p-12 text-center">
                <p class="text-slate-400">아직 수집되거나 분석된 항목이 없습니다.</p>
                <p class="text-xs text-slate-600 mt-2">프로그램을 가동하면 실시간으로 여기에 누적 분석 카드가 생성됩니다.</p>
            </div>
        """
    else:
        for r in rows:
            # Format badges
            is_rel = r['is_relevant'] == 1
            processed_at = r['processed_at'][:19].replace('T', ' ')
            published_at = r.get('published_at', '')
            if published_at:
                published_at = published_at[:19].replace('T', ' ')
            else:
                published_at = "알 수 없음"
            
            if is_rel:
                # Sentiment Badge
                sent = r['sentiment']
                sent_score = r['sentiment_score']
                if sent == 'POSITIVE':
                    sent_badge = f'<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">긍정 ({sent_score:+.1f})</span>'
                elif sent == 'NEGATIVE':
                    sent_badge = f'<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">부정 ({sent_score:+.1f})</span>'
                else:
                    sent_badge = f'<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">중립 ({sent_score:+.1f})</span>'
                
                # Alert Badge
                alert = r['alert_level']
                if alert == 'HIGH':
                    alert_badge = '<span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-600 text-white shadow-lg shadow-rose-900/40">경보: 높음 (HIGH)</span>'
                    glow_class = 'border-rose-500/30'
                elif alert == 'MEDIUM':
                    alert_badge = '<span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500 text-slate-950">경보: 중간 (MEDIUM)</span>'
                    glow_class = 'border-amber-500/30'
                else:
                    alert_badge = '<span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-700 text-slate-300">경보: 낮음 (LOW)</span>'
                    glow_class = 'border-slate-800'
                
                # Sectors and Companies
                try:
                    sectors = json.loads(r['impacted_sectors'])
                    sectors_str = ", ".join(sectors)
                except:
                    sectors_str = r['impacted_sectors'] or "기타"
                    
                try:
                    companies = json.loads(r['impacted_companies'])
                    enriched_companies = []
                    for comp in companies:
                        if comp == "삼성전자" and "SAMSUNG" in market_data:
                            s_info = market_data["SAMSUNG"]
                            sign = "+" if s_info["change"] >= 0 else ""
                            color = "text-emerald-400" if s_info["change"] >= 0 else "text-rose-400"
                            enriched_companies.append(f'<span class="font-semibold text-slate-100">{comp}</span> <span class="text-xs {color} font-medium">({s_info["price"]:,}원 {sign}{s_info["percent"]}%)</span>')
                        elif comp == "SK하이닉스" and "HYNIX" in market_data:
                            h_info = market_data["HYNIX"]
                            sign = "+" if h_info["change"] >= 0 else ""
                            color = "text-emerald-400" if h_info["change"] >= 0 else "text-rose-400"
                            enriched_companies.append(f'<span class="font-semibold text-slate-100">{comp}</span> <span class="text-xs {color} font-medium">({h_info["price"]:,}원 {sign}{h_info["percent"]}%)</span>')
                        else:
                            enriched_companies.append(f'<span class="font-semibold text-slate-300">{comp}</span>')
                    companies_str = ", ".join(enriched_companies) if enriched_companies else "없음"
                except Exception as e:
                    companies_str = r['impacted_companies'] or "없음"
                
                link_btn = f'<a href="{r["url"]}" target="_blank" class="text-xs text-indigo-400 hover:text-indigo-300 hover:underline">원본 원문보기 ↗</a>' if r['url'] else ''
                
                # Format other sources
                other_sources_html = ""
                if 'other_sources' in r.keys() and r['other_sources']:
                    try:
                        other_list = json.loads(r['other_sources'])
                        if other_list:
                            badges = "".join([f'<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800/80 text-slate-400 border border-slate-700/80 mr-1.5">{src}</span>' for src in other_list])
                            other_sources_html = f"""
                            <div class="mt-3 pt-3 border-t border-slate-800/50 flex flex-wrap items-center text-xs text-slate-500">
                                <span class="mr-2">동일 보도 매체:</span>
                                {badges}
                            </div>
                            """
                    except:
                        pass
                
                # Sectors JSON list for easy client-side parsing
                try:
                    sectors_list = json.loads(r['impacted_sectors'])
                except:
                    sectors_list = [x.strip() for x in (r['impacted_sectors'] or '').split(',') if x.strip()]
                sectors_json = json.dumps(sectors_list, ensure_ascii=False)
                
                # Combine search tokens cleanly (lowercase)
                search_text = f"{r['title']} {r['content']} {r['korean_summary']} {sectors_str} {companies_str} {r['source']}".lower().replace('"', '\\"').replace("'", "\\'")
                
                html += f"""
                <div class="timeline-card glass-card rounded-2xl p-6 border {glow_class} transition duration-300 hover:bg-slate-900/50" data-sectors='{sectors_json}' data-search-text='{search_text}'>
                    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-4 mb-4">
                        <div class="flex items-center space-x-3">
                            <span class="px-2 py-0.5 rounded text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">{r['source']}</span>
                            <span class="text-xs text-slate-400">
                                <span class="text-indigo-400 font-medium">작성:</span> {published_at}
                                <span class="mx-1 text-slate-600">|</span>
                                <span class="text-slate-500">수집:</span> {processed_at}
                            </span>
                        </div>
                        <div class="flex items-center space-x-2">
                            {sent_badge}
                            {alert_badge}
                        </div>
                    </div>
                    
                    <h3 class="text-lg font-bold text-slate-100 mb-2">{r['title']}</h3>
                    <p class="text-sm text-slate-400 line-clamp-3 mb-4">{r['content']}</p>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-950/40 p-4 rounded-xl border border-white/5 mb-4">
                        <div>
                            <p class="text-xs font-semibold text-slate-500 mb-1">영향 대상 업종 / 수혜 기업</p>
                            <p class="text-sm text-slate-200 flex flex-wrap items-center gap-1.5">
                                <span class="text-indigo-300">{sectors_str}</span>
                                <span class="text-slate-500">|</span>
                                {companies_str}
                            </p>
                        </div>
                        <div>
                            <p class="text-xs font-semibold text-slate-500 mb-1">거시지표 및 증시(KOSPI) 영향</p>
                            <p class="text-sm text-slate-200">{r['macro_impacts']}</p>
                        </div>
                    </div>
                    
                    <div class="bg-indigo-950/20 p-4 rounded-xl border border-indigo-500/10 mb-4">
                        <p class="text-xs font-semibold text-indigo-400 mb-1">AI 요약 분석 (Gemini)</p>
                        <p class="text-sm text-slate-300 leading-relaxed">{r['korean_summary']}</p>
                    </div>
                    
                    <div class="flex justify-between items-center text-xs text-slate-500">
                        <span>관련성 분류 이유: {r['relevance_reason']}</span>
                        {link_btn}
                    </div>
                    {other_sources_html}
                </div>
                """
            else:
                pass
                
    html += f"""
        </div>
    </div>

    <!-- AI Reasoning Detail Modal -->
    <div id="reasoningModal" class="fixed inset-0 z-50 hidden flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
        <div class="glass-card w-full max-w-xl rounded-3xl border border-indigo-500/20 shadow-2xl p-6 overflow-hidden flex flex-col max-h-[90vh]">
            <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                <h3 class="text-base font-bold text-slate-100 flex items-center gap-2">
                    <span id="modalStockName" class="text-indigo-400 font-extrabold"></span>
                    <span id="modalActionBadge"></span>
                    <span>상세 투자 판단 사유</span>
                </h3>
                <button onclick="closeReasoningModal()" class="text-slate-400 hover:text-slate-200 text-lg font-bold">&times;</button>
            </div>
            <div id="modalReasoningContent" class="py-6 overflow-y-auto text-sm text-slate-300 leading-relaxed whitespace-pre-wrap font-sans">
            </div>
            <div class="pt-4 border-t border-slate-800 flex justify-end">
                <button onclick="closeReasoningModal()" class="px-5 py-2.5 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-750 transition">
                    닫기
                </button>
            </div>
        </div>
    </div>

    <!-- AI Briefing Modal -->
    <div id="briefingModal" class="fixed inset-0 z-50 hidden flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
        <div class="glass-card w-full max-w-4xl rounded-3xl p-6 border border-slate-800 shadow-2xl flex flex-col max-h-[85vh]">
            <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                <h2 class="text-2xl font-bold bg-gradient-to-r from-indigo-400 to-pink-400 bg-clip-text text-transparent flex items-center">
                    📄 Gemini 일일 거시경제 브리핑 보고서
                </h2>
                <button onclick="closeBriefing()" class="text-slate-400 hover:text-slate-200 text-xl font-bold">&times;</button>
            </div>
            <div id="briefingContent" class="overflow-y-auto py-6 text-slate-300 text-sm leading-relaxed flex-1">
                <!-- Loaded dynamically -->
                <div class="flex flex-col items-center justify-center py-12">
                    <div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-400 mb-4"></div>
                    <p class="text-slate-400">Gemini AI가 실시간 브리핑을 합성 중입니다...</p>
                </div>
            </div>
            <div class="pt-4 border-t border-slate-800 flex justify-end">
                <button onclick="closeBriefing()" class="px-5 py-2.5 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition">
                    닫기
                </button>
            </div>
        </div>
    </div>

    <!-- AI Feedback Suggestions Modal -->
    <div id="feedbackModal" class="fixed inset-0 z-50 hidden flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
        <div class="glass-card w-full max-w-4xl rounded-3xl p-6 border border-slate-800 shadow-2xl flex flex-col max-h-[85vh]">
            <div class="flex items-center justify-between pb-4 border-b border-slate-800">
                <h2 class="text-2xl font-bold bg-gradient-to-r from-amber-400 to-orange-400 bg-clip-text text-transparent flex items-center gap-2">
                    💡 Gemini AI 피드백 제안서
                </h2>
                <button onclick="closeFeedbackModal()" class="text-slate-400 hover:text-slate-200 text-xl font-bold">&times;</button>
            </div>
            
            <div class="flex flex-col md:flex-row gap-4 mt-4 flex-1 overflow-hidden">
                <!-- Left Sidebar: Date List -->
                <div class="w-full md:w-52 border-b md:border-b-0 md:border-r border-slate-800 pb-4 md:pb-0 md:pr-4 flex flex-col gap-2 overflow-y-auto" id="feedbackDateList">
                    <!-- Date items loaded dynamically -->
                </div>
                
                <!-- Right Content: Suggestion Detail -->
                <div class="flex-1 flex flex-col overflow-hidden">
                    <div class="flex items-center justify-between pb-3 border-b border-slate-800/50 mb-3">
                        <span class="text-xs text-slate-400 font-bold" id="feedbackSelectedDate">날짜 선택 필요</span>
                        <span id="feedbackAppliedBadge"></span>
                    </div>
                    <div id="feedbackContent" class="overflow-y-auto text-slate-300 text-sm leading-relaxed flex-1 whitespace-pre-wrap font-mono bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        피드백 제안서를 선택해 주세요.
                    </div>
                </div>
            </div>
            
            <div class="pt-4 border-t border-slate-800 flex justify-end">
                <button onclick="closeFeedbackModal()" class="px-5 py-2.5 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition">
                    닫기
                </button>
            </div>
        </div>
    </div>

    <!-- AI Interactive Chatbot Widget (Floating bottom right) -->
    <div class="fixed bottom-6 right-6 z-40">
        <!-- Floating Chat Icon -->
        <button onclick="toggleChat()" id="chatOpenBtn" class="h-14 w-14 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white shadow-xl shadow-indigo-900/50 flex items-center justify-center border border-indigo-400/30 transition duration-300 transform hover:scale-105">
            <svg class="h-7 w-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
        </button>

        <!-- Chat window -->
        <div id="chatWindow" class="hidden glass-card w-[380px] sm:w-[420px] rounded-3xl border border-indigo-500/20 shadow-2xl flex flex-col max-h-[500px] overflow-hidden transition-all duration-300">
            <!-- Header -->
            <div class="bg-gradient-to-r from-indigo-950 to-purple-950 p-4 border-b border-indigo-500/10 flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <div class="h-2 w-2 rounded-full bg-emerald-400 animate-ping"></div>
                    <span class="font-bold text-sm text-slate-100 flex items-center">⚖️ K-이코노미 AI 비서 (RAG)</span>
                </div>
                <button onclick="toggleChat()" class="text-slate-400 hover:text-slate-200 text-lg font-bold">&times;</button>
            </div>
            
            <!-- Chat logs -->
            <div id="chatLogs" class="chat-container flex-1 p-4 space-y-3 bg-slate-950/20 text-xs">
                <div class="bg-indigo-950/20 text-slate-300 p-3 rounded-2xl border border-indigo-500/10 max-w-[85%]">
                    안녕하세요! 실시간 수집된 뉴스 데이터베이스를 완벽히 숙지하고 있는 **한반도 경제 AI 비서**입니다. 궁금하신 경제 질문이 있으신가요?
                </div>
            </div>

            <!-- Input area -->
            <div class="p-3 bg-slate-950/60 border-t border-indigo-500/10 flex items-center space-x-2">
                <input type="text" id="chatInput" onkeydown="handleChatKey(event)" placeholder="예: 최근 삼성전자 HBM 관련 뉴스 요약해줘" class="flex-1 bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500" />
                <button onclick="sendChatMessage()" class="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition">
                    전송
                </button>
            </div>
        </div>
    </div>

    <!-- Frontend Interactive Javascript -->
    <script>
        // Risk Profile Interactive UI Update Helpers
        const riskNames = {{
            1: "극단적 안정형 (1단계)",
            2: "안정형 (2단계)",
            3: "중립형 (3단계)",
            4: "공격형 (4단계)",
            5: "극단적 공격형 (5단계)"
        }};
        const riskDescriptions = {{
            1: "원금 보존 극대화. 이격도 98% 미만 시 즉시 차단, 1/4 Kelly 베팅(0.25배) 및 50% 현금 강제 보유.",
            2: "자산 보호 우선. 이격도 97% 미만 시 차단, 0.35배 Kelly 베팅 및 45% 현금 강제 보유.",
            3: "완만한 조정장 매수 허용. 이격도 95% 미만 시 차단, Half-Kelly 베팅(0.50배) 및 40% 현금 강제 보유.",
            4: "하락장 속에서도 적극적 매수. 이격도 93% 미만 시 차단, 3/4 Kelly 베팅(0.75배) 및 30% 현금 강제 보유.",
            5: "이익 극대화 풀베팅. 이격도 90% 미만 시 차단, Full Kelly 베팅(1.00배) 및 10% 현금만 보유."
        }};
        const riskColors = {{
            1: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
            2: "bg-teal-500/20 text-teal-400 border-teal-500/30",
            3: "bg-amber-500/20 text-amber-400 border-amber-500/30",
            4: "bg-orange-500/20 text-orange-400 border-orange-500/30",
            5: "bg-rose-500/20 text-rose-400 border-rose-500/30"
        }};
        
        function updateRiskProfileUI(val) {{
            const valNum = parseInt(val);
            const badge = document.getElementById("riskProfileBadge");
            const desc = document.getElementById("riskProfileDesc");
            const range = document.getElementById("riskProfileRange");
            
            if (badge) {{
                badge.textContent = riskNames[valNum];
                badge.className = "px-2 py-0.5 rounded text-[10px] font-bold border " + riskColors[valNum];
            }}
            if (desc) {{
                desc.textContent = riskDescriptions[valNum];
            }}
            if (range) {{
                const colors = {{1: "#10b981", 2: "#14b8a6", 3: "#f59e0b", 4: "#f97316", 5: "#f43f5e"}};
                range.style.accentColor = colors[valNum];
            }}
        }}
        
        function saveRiskProfile(val) {{
            const valNum = parseInt(val);
            const range = document.getElementById("riskProfileRange");
            if (range) {{
                range.dataset.userInteracting = "";
            }}
            
            console.log("Saving risk profile: ", valNum);
            fetch('/api/save-config', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ risk_profile: valNum }})
            }})
            .then(res => res.json())
            .then(data => {{
                if (data.status === "success") {{
                    console.log("Risk profile saved successfully!");
                    loadTradingState();
                }} else {{
                    alert("설정 저장 실패: " + data.message);
                }}
            }})
            .catch(err => {{
                console.error("Error saving risk profile:", err);
            }});
        }}
        
        // Track user interaction state to prevent slider jumping during dragging
        document.addEventListener("DOMContentLoaded", () => {{
            const range = document.getElementById("riskProfileRange");
            if (range) {{
                range.addEventListener("input", () => {{
                    range.dataset.userInteracting = "true";
                }});
            }}
        }});

        // AI Trading State Loader & Manual Trigger JS (Classic String Concat for Python f-string Safety)
        function loadTradingState() {{
            fetch('/api/trading/state')
            .then(res => res.json())
            .then(data => {{
                if (data.status !== "success") return;
                
                const tickersMap = {{
                    "005930": "삼성전자",
                    "000660": "SK하이닉스",
                    "005380": "현대자동차",
                    "000270": "기아",
                    "035420": "NAVER",
                    "035720": "카카오",
                    "373220": "LG에너지솔루션",
                    "006400": "삼성SDI",
                    "051910": "LG화학",
                    "005490": "POSCO홀딩스",
                    "068270": "셀트리온",
                    "042700": "한미반도체",
                    "086520": "에코프로",
                    "247540": "에코프로비엠",
                    "003670": "포스코퓨처엠",
                    "096770": "SK이노베이션",
                    "028260": "삼성물산",
                    "105560": "KB금융",
                    "055550": "신한지주",
                    "086790": "하나금융지주",
                    "207940": "삼성바이오로직스",
                    "196170": "알테오젠",
                    "028300": "HLB",
                    "011200": "HMM",
                    "003490": "대한항공",
                    "034020": "두산에너빌리티",
                    "329180": "HD현대중공업",
                    "000100": "유한양행",
                    "066970": "엘앤에프"
                }};
                
                const state = data.state;
                const portfolio = data.portfolio;
                const marketPrices = data.market_prices;
                const transactions = data.transactions;
                
                document.getElementById("tradingCash").textContent = Math.round(state.balance).toLocaleString() + "원";
                document.getElementById("tradingTotalAsset").textContent = Math.round(state.total_asset).toLocaleString() + "원";
                
                let stockVal = state.total_asset - state.balance;
                document.getElementById("tradingStockValue").textContent = Math.round(stockVal).toLocaleString() + "원";
                
                // Update Risk Profile UI
                if (data.risk_profile !== undefined) {{
                    const rangeEl = document.getElementById("riskProfileRange");
                    if (rangeEl && !rangeEl.dataset.userInteracting) {{
                        rangeEl.value = data.risk_profile;
                        updateRiskProfileUI(data.risk_profile);
                    }}
                }}
                
                // Update Leading Flow Score
                const score = data.leading_flow_score || 5;
                const soxx = data.soxx_change || 0.0;
                const usdkrw = data.usdkrw_change || 0.0;
                const scoreEl = document.getElementById("leadingFlowScore");
                if (scoreEl) {{
                    scoreEl.innerHTML = score + '점 / 10점 <span class="text-[9px] block text-slate-500 font-normal mt-0.5">SOXX: ' + (soxx >= 0 ? '+' : '') + soxx.toFixed(2) + '%, 환율: ' + (usdkrw >= 0 ? '+' : '') + usdkrw.toFixed(2) + '%</span>';
                }}

                // AI Dynamic Watchlist Rendering
                const watchlistBody = document.getElementById("dynamicWatchlistBody");
                if (watchlistBody && data.watchlist && data.dynamic_tickers) {{
                    watchlistBody.innerHTML = "";
                    data.dynamic_tickers.forEach(ticker => {{
                        const ind = data.watchlist[ticker] || {{}};
                        const price = ind.current_price || 0;
                        const disparity = ind.disparity || 100.0;
                        const volRatio = ind.volume_ratio || 1.0;
                        const frgn5d = ind.frgn_net_5d || 0;
                        const inst5d = ind.inst_net_5d || 0;
                        
                        const name = tickersMap[ticker] || ticker;
                        
                        // Determine technical status & badge
                        let badgeHtml = "";
                        let borderGlow = "border-slate-800/80";
                        if (disparity >= 115.0) {{
                            badgeHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">⚠️ 과열경계</span>';
                            borderGlow = "border-rose-500/30 glow-red";
                        }} else if (disparity <= 90.0) {{
                            badgeHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">📉 낙폭과대</span>';
                            borderGlow = "border-emerald-500/30 glow-green";
                        }} else if (ind.volume_breakout) {{
                            badgeHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">⚡ 수급돌파</span>';
                            borderGlow = "border-amber-500/30 glow-orange";
                        }} else {{
                            badgeHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-slate-800 text-slate-400 border border-slate-700">🟢 안정</span>';
                        }}
                        
                        // Determine sugeup status & badge
                        let sugeupHtml = "";
                        if (frgn5d > 0 && inst5d > 0) {{
                            sugeupHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">양매수</span>';
                        }} else if (frgn5d < 0 && inst5d < 0) {{
                            sugeupHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">동시매도</span>';
                        }} else if (frgn5d > 0) {{
                            sugeupHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">외인매수</span>';
                        }} else if (inst5d > 0) {{
                            sugeupHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20">기관매수</span>';
                        }} else {{
                            sugeupHtml = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-slate-800 text-slate-400 border border-slate-700">관망</span>';
                        }}
                        
                        const formatVol = (val) => {{
                            const absVal = Math.abs(val);
                            if (absVal >= 1000000) {{
                                return (val > 0 ? '+' : '-') + (absVal / 1000000).toFixed(1) + 'M';
                            }} else if (absVal >= 1000) {{
                                return (val > 0 ? '+' : '-') + Math.round(absVal / 1000) + 'K';
                            }}
                            return (val > 0 ? '+' : '-') + absVal;
                        }};
                        
                        const card = document.createElement("div");
                        card.className = "glass-card rounded-xl p-3 border " + borderGlow + " transition duration-200 hover:scale-[1.02] min-w-[145px] md:min-w-0 snap-center flex-shrink-0";
                        card.innerHTML = '<div class="flex justify-between items-start mb-1">' +
                                         '  <p class="text-[10px] font-semibold text-slate-400 truncate max-w-[80px]" title="' + name + '">' + name + '</p>' +
                                         '  ' + badgeHtml +
                                         '</div>' +
                                         '<p class="text-sm font-extrabold text-slate-100 font-mono">' + Math.round(price).toLocaleString() + '원</p>' +
                                         '<div class="flex justify-between items-center mt-1 text-[9px] text-slate-400 font-mono">' +
                                         '  <span>이격: ' + disparity.toFixed(1) + '%</span>' +
                                         '  <span>거래: ' + volRatio.toFixed(1) + 'x</span>' +
                                         '</div>' +
                                         '<div class="flex justify-between items-center mt-1 pt-1 border-t border-white/5 text-[9px] font-mono">' +
                                         '  <span class="' + (frgn5d >= 0 ? 'text-emerald-400' : 'text-rose-400') + '">외인: ' + formatVol(frgn5d) + '</span>' +
                                         '  <span class="' + (inst5d >= 0 ? 'text-emerald-400' : 'text-rose-400') + '">기관: ' + formatVol(inst5d) + '</span>' +
                                         '</div>' +
                                         '<div class="mt-2 text-center">' +
                                         '  ' + sugeupHtml +
                                         '</div>';
                        watchlistBody.appendChild(card);
                    }});
                }}
                
                let roi = ((state.total_asset - 10000000) / 10000000 * 100);
                const roiEl = document.getElementById("tradingROI");
                roiEl.textContent = (roi >= 0 ? "+" : "") + roi.toFixed(2) + "%";
                if (roi > 0) {{
                    roiEl.className = "mt-1 text-lg font-extrabold text-emerald-400";
                }} else if (roi < 0) {{
                    roiEl.className = "mt-1 text-lg font-extrabold text-rose-500";
                }} else {{
                    roiEl.className = "mt-1 text-lg font-extrabold text-slate-100";
                }}
                
                // Update Elapsed Days
                const elapsed = state.elapsed_days || 0;
                document.getElementById("tradingElapsedDays").textContent = elapsed + "일차 / 30일";
                
                // Toggle period ended banner
                const periodBanner = document.getElementById("periodEndedBanner");
                if (elapsed >= 30) {{
                    periodBanner.classList.remove("hidden");
                }} else {{
                    periodBanner.classList.add("hidden");
                }}

                const statusDot = document.getElementById("tradingEngineStatusDot");
                const lockBanner = document.getElementById("systemLockBanner");
                const triggerBtn = document.getElementById("tradeTriggerBtn");
                
                if (state.system_lock) {{
                    statusDot.className = "h-3 w-3 rounded-full bg-rose-500 animate-pulse";
                    lockBanner.classList.remove("hidden");
                    triggerBtn.disabled = true;
                    triggerBtn.className = "px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 text-slate-600 border border-slate-700 cursor-not-allowed";
                }} else {{
                    statusDot.className = "h-3 w-3 rounded-full bg-emerald-500 animate-ping";
                    lockBanner.classList.add("hidden");
                    triggerBtn.disabled = false;
                    triggerBtn.className = "px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white shadow-lg transition duration-200 flex items-center gap-1.5";
                }}
                
                const holdingsBody = document.getElementById("holdingsTableBody");
                holdingsBody.innerHTML = "";
                
                let holdingsCount = 0;
                for (const ticker in portfolio) {{
                    holdingsCount++;
                    const info = portfolio[ticker];
                    const currentPrice = marketPrices[ticker] || info.average_price;
                    const costVal = info.quantity * info.average_price;
                    const curVal = info.quantity * currentPrice;
                    const pl = curVal - costVal;
                    const plRate = ((currentPrice - info.average_price) / info.average_price * 100);
                    
                    const name = tickersMap[ticker] || ticker;
                    const plSign = pl >= 0 ? "+" : "";
                    const plClass = pl > 0 ? "text-emerald-400 font-semibold" : (pl < 0 ? "text-rose-400 font-semibold" : "text-slate-400");
                    
                    const row = document.createElement("tr");
                    row.className = "hover:bg-white/5 transition duration-150";
                    row.innerHTML = '<td class="px-3 py-2"><span class="text-slate-100 font-semibold">' + name + '</span> <span class="text-[9px] text-slate-500 font-mono">' + ticker + '</span></td>' +
                                    '<td class="px-3 py-2 text-right font-mono">' + info.quantity.toLocaleString() + '주</td>' +
                                    '<td class="px-3 py-2 text-right font-mono text-slate-400">' + Math.round(info.average_price).toLocaleString() + '원</td>' +
                                    '<td class="px-3 py-2 text-right font-mono text-slate-400">' + Math.round(currentPrice).toLocaleString() + '원</td>' +
                                    '<td class="px-3 py-2 text-right font-mono ' + plClass + '">' + plSign + Math.round(pl).toLocaleString() + '원 (' + plSign + plRate.toFixed(2) + '%)</td>';
                    holdingsBody.appendChild(row);
                }}
                
                if (holdingsCount === 0) {{
                    holdingsBody.innerHTML = `
                        <tr>
                            <td colspan="5" class="px-3 py-6 text-center text-slate-500">현재 보유 중인 포트폴리오 주식이 없습니다.</td>
                        </tr>
                    `;
                }}
                
                const txBody = document.getElementById("transactionsTableBody");
                txBody.innerHTML = "";
                let txCount = 0;
                transactions.forEach(tx => {{
                    txCount++;
                    const time = tx.timestamp.replace('T', ' ').substring(5, 16);
                    const name = tickersMap[tx.ticker] || tx.ticker;
                    const price = tx.price;
                    
                    let actionBadge = "";
                    if (tx.action === "BUY") {{
                        actionBadge = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">매수</span>';
                    }} else if (tx.action === "SELL") {{
                        actionBadge = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">매도</span>';
                    }} else if (tx.action === "HOLD") {{
                        actionBadge = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-slate-800 text-slate-400 border border-slate-700">관망</span>';
                    }} else {{
                        actionBadge = '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-rose-600 text-white shadow shadow-rose-900/30">' + tx.action + '</span>';
                    }}
                    
                    const row = document.createElement("tr");
                    row.className = "hover:bg-white/5 transition duration-150";
                    row.innerHTML = '<td class="px-3 py-2 font-mono text-slate-500">' + time + '</td>' +
                                    '<td class="px-3 py-2">' + actionBadge + '</td>' +
                                    '<td class="px-3 py-2 font-medium text-slate-300">' + name + ' <span class="text-[8px] text-slate-500 font-mono">' + tx.ticker + '</span></td>' +
                                    '<td class="px-3 py-2 text-right font-mono text-slate-400">' + (tx.quantity > 0 ? (tx.quantity + '주 / ' + Math.round(price).toLocaleString() + '원') : '-') + '</td>' +
                                    '<td class="px-3 py-2 text-slate-300 text-left truncate max-w-[240px] cursor-pointer hover:text-indigo-400 hover:underline" data-name="' + name + '" data-action="' + tx.action + '" data-reasoning="' + (tx.reasoning_safe || '') + '" onclick="openReasoningFromElement(this)" title="클릭하여 전체 판단 사유 보기">' + tx.reasoning + '</td>';
                    txBody.appendChild(row);
                }});
                
                if (txCount === 0) {{
                    txBody.innerHTML = `
                        <tr>
                            <td colspan="5" class="px-3 py-6 text-center text-slate-500">최근 거래 기록이 없습니다.</td>
                        </tr>
                    `;
                }}

                // Update stats dynamically
                if (data.stats) {{
                    document.getElementById("stat-processed").textContent = data.stats.total_processed + " 건";
                    document.getElementById("stat-relevant").textContent = data.stats.total_relevant + " 건";
                    document.getElementById("stat-high-alerts").textContent = data.stats.high_alerts + " 건";
                    
                    const avgSentEl = document.getElementById("stat-avg-sentiment");
                    const avgSent = data.stats.avg_sentiment;
                    avgSentEl.textContent = (avgSent >= 0 ? "+" : "") + avgSent.toFixed(2);
                    if (avgSent > 0.2) {{
                        avgSentEl.className = "mt-1 text-lg font-extrabold text-emerald-400";
                    }} else if (avgSent < -0.2) {{
                        avgSentEl.className = "mt-1 text-lg font-extrabold text-rose-400";
                    }} else {{
                        avgSentEl.className = "mt-1 text-lg font-extrabold text-slate-400";
                    }}
                }}

                // Update market indicators dynamically
                if (data.top_market_data) {{
                    for (const label in data.top_market_data) {{
                        const info = data.top_market_data[label];
                        const priceEl = document.getElementById("market-price-" + label);
                        const changeEl = document.getElementById("market-change-" + label);
                        const cardEl = document.getElementById("market-card-" + label);
                        if (priceEl && changeEl) {{
                            const unit = (label === "KOSPI" || label === "SOXX") ? "pt" : "원";
                            priceEl.textContent = info.price.toLocaleString() + unit;
                            
                            const changeSign = info.change > 0 ? "+" : "";
                            changeEl.textContent = changeSign + info.change.toLocaleString() + " (" + changeSign + info.percent + "%)";
                            
                            if (info.change >= 0) {{
                                changeEl.className = "text-xs font-bold text-emerald-400";
                                if (cardEl) {{
                                    cardEl.className = "glass-card rounded-2xl p-4 glow-green border border-slate-800/80";
                                }}
                            }} else {{
                                changeEl.className = "text-xs font-bold text-rose-400";
                                if (cardEl) {{
                                    cardEl.className = "glass-card rounded-2xl p-4 glow-red border border-slate-800/80";
                                }}
                            }}
                        }}
                    }}
                }}

                // Update latest news timeline cards dynamically
                const timelineContainer = document.getElementById("timelineContainer");
                if (timelineContainer && data.news) {{
                    // Update lastCount to keep sync
                    if (data.stats && data.stats.total_processed) {{
                        lastCount = data.stats.total_processed;
                    }}
                    
                    timelineContainer.innerHTML = "";
                    data.news.forEach(r => {{
                        const isRel = r.is_relevant === 1;
                        const processedAt = r.processed_at.replace('T', ' ').substring(0, 19);
                        const publishedAt = r.published_at ? r.published_at.replace('T', ' ').substring(0, 19) : "알 수 없음";
                        
                        let cardHtml = "";
                        let glowClass = "border-slate-800";
                        
                        if (isRel) {{
                            // Sentiment Badge
                            const sent = r.sentiment;
                            const score = r.sentiment_score || 0.0;
                            const scoreSign = score >= 0 ? "+" : "";
                            let sentBadge = "";
                            if (sent === 'POSITIVE') {{
                                sentBadge = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">긍정 (${{scoreSign}}${{score.toFixed(1)}})</span>`;
                            }} else if (sent === 'NEGATIVE') {{
                                sentBadge = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">부정 (${{scoreSign}}${{score.toFixed(1)}})</span>`;
                            }} else {{
                                sentBadge = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">중립 (${{scoreSign}}${{score.toFixed(1)}})</span>`;
                            }}
                            
                            // Alert Badge
                            const alertVal = r.alert_level;
                            let alertBadge = "";
                            if (alertVal === 'HIGH') {{
                                alertBadge = '<span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-600 text-white shadow-lg shadow-rose-900/40">경보: 높음 (HIGH)</span>';
                                glowClass = 'border-rose-500/30';
                            }} else if (alertVal === 'MEDIUM') {{
                                alertBadge = '<span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500 text-slate-950">경보: 중간 (MEDIUM)</span>';
                                glowClass = 'border-amber-500/30';
                            }} else {{
                                alertBadge = '<span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-700 text-slate-300">경보: 낮음 (LOW)</span>';
                                glowClass = 'border-slate-800';
                            }}
                            
                            // Sectors
                            let sectors = [];
                            try {{
                                sectors = typeof r.impacted_sectors === 'string' ? JSON.parse(r.impacted_sectors) : r.impacted_sectors;
                            }} catch(e) {{
                                sectors = r.impacted_sectors ? r.impacted_sectors.split(',') : ["기타"];
                            }}
                            const sectorsStr = sectors.join(", ");
                            
                            // Companies
                            let companies = [];
                            try {{
                                companies = typeof r.impacted_companies === 'string' ? JSON.parse(r.impacted_companies) : r.impacted_companies;
                            }} catch(e) {{
                                companies = r.impacted_companies ? r.impacted_companies.split(',') : [];
                            }}
                            
                            let enrichedCompanies = [];
                            companies.forEach(comp => {{
                                if (comp === "삼성전자" && data.top_market_data && data.top_market_data.SAMSUNG) {{
                                    const sInfo = data.top_market_data.SAMSUNG;
                                    const sign = sInfo.change >= 0 ? "+" : "";
                                    const color = sInfo.change >= 0 ? "text-emerald-400" : "text-rose-400";
                                    enrichedCompanies.push(`<span class="font-semibold text-slate-100">${{comp}}</span> <span class="text-xs ${{color}} font-medium">(${{sInfo.price.toLocaleString()}}원 ${{sign}}${{sInfo.percent}}%)</span>`);
                                }} else if (comp === "SK하이닉스" && data.top_market_data && data.top_market_data.HYNIX) {{
                                    const hInfo = data.top_market_data.HYNIX;
                                    const sign = hInfo.change >= 0 ? "+" : "";
                                    const color = hInfo.change >= 0 ? "text-emerald-400" : "text-rose-400";
                                    enrichedCompanies.push(`<span class="font-semibold text-slate-100">${{comp}}</span> <span class="text-xs ${{color}} font-medium">(${{hInfo.price.toLocaleString()}}원 ${{sign}}${{hInfo.percent}}%)</span>`);
                                }} else {{
                                    enrichedCompanies.push(`<span class="font-semibold text-slate-300">${{comp}}</span>`);
                                }}
                            }});
                            const companiesStr = enrichedCompanies.length > 0 ? enrichedCompanies.join(", ") : "없음";
                            
                            const linkBtn = r.url ? `<a href="${{r.url}}" target="_blank" class="text-xs text-indigo-400 hover:text-indigo-300 hover:underline">원본 원문보기 ↗</a>` : '';
                            
                            // Other sources
                            let otherSourcesHtml = "";
                            if (r.other_sources) {{
                                try {{
                                    const otherList = typeof r.other_sources === 'string' ? JSON.parse(r.other_sources) : r.other_sources;
                                    if (otherList && otherList.length > 0) {{
                                        const badges = otherList.map(src => `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800/80 text-slate-400 border border-slate-700/80 mr-1.5">${{src}}</span>`).join("");
                                        otherSourcesHtml = `
                                            <div class="mt-3 pt-3 border-t border-slate-800/50 flex flex-wrap items-center text-xs text-slate-500">
                                                <span class="mr-2">동일 보도 매체:</span>
                                                ${{badges}}
                                            </div>
                                        `;
                                    }}
                                }} catch(e) {{}}
                            }}
                            
                            // Sectors JSON list
                            const sectorsJson = JSON.stringify(sectors);
                            
                            // Combine search tokens
                            const searchText = `${{r.title}} ${{r.content}} ${{r.korean_summary}} ${{sectorsStr}} ${{companies.join(", ")}} ${{r.source}}`.toLowerCase().replace(/"/g, '\\"').replace(/'/g, "\\'");
                            
                            cardHtml = `
                                <div class="timeline-card glass-card rounded-2xl p-6 border ${{glowClass}} transition duration-300 hover:bg-slate-900/50" data-sectors='${{sectorsJson}}' data-search-text="${{searchText}}">
                                    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-4 mb-4">
                                        <div class="flex items-center space-x-3">
                                            <span class="px-2.5 py-0.5 rounded text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">${{r.source}}</span>
                                            <span class="text-xs text-slate-400">
                                                <span class="text-indigo-400 font-medium">작성:</span> ${{publishedAt}}
                                                <span class="mx-1 text-slate-600">|</span>
                                                <span class="text-slate-500">수집:</span> ${{processedAt}}
                                            </span>
                                        </div>
                                        <div class="flex items-center space-x-2">
                                            ${{sentBadge}}
                                            ${{alertBadge}}
                                        </div>
                                    </div>
                                    
                                    <h3 class="text-lg font-bold text-slate-100 mb-2">${{r.title}}</h3>
                                    <p class="text-sm text-slate-400 line-clamp-3 mb-4">${{r.content}}</p>
                                    
                                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-950/40 p-4 rounded-xl border border-white/5 mb-4">
                                        <div>
                                            <p class="text-xs font-semibold text-slate-500 mb-1">영향 대상 업종 / 수혜 기업</p>
                                            <p class="text-sm text-slate-200 flex flex-wrap items-center gap-1.5">
                                                <span class="text-indigo-300">${{sectorsStr}}</span>
                                                <span class="text-slate-500">|</span>
                                                ${{companiesStr}}
                                            </p>
                                        </div>
                                        <div>
                                            <p class="text-xs font-semibold text-slate-500 mb-1">거시지표 및 증시(KOSPI) 영향</p>
                                            <p class="text-sm text-slate-200">${{r.macro_impacts}}</p>
                                        </div>
                                    </div>
                                    
                                    <div class="bg-indigo-950/20 p-4 rounded-xl border border-indigo-500/10 mb-4">
                                        <p class="text-xs font-semibold text-indigo-400 mb-1">AI 요약 분석 (Gemini)</p>
                                        <p class="text-sm text-slate-300 leading-relaxed">${{r.korean_summary}}</p>
                                    </div>
                                    
                                    <div class="flex justify-between items-center text-xs">
                                        <span class="text-slate-500">신뢰도: ${{r.relevance_score}}/10</span>
                                        ${{linkBtn}}
                                    </div>
                                    ${{otherSourcesHtml}}
                                </div>
                            `;
                        }} else {{
                            // Non-relevant item
                            const searchText = `${{r.title}} ${{r.content}} ${{r.source}}`.toLowerCase().replace(/"/g, '\\"').replace(/'/g, "\\'");
                            cardHtml = `
                                <div class="timeline-card glass-card rounded-2xl p-6 border border-slate-800 transition duration-300 hover:bg-slate-900/50" data-sectors='["기타"]' data-search-text="${{searchText}}">
                                    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-4 mb-4">
                                        <div class="flex items-center space-x-3">
                                            <span class="px-2 py-0.5 rounded text-xs bg-slate-800 text-slate-400 border border-slate-700">${{r.source}}</span>
                                            <span class="text-xs text-slate-400">
                                                <span class="text-indigo-400 font-medium">작성:</span> ${{publishedAt}}
                                                <span class="mx-1 text-slate-600">|</span>
                                                <span class="text-slate-500">수집:</span> ${{processedAt}}
                                            </span>
                                        </div>
                                        <div>
                                            <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-500 border border-slate-700">미연관 단독 기사</span>
                                        </div>
                                    </div>
                                    
                                    <h3 class="text-lg font-bold text-slate-100 mb-2">${{r.title}}</h3>
                                    <p class="text-sm text-slate-400 line-clamp-2 mb-3">${{r.content}}</p>
                                    <div class="flex justify-between items-center text-xs">
                                        <span class="text-slate-600">${{r.relevance_reason || '한국 경제 연관 키워드 미검출로 필터링됨'}}</span>
                                        ${{r.url ? `<a href="${{r.url}}" target="_blank" class="text-xs text-slate-500 hover:text-slate-400 hover:underline">원본보기 ↗</a>` : ''}}
                                    </div>
                                </div>
                            `;
                        }}
                        
                        const wrapper = document.createElement("div");
                        wrapper.innerHTML = cardHtml;
                        timelineContainer.appendChild(wrapper.firstElementChild);
                    }});
                    
                    // Re-apply filters
                    filterTimeline();
                }}
            }})
            .catch(err => {{
                console.error("Failed to load trading state:", err);
            }});
        }}
        
        function triggerManualTrade() {{
            const btn = document.getElementById("tradeTriggerBtn");
            btn.disabled = true;
            btn.innerHTML = `
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                AI 분석 및 매매 주문 체결 중...
            `;
            
            fetch('/api/trade?bypass_hours=true', {{ method: 'POST' }})
            .then(async res => {{
                const text = await res.text();
                try {{
                    const parsed = JSON.parse(text);
                    parsed._ok = res.ok;
                    return parsed;
                }} catch(e) {{
                    throw new Error("HTTP " + res.status + " | " + text.substring(0, 300));
                }}
            }})
            .then(data => {{
                if (data._ok && data.status === "success") {{
                    if (data.background) {{
                        alert("[AI 구동 시작] " + data.message);
                    }} else {{
                        alert("[매매 체결] 구분: " + data.action + ", 종목코드: " + data.ticker + ", 수량: " + data.quantity + "주, 단가: " + Math.round(data.price).toLocaleString() + "원\\n\\n[이유] " + data.reasoning);
                    }}
                }} else if (data._ok && data.status === "skipped") {{
                    alert("[매매 관망/건너뜀] 사유: " + data.message);
                }} else {{
                    const msg = data.message || "알 수 없는 백엔드 실패";
                    const trace = data.traceback ? "\\n\\n[상세 오류]\\n" + data.traceback : "";
                    alert("[매매 실패] 사유: " + msg + trace);
                }}
                btn.disabled = false;
                btn.innerHTML = `⚡ AI 모의투자 매매 1사이클 강제 구동`;
                loadTradingState();
            }})
            .catch(err => {{
                alert("매매 거래 수행 도중 백엔드 오류가 발생했습니다.\\n\\n[에러 내역]\\n" + err.message);
                btn.disabled = false;
                btn.innerHTML = `⚡ AI 모의투자 매매 1사이클 강제 구동`;
                loadTradingState();
            }});
        }}
        
        function extendTradingPeriod() {{
            if (!confirm("현재 잔고 및 포트폴리오를 유지한 상태에서 모의투자 시작일을 오늘로 리셋하여 30일을 추가 연장하시겠습니까?")) return;
            
            fetch('/api/trading/extend', {{ method: 'POST' }})
            .then(res => res.json())
            .then(data => {{
                if (data.status === "success") {{
                    alert(data.message);
                    loadTradingState();
                }} else {{
                    alert("오류: " + data.message);
                }}
            }})
            .catch(err => {{
                alert("기간 연장 중 오류가 발생했습니다: " + err.message);
            }});
        }}
        
        // Add automatic initialization
        document.addEventListener("DOMContentLoaded", () => {{
            loadTradingState();
            setInterval(loadTradingState, 15000);
        }});

        // Toggle chatbot window
        function toggleChat() {{
            const window = document.getElementById("chatWindow");
            const btn = document.getElementById("chatOpenBtn");
            if (window.classList.contains("hidden")) {{
                window.classList.remove("hidden");
                btn.classList.add("hidden");
                document.getElementById("chatInput").focus();
            }} else {{
                window.classList.add("hidden");
                btn.classList.remove("hidden");
            }}
        }}

        // Send Chat Message to Flask backend /api/chat
        function sendChatMessage() {{
            const input = document.getElementById("chatInput");
            const query = input.value.trim ? input.value.trim() : input.value;
            if (!query) return;
            
            input.value = "";
            
            // Append User message bubble
            const logs = document.getElementById("chatLogs");
            const userBubble = document.createElement("div");
            userBubble.className = "bg-slate-800 text-slate-200 p-3 rounded-2xl max-w-[85%] ml-auto text-right";
            userBubble.textContent = query;
            logs.appendChild(userBubble);
            logs.scrollTop = logs.scrollHeight;
            
            // Append Typing indicator bubble
            const typingBubble = document.createElement("div");
            typingBubble.id = "typingIndicator";
            typingBubble.className = "bg-indigo-950/10 text-slate-400 p-3 rounded-2xl border border-indigo-500/5 max-w-[85%] flex items-center space-x-1";
            typingBubble.innerHTML = `
                <div class="h-1.5 w-1.5 bg-slate-400 rounded-full animate-bounce"></div>
                <div class="h-1.5 w-1.5 bg-slate-400 rounded-full animate-bounce delay-100"></div>
                <div class="h-1.5 w-1.5 bg-slate-400 rounded-full animate-bounce delay-200"></div>
            `;
            logs.appendChild(typingBubble);
            logs.scrollTop = logs.scrollHeight;
            
            // Fetch answer from backend RAG API
            fetch('/api/chat', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ query: query }})
            }})
            .then(res => res.json())
            .then(data => {{
                // Remove typing bubble
                document.getElementById("typingIndicator").remove();
                
                // Append AI message bubble
                const aiBubble = document.createElement("div");
                aiBubble.className = "bg-indigo-950/20 text-slate-300 p-3 rounded-2xl border border-indigo-500/10 max-w-[85%] leading-relaxed";
                
                let text = data.answer;
                text = text.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                text = text.replace(/\\*(.*?)\\n/g, '• $1<br>');
                text = text.replace(/\\n/g, '<br>');
                
                aiBubble.innerHTML = text;
                logs.appendChild(aiBubble);
                logs.scrollTop = logs.scrollHeight;
            }})
            .catch(err => {{
                document.getElementById("typingIndicator").remove();
                const errBubble = document.createElement("div");
                errBubble.className = "bg-rose-950/20 text-rose-300 p-3 rounded-2xl border border-rose-500/10 max-w-[85%]";
                errBubble.textContent = "에러: 답변을 불러오는 과정에 실패했습니다.";
                logs.appendChild(errBubble);
                logs.scrollTop = logs.scrollHeight;
            }});
        }}

        function handleChatKey(e) {{
            if (e.key === "Enter") {{
                sendChatMessage();
            }}
        }}

        // Open/Close AI Reasoning Modal
        function showReasoningModal(name, action, reasoning) {{
            document.getElementById("modalStockName").textContent = name;
            
            const badgeEl = document.getElementById("modalActionBadge");
            if (action === "BUY") {{
                badgeEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
                badgeEl.textContent = "매수";
            }} else if (action === "SELL") {{
                badgeEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20";
                badgeEl.textContent = "매도";
            }} else if (action === "HOLD") {{
                badgeEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-400 border border-slate-700";
                badgeEl.textContent = "관망";
            }} else {{
                badgeEl.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-rose-600 text-white shadow shadow-rose-900/30";
                badgeEl.textContent = action;
            }}
            
            document.getElementById("modalReasoningContent").textContent = reasoning;
            document.getElementById("reasoningModal").classList.remove("hidden");
        }}

        // Force Pipeline Refresh manually via frontend API
        var lastCount = {total_processed};
        
        function closeReasoningModal() {{
            document.getElementById("reasoningModal").classList.add("hidden");
        }}

        function openReasoningFromElement(el) {{
            const name = el.getAttribute("data-name");
            const action = el.getAttribute("data-action");
            const reasoning = el.getAttribute("data-reasoning");
            showReasoningModal(name, action, reasoning);
        }}

        // Open/Close AI Briefing Modal
        function openBriefing() {{
            const modal = document.getElementById("briefingModal");
            modal.classList.remove("hidden");
            
            const content = document.getElementById("briefingContent");
            // Show loading spinner
            content.innerHTML = `
                <div class="flex flex-col items-center justify-center py-12">
                    <div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-400 mb-4"></div>
                    <p class="text-slate-400">Gemini AI가 실시간 브리핑 보고서를 작성 중입니다...</p>
                </div>
            `;
            
            // Fetch briefing HTML
            fetch('/briefing')
            .then(res => res.text())
            .then(html => {{
                content.innerHTML = html;
            }})
            .catch(err => {{
                content.innerHTML = `
                    <div class="text-center py-12 text-rose-400">
                        에러: 실시간 브리핑 합성 과정에 실패했습니다.
                    </div>
                `;
            }});
        }}

        function closeBriefing() {{
            document.getElementById("briefingModal").classList.add("hidden");
        }}

        // Force Pipeline Refresh manually via frontend API
        function forceRefresh() {{
            const btn = document.getElementById("refreshBtn");
            btn.disabled = true;
            btn.innerHTML = `
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-slate-300" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                수집 및 분석 중...
            `;
            
            fetch('/api/refresh', {{ method: 'POST' }})
            .then(res => res.json())
            .then(data => {{
                // Check every 2s for count increase, then load trading state dynamically
                let checkAttempts = 0;
                const checkInterval = setInterval(() => {{
                    fetch('/api/count')
                    .then(res => res.json())
                    .then(countData => {{
                        checkAttempts++;
                        if (countData.count > lastCount || checkAttempts > 15) {{
                            clearInterval(checkInterval);
                            loadTradingState();
                            btn.disabled = false;
                            btn.innerHTML = "🔄 실시간 수동 갱신";
                        }}
                    }});
                }}, 2000);
            }})
            .catch(err => {{
                alert("수동 갱신 오류가 발생했습니다.");
                btn.disabled = false;
                btn.innerHTML = "🔄 실시간 수동 갱신";
            }});
        }}
        
        let feedbackList = [];
        
        function openFeedbackModal() {{
            const modal = document.getElementById("feedbackModal");
            modal.classList.remove("hidden");
            
            const dateListEl = document.getElementById("feedbackDateList");
            dateListEl.innerHTML = `
                <div class="text-xs text-slate-500 py-4 text-center">불러오는 중...</div>
            `;
            
            fetch('/api/daily-feedback/list')
            .then(res => res.json())
            .then(data => {{
                if (data.status !== "success") {{
                    dateListEl.innerHTML = `<div class="text-xs text-rose-400 py-4 text-center">오류: ${{data.message}}</div>`;
                    return;
                }}
                
                feedbackList = data.suggestions || [];
                if (feedbackList.length === 0) {{
                    dateListEl.innerHTML = `<div class="text-xs text-slate-500 py-4 text-center">저장된 제안서 없음</div>`;
                    document.getElementById("feedbackContent").textContent = "최근 7일 동안 기록된 피드백 제안서가 없습니다.";
                    document.getElementById("feedbackSelectedDate").textContent = "";
                    document.getElementById("feedbackAppliedBadge").innerHTML = "";
                    return;
                }}
                
                renderFeedbackDates();
                // Select the first one by default
                selectFeedback(0);
            }})
            .catch(err => {{
                dateListEl.innerHTML = `<div class="text-xs text-rose-400 py-4 text-center">오류가 발생했습니다.</div>`;
            }});
        }}
        
        function renderFeedbackDates() {{
            const dateListEl = document.getElementById("feedbackDateList");
            dateListEl.innerHTML = "";
            
            feedbackList.forEach((item, idx) => {{
                const btn = document.createElement("button");
                btn.onclick = () => selectFeedback(idx);
                btn.id = "feedback-date-btn-" + idx;
                
                const appliedIcon = item.applied ? "🟢 반영됨" : "🔴 미반영";
                const isAppliedClass = item.applied ? "text-emerald-400" : "text-amber-500";
                
                btn.className = "w-full text-left px-3 py-2.5 rounded-xl text-xs font-semibold bg-slate-900/60 text-slate-400 border border-slate-800/80 hover:bg-slate-800/60 hover:text-slate-200 transition flex flex-col gap-1";
                btn.innerHTML = `
                    <span class="text-slate-200">${{item.date}}</span>
                    <span class="text-[10px] ${{isAppliedClass}}">${{appliedIcon}}</span>
                `;
                dateListEl.appendChild(btn);
            }});
        }}
        
        function selectFeedback(idx) {{
            // Remove active classes
            document.querySelectorAll("#feedbackDateList button").forEach(btn => {{
                btn.className = "w-full text-left px-3 py-2.5 rounded-xl text-xs font-semibold bg-slate-900/60 text-slate-400 border border-slate-800/80 hover:bg-slate-800/60 hover:text-slate-200 transition flex flex-col gap-1";
            }});
            
            const activeBtn = document.getElementById("feedback-date-btn-" + idx);
            if (activeBtn) {{
                activeBtn.className = "w-full text-left px-3 py-2.5 rounded-xl text-xs font-semibold bg-amber-600/20 text-amber-200 border border-amber-500/30 flex flex-col gap-1 shadow-lg shadow-amber-950/30";
            }}
            
            const item = feedbackList[idx];
            if (!item) return;
            
            document.getElementById("feedbackSelectedDate").textContent = `제안일자: ${{item.date}} (${{item.timestamp.substring(11, 19)}})`;
            
            const badgeEl = document.getElementById("feedbackAppliedBadge");
            if (item.applied) {{
                badgeEl.innerHTML = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">🟢 소스코드 반영 완료</span>`;
            }} else {{
                badgeEl.innerHTML = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">🔴 미반영 (대기 중)</span>`;
            }}
            
            // Render markdown suggestion content
            let text = item.suggestion || "";
            document.getElementById("feedbackContent").textContent = text;
        }}
        
        function closeFeedbackModal() {{
            document.getElementById("feedbackModal").classList.add("hidden");
        }}
        
        // Client-side Bloomberg-like Timeline Filtering
        let activeSector = 'ALL';
        
        function filterSector(sect) {{
            activeSector = sect;
            
            // Toggle active styles on buttons
            document.querySelectorAll("#sectorFilters button").forEach(btn => {{
                btn.className = "sector-btn px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-slate-900/60 text-slate-400 border border-slate-800/80 hover:bg-slate-800/60 hover:text-slate-200 transition duration-200 hover:scale-105 active:scale-95";
            }});
            
            const safeId = "".join([c for c in sect if c.isalnum() || c in ["-", "_"]])
            const activeBtn = document.getElementById(sect === 'ALL' ? "filter-all" : "filter-" + safeId);
            if (activeBtn) {{
                activeBtn.className = "px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 text-white border border-indigo-500/20 transition duration-200 shadow-lg shadow-indigo-950/50 hover:scale-105 active:scale-95";
            }}
            
            filterTimeline();
        }}
        
        function filterTimeline() {{
            const searchInput = document.getElementById("searchInput");
            const query = searchInput.value.toLowerCase().trim();
            
            document.querySelectorAll("#timelineContainer .timeline-card").forEach(card => {{
                let show = true;
                
                // 1. Sector filter
                if (activeSector !== 'ALL') {{
                    const cardSectors = JSON.parse(card.getAttribute("data-sectors") || "[]");
                    if (!cardSectors.includes(activeSector)) {{
                        show = false;
                    }}
                }}
                
                // 2. Search query filter
                if (show && query) {{
                    const searchText = card.getAttribute("data-search-text") || "";
                    if (!searchText.includes(query)) {{
                        show = false;
                    }}
                }}
                
                if (show) {{
                    card.classList.remove("hidden");
                }} else {{
                    card.classList.add("hidden");
                }}
            }});
        }}
        
        // Dynamic automatic SSE refresh fallback (Checks count increase in background)
        setInterval(() => {{
            fetch('/api/count')
            .then(res => res.json())
            .then(data => {{
                if (data.count > lastCount) {{
                    const isUserActive = document.activeElement === document.getElementById("chatInput") || 
                                         document.activeElement === document.getElementById("searchInput");
                    
                    if (isUserActive) {{
                        console.log("[Pipeline] New news processed, but skipping reload because user is active.");
                        return;
                    }}
                    
                    console.log("[Pipeline] New news processed! Updating dashboard dynamically.");
                    loadTradingState();
                }}
            }})
            .catch(err => {{}});
        }}, 15000);
    </script>
</body>
</html>
"""
    
    try:
        with open("dashboard.html", "w", encoding="utf-8") as f:
            f.write(html)
        # print("[Dashboard] HTML Dashboard successfully updated.")
    except Exception as e:
        print(f"[Error] Failed to write dashboard.html: {str(e)}")
