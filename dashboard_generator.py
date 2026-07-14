import json
import os
from market import get_market_indicators
import db

def generate_html_dashboard():
    """
    Reads SQLite analysis history and generates a stunning, premium, modern HTML dashboard.
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

    # Dynamic Timeline Cards generation
    timeline_cards_html = ""
    if not rows:
        timeline_cards_html = """
            <div class="glass-card rounded-2xl p-12 text-center">
                <p class="text-slate-400">아직 수집하거나 분석한 항목이 없습니다.</p>
                <p class="text-xs text-slate-600 mt-2">프로그램을 가동하면 실시간으로 여기에 누적 분석 카드가 생성됩니다.</p>
            </div>
        """
    else:
        for r in rows:
            is_rel = r['is_relevant'] == 1
            processed_at = r['processed_at'][:19].replace('T', ' ')
            published_at = r.get('published_at', '')
            if published_at:
                published_at = published_at[:19].replace('T', ' ')
            else:
                published_at = "정보 없음"
                
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
                except Exception:
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
                search_text = f"{r['title']} {r['content']} {r['korean_summary']} {sectors_str} {companies_str} {r['source']}".lower().replace('"', '\"').replace("'", "\'")
                
                timeline_cards_html += f"""
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
                    
                    <div class="bg-slate-950/20 p-4 rounded-xl border border-white/5 mb-4">
                        <p class="text-xs font-semibold text-slate-500 mb-1">AI 요약 분석 (Gemini)</p>
                        <p class="text-sm text-slate-300 leading-relaxed">{r['korean_summary']}</p>
                    </div>
                    
                    <div class="flex justify-between items-center text-xs text-slate-500">
                        <span><strong class="text-slate-400">관련성 분류 이유:</strong> {r['relevance_reason']}</span>
                        {link_btn}
                    </div>
                    {other_sources_html}
                </div>
                """
            else:
                pass

    # Load HTML template from file
    template_file = "dashboard_template.html"
    if not os.path.exists(template_file):
        print(f"[Error] HTML template file '{template_file}' not found.")
        return

    try:
        with open(template_file, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception as e:
        print(f"[Error] Failed to read template file: {str(e)}")
        return

    # Replace placeholders
    html = html.replace("[[SECTOR_BUTTONS_HTML]]", sector_buttons_html)
    html = html.replace("[[MARKET_HTML]]", market_html)
    html = html.replace("[[TIMELINE_CARDS_HTML]]", timeline_cards_html)
    html = html.replace("[[TOTAL_PROCESSED]]", str(total_processed))
    html = html.replace("[[TOTAL_RELEVANT]]", str(total_relevant))
    html = html.replace("[[HIGH_ALERTS]]", str(high_alerts))
    html = html.replace("[[AVG_SENTIMENT]]", f"{avg_sentiment:+.2f}")
    html = html.replace("[[SENTIMENT_CLASS]]", sentiment_class)
    html = html.replace("[[SENTIMENT_LABEL]]", sentiment_label)

    try:
        with open("dashboard.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("[Dashboard] HTML Dashboard successfully updated.")
    except Exception as e:
        print(f"[Error] Failed to write dashboard.html: {str(e)}")
