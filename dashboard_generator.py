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
    html = html.replace("[[TOTAL_PROCESSED]]", str(total_processed))
    html = html.replace("[[TOTAL_RELEVANT]]", str(total_relevant))
    html = html.replace("[[HIGH_ALERTS]]", str(high_alerts))
    html = html.replace("[[AVG_SENTIMENT]]", f"{avg_sentiment:+.2f}")
    html = html.replace("[[SENTIMENT_CLASS]]", sentiment_class)
    html = html.replace("[[SENTIMENT_LABEL]]", sentiment_label)

    try:
        with open("dashboard.html", "w", encoding="utf-8") as f:
            f.write(html)
        # print("[Dashboard] HTML Dashboard successfully updated.")
    except Exception as e:
        print(f"[Error] Failed to write dashboard.html: {str(e)}")
