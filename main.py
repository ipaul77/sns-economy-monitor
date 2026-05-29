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

def find_similar_in_db(title):
    return db.find_similar(title)

def update_other_sources_in_db(url, new_source):
    db.update_other_sources(url, new_source)

def generate_html_dashboard():
    """
    Reads SQLite analysis history and generates a stunning, premium, modern HTML dashboard.
    Fetches real-time stock/exchange rate market indicators dynamically on generation!
    """
    try:
        rows = db.fetch_history()
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
        unit = "pt" if label == "KOSPI" else ("원" if label in ["SAMSUNG", "HYNIX"] else "원")
        
        display_label = "코스피 지수" if label == "KOSPI" else ("원/달러 환율" if label == "USD_KRW" else ("삼성전자" if label == "SAMSUNG" else "SK하이닉스"))
        
        market_html += f"""
        <div class="glass-card rounded-2xl p-4 {bg_glow} border border-slate-800/80">
            <p class="text-xs font-semibold text-slate-500">{display_label} ({info['symbol']})</p>
            <div class="flex items-baseline justify-between mt-1">
                <span class="text-lg font-bold text-slate-100">{info['price']:,}{unit}</span>
                <span class="text-xs font-bold {text_color}">{change_sign}{info['change']:,} ({change_sign}{info['percent']}%)</span>
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
                <p class="mt-1 text-lg font-extrabold text-slate-100">{total_processed} 건</p>
            </div>
            <div class="glass-card rounded-xl p-3 glow-green">
                <p class="text-xs font-semibold text-slate-400">연관 기사</p>
                <p class="mt-1 text-lg font-extrabold text-emerald-400">{total_relevant} 건</p>
            </div>
            <div class="glass-card rounded-xl p-3 glow-red">
                <p class="text-xs font-semibold text-slate-400">고위험 경보 (HIGH)</p>
                <p class="mt-1 text-lg font-extrabold text-rose-500">{high_alerts} 건</p>
            </div>
            <div class="glass-card rounded-xl p-3 glow-blue">
                <p class="text-xs font-semibold text-slate-400">평균 감성 지수</p>
                <p class="mt-1 text-lg font-extrabold {sentiment_class}">{avg_sentiment:+.2f}</p>
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
                            <span class="text-base font-bold text-slate-100">AI 에이전트 모의투자 계좌</span>
                            <span class="text-xs text-slate-500 ml-2">(초기 가상 자산: 10,000,000원 | 운용 30일 제한)</span>
                        </div>
                    </div>
                    <div>
                        <button onclick="triggerManualTrade()" id="tradeTriggerBtn" class="px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white shadow-lg transition duration-200 flex items-center gap-1.5">
                            ⚡ AI 모의투자 매매 1사이클 강제 구동
                        </button>
                    </div>
                </div>

                <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 my-6">
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">예수금 (Cash)</p>
                        <p class="mt-1 text-lg font-extrabold text-slate-100" id="tradingCash">10,000,000원</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">보유 주식 평가금액</p>
                        <p class="mt-1 text-lg font-extrabold text-slate-100" id="tradingStockValue">0원</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">총 평가 자산 (Total Asset)</p>
                        <p class="mt-1 text-lg font-extrabold text-slate-100" id="tradingTotalAsset">10,000,000원</p>
                    </div>
                    <div class="bg-slate-950/40 p-4 rounded-xl border border-white/5">
                        <p class="text-xs font-semibold text-slate-500">누적 수익률 (Total ROI)</p>
                        <p class="mt-1 text-lg font-extrabold text-slate-100" id="tradingROI">+0.00%</p>
                    </div>
                </div>

                <div id="systemLockBanner" class="hidden bg-rose-950/30 border border-rose-500/20 p-4 rounded-xl flex items-center space-x-3 mb-6">
                    <svg class="h-5 w-5 text-rose-500 flex-shrink-0 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m0 0v3m0-3h3m-3 0H9m12-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <div>
                        <p class="text-xs font-bold text-rose-400">🚨 시스템 강제 잠금 상태 (Accounting Assert Safety Lock Active)</p>
                        <p class="text-[11px] text-rose-500 mt-0.5">최근 매매 실행 후 자산 무결성 검증 실패(10원 초과 오차 검출)로 오작동 방지 시스템이 작동하여 모든 에이전트 거래가 정지되었습니다.</p>
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
                        <div class="overflow-x-auto rounded-xl border border-slate-800/80 bg-slate-950/20 max-h-[162px] overflow-y-auto">
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
        
        <div class="space-y-6">
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
        // AI Trading State Loader & Manual Trigger JS (Classic String Concat for Python f-string Safety)
        function loadTradingState() {{
            fetch('/api/trading/state')
            .then(res => res.json())
            .then(data => {{
                if (data.status !== "success") return;
                const state = data.state;
                const portfolio = data.portfolio;
                const marketPrices = data.market_prices;
                const transactions = data.transactions;
                
                document.getElementById("tradingCash").textContent = Math.round(state.balance).toLocaleString() + "원";
                document.getElementById("tradingTotalAsset").textContent = Math.round(state.total_asset).toLocaleString() + "원";
                
                let stockVal = state.total_asset - state.balance;
                document.getElementById("tradingStockValue").textContent = Math.round(stockVal).toLocaleString() + "원";
                
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
                    "000100": "유한양행"
                }};
                
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
                                    '<td class="px-3 py-2 text-slate-400 text-left line-clamp-1 max-w-[220px]" title="' + tx.reasoning + '">' + tx.reasoning + '</td>';
                    txBody.appendChild(row);
                }});
                
                if (txCount === 0) {{
                    txBody.innerHTML = `
                        <tr>
                            <td colspan="5" class="px-3 py-6 text-center text-slate-500">최근 거래 기록이 없습니다.</td>
                        </tr>
                    `;
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
                    // Attach ok flag to the data
                    parsed._ok = res.ok;
                    return parsed;
                }} catch(e) {{
                    throw new Error("HTTP " + res.status + " | " + text.substring(0, 300));
                }}
            }})
            .then(data => {{
                if (data._ok && data.status === "success") {{
                    alert("[매매 체결] 구분: " + data.action + ", 종목코드: " + data.ticker + ", 수량: " + data.quantity + "주, 단가: " + Math.round(data.price).toLocaleString() + "원\\n\\n[이유] " + data.reasoning);
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
            const query = input.value.strip ? input.value.trim() : input.value;
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
                
                // Append AI message bubble (parsed as simple HTML since markdown could contain basic blocks)
                const aiBubble = document.createElement("div");
                aiBubble.className = "bg-indigo-950/20 text-slate-300 p-3 rounded-2xl border border-indigo-500/10 max-w-[85%] leading-relaxed";
                
                // Simple markdown parser for bold and lists
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
                // Reload page to reflect new DB values
                window.location.reload();
            }})
            .catch(err => {{
                alert("수동 갱신 오류가 발생했습니다.");
                btn.disabled = false;
                btn.innerHTML = "🔄 실시간 수동 갱신";
            }});
        }}
        
        // Client-side Bloomberg-like Timeline Filtering
        let activeSector = 'ALL';
        
        function filterSector(sector) {{
            activeSector = sector;
            
            // Clear other buttons active styles
            const buttons = document.querySelectorAll('#sectorFilters button');
            buttons.forEach(btn => {{
                btn.className = "px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-slate-900/60 text-slate-400 border border-slate-800/80 hover:bg-slate-800/60 hover:text-slate-200 transition duration-200 hover:scale-105 active:scale-95";
            }});
            
            // Highlight active button
            const safeId = sector === 'ALL' ? 'all' : sector.replace(/[^a-zA-Z0-9-_]/g, '');
            const activeBtn = document.getElementById('filter-' + safeId);
            if (activeBtn) {{
                activeBtn.className = "px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 text-white border border-indigo-500/20 transition duration-200 shadow-lg shadow-indigo-950/50 hover:scale-105 active:scale-95";
            }}
            
            filterTimeline();
        }}
        
        function filterTimeline() {{
            const query = document.getElementById("searchInput").value.toLowerCase().trim();
            const cards = document.querySelectorAll(".timeline-card");
            
            cards.forEach(card => {{
                const sectors = JSON.parse(card.getAttribute("data-sectors") || "[]");
                const searchText = card.getAttribute("data-search-text") || "";
                
                const matchesSector = (activeSector === 'ALL') || sectors.includes(activeSector);
                const matchesQuery = (query === '') || searchText.includes(query);
                
                if (matchesSector && matchesQuery) {{
                    card.style.display = "block";
                    // Reset display transition
                    setTimeout(() => {{
                        card.style.opacity = "1";
                        card.style.transform = "translateY(0) scale(1)";
                    }}, 10);
                }} else {{
                    card.style.display = "none";
                    card.style.opacity = "0";
                    card.style.transform = "translateY(4px) scale(0.98)";
                }}
            }});
        }}
        
        // Dynamic dynamic AJAX Fetch updates! (Runs every 15s in background, checks total item count, reloads if new)
        let lastCount = {total_processed};
        setInterval(() => {{
            fetch('/api/count')
            .then(res => res.json())
            .then(data => {{
                if (data.count > lastCount) {{
                    // Skip reload if user is actively viewing briefing, chatting, or searching/filtering
                    const briefingOpen = !document.getElementById("briefingModal").classList.contains("hidden");
                    const chatOpen = !document.getElementById("chatWindow").classList.contains("hidden");
                    const searchInput = document.getElementById("searchInput");
                    const searchActive = searchInput && (document.activeElement === searchInput || searchInput.value.trim() !== "");
                    
                    if (briefingOpen || chatOpen || searchActive) {{
                        console.log("[Pipeline] New news processed, but skipping reload because user is active.");
                        return;
                    }}
                    
                    console.log("[Pipeline] New news processed! Reloading dashboard page dynamically.");
                    window.location.reload();
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

def is_already_processed(url):
    return db.is_already_processed(url)

def save_analysis_result(item, rel_check, analysis, other_sources=None):
    db.save_analysis_result(item, rel_check, analysis, other_sources)

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
            return json.load(f)
    except Exception as e:
        print(f"[Error] Failed to load config.json: {str(e)}")
        sys.exit(1)

def run_pipeline(config, analyzer):
    """
    Runs a single cycle of the pipeline: crawl -> check cache -> analyze -> save & log.
    Sends instant push notifications for HIGH level economic warnings.
    """
    cycle_time = db.get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
    print(Style.BRIGHT + Fore.CYAN + f"\n--- Starting Monitoring Cycle: {cycle_time} ---")
    
    # 1. Fetch
    raw_items = scraper.fetch_all_sources(config)
    if not raw_items:
        print(Fore.YELLOW + "[Pipeline] No articles collected in this cycle.")
        return
        
    # 2. Group items in the current batch by title similarity to prevent double processing
    grouped_items = []
    for item in raw_items:
        found_group = False
        for group in grouped_items:
            primary = group[0]
            if db.get_similarity(item["title"], primary["title"]) > 0.75:
                group.append(item)
                found_group = True
                break
        if not found_group:
            grouped_items.append([item])
            
    new_processed_count = 0
    relevant_count = 0
    
    for group in grouped_items:
        primary_item = group[0]
        url = primary_item.get("url")
        if not url:
            continue
            
        # Collect other sources in this batch group
        batch_other_sources = list(set([x["source"] for x in group[1:] if x.get("source") != primary_item.get("source")]))
        
        # Check if this primary URL is already processed
        if is_already_processed(url):
            # Already analyzed previously, check if we need to add other sources in this batch
            for src in batch_other_sources:
                update_other_sources_in_db(url, src)
            continue
            
        # Check if a similar story already exists in the database from a previous run
        similar_record = find_similar_in_db(primary_item["title"])
        if similar_record:
            # We already have an analyzed version of this story!
            # We don't analyze again. We just append the primary source and all other batch sources to the existing story!
            existing_url = similar_record["url"]
            print(Fore.LIGHTBLACK_EX + f"\n[Duplicate Story] '{primary_item['title']}' matches existing story in DB. Merging sources...")
            
            update_other_sources_in_db(existing_url, primary_item["source"])
            for src in batch_other_sources:
                update_other_sources_in_db(existing_url, src)
            continue
            
        # If it is a completely new story, execute the E2E pipeline!
        new_processed_count += 1
        print(Fore.WHITE + f"\n[New Item] {primary_item['title']} ({primary_item['source']})")
        if batch_other_sources:
            print(Fore.LIGHTBLUE_EX + f"  └─ Co-reporting sources: {', '.join(batch_other_sources)}")
            
        # Run 2-Stage Analyzer
        rel_check, analysis = analyzer.process_item(primary_item)
        
        # Save to SQLite and log.txt
        save_analysis_result(primary_item, rel_check, analysis, batch_other_sources)
        append_to_logfile(primary_item, rel_check, analysis, batch_other_sources)
        
        # Trigger Slack/Telegram instant notification if it is a high level warning
        if rel_check.relevant and analysis and analysis.alert_level == "HIGH":
            # Send Slack webhook
            slack_url = config.get("slack_webhook_url")
            if slack_url and slack_url.strip():
                send_slack_alert(slack_url, primary_item["title"], analysis.korean_summary, analysis.alert_level, analysis.sentiment)
                
            # Send Telegram Bot push alert
            tg_token = config.get("telegram_bot_token")
            tg_chat_id = config.get("telegram_chat_id")
            if tg_token and tg_chat_id:
                send_telegram_alert(tg_token, tg_chat_id, primary_item["title"], analysis.korean_summary, analysis.alert_level, analysis.sentiment)
        
        # Visual terminal output
        if rel_check.relevant:
            relevant_count += 1
            alert_color = Fore.RED if analysis.alert_level == "HIGH" else (Fore.YELLOW if analysis.alert_level == "MEDIUM" else Fore.GREEN)
            
            print(Fore.GREEN + f"  └─ [RELEVANT] {rel_check.reason}")
            print(alert_color + f"  └─ Alert Level: {analysis.alert_level} | Sentiment: {analysis.sentiment} (Score: {analysis.sentiment_score})")
            print(Fore.MAGENTA + f"  └─ Impacted: {', '.join(analysis.impacted_sectors)} | Companies: {', '.join(analysis.impacted_companies)}")
            print(Fore.CYAN + f"  └─ Macro Impact: {analysis.macro_impacts}")
            print(Fore.WHITE + Style.DIM + f"  └─ Summary: {analysis.korean_summary}")
        else:
            print(Fore.LIGHTBLACK_EX + f"  └─ [NOT RELEVANT] {rel_check.reason}")
            
    print(Fore.CYAN + f"\n[Cycle Summary] Processed {new_processed_count} new entries, found {relevant_count} relevant to the Korean Economy.")
    print(Style.BRIGHT + Fore.CYAN + "---------------------------------------------")
    
    # 3. Generate updated HTML dashboard
    generate_html_dashboard()
    
    # 4. Auto-Purge old records to keep Firestore database size forever free!
    try:
        retention_days = config.get("data_retention_days", 14)
        db.purge_old_records(retention_days)
    except Exception as e:
        print(f"[Warning] Auto-Purge failed: {str(e)}")


# --- FLASK APP ENDPOINTS ---

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
    Can be triggered by external cron (cron-job.org) or by manual UI refresh.
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
            
        result = trading_engine.run_simulation_cycle(bypass_hours=bypass_hours)
        return jsonify(result)
    except Exception as e:
        import traceback
        err_stack = traceback.format_exc()
        print(f"[Trading Engine] [API Error] {err_stack}")
        return jsonify({
            "status": "error",
            "message": f"Simulation cycle execution failed: {str(e)}",
            "traceback": err_stack
        }), 500

@app.route('/api/trading/state')
def get_trading_state():
    """
    API endpoint: Returns the current paper trading state, portfolio holdings,
    and recent transactions to populate the dashboard UI.
    """
    try:
        import trading_engine
        state = trading_engine.get_agent_state()
        portfolio = trading_engine.get_portfolio_holdings()
        transactions = trading_engine.get_latest_transactions(limit=15)
        
        # Gather current stock prices to compute real-time value and ROI on front-end
        market_prices = {}
        for ticker in portfolio.keys():
            price = trading_engine.get_stock_price(ticker)
            if price > 0:
                market_prices[ticker] = price
                
        return jsonify({
            "status": "success",
            "state": state,
            "portfolio": portfolio,
            "market_prices": market_prices,
            "transactions": transactions
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to retrieve paper trading state: {str(e)}"
        }), 500


# --- SCHEDULER & RUN THREAD ---

def scheduler_thread():
    """
    Background daemon thread that continuously crawls, analyzes, and saves news on an interval.
    """
    interval = global_config.get("scraping_interval_seconds", 60)
    print(Fore.BLUE + f"[Scheduler] Background crawler thread active. (Interval: {interval} seconds)...")
    
    # Run once immediately on startup
    try:
        run_pipeline(global_config, global_analyzer)
    except Exception as e:
        print(f"[Error] Initial startup pipeline failed: {str(e)}")
        
    while True:
        time.sleep(interval)
        try:
            run_pipeline(global_config, global_analyzer)
        except Exception as e:
            print(f"[Error] Periodic background pipeline failed: {str(e)}")

# Setup Database & Load Configurations at module level (WSGI / Cloud compatible)
setup_database()
global_config = load_config()
global_analyzer = GeminiEconomyAnalyzer()

# Pre-generate dashboard.html from cache on startup
generate_html_dashboard()

# Start background crawler thread immediately on import ONLY if enabled in config
if global_config.get("realtime_monitoring_enabled", False):
    t = threading.Thread(target=scheduler_thread, daemon=True)
    t.start()

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run once and exit (for standard Cron triggers)")
    args = parser.parse_args()
    
    if args.once:
        print(Fore.BLUE + "\n[Mode] Running once (Cron triggered)...")
        run_pipeline(global_config, global_analyzer)
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
