import os
import json
import sys
from colorama import Fore, Style

import db
import scraper
import report_scraper
from alerts import send_telegram_alert, send_slack_alert
from dashboard_generator import generate_html_dashboard

LOG_PATH = "log.txt"

def is_already_processed(url):
    return db.is_already_processed(url)

def save_analysis_result(item, rel_check, analysis, other_sources=None, analyzer=None):
    db.save_analysis_result(item, rel_check, analysis, other_sources, analyzer)

def find_similar_in_db(title, analyzer=None):
    return db.find_similar(title, analyzer)

def update_other_sources_in_db(url, new_source):
    db.update_other_sources(url, new_source)

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

def run_pipeline(config, analyzer):
    """
    Runs a single cycle of the pipeline: crawl -> check cache -> analyze -> save & log.
    Sends instant push notifications for HIGH level economic warnings.
    """
    cycle_time = db.get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
    print(Style.BRIGHT + Fore.CYAN + f"\n--- Starting Monitoring Cycle: {cycle_time} ---")
    
    # 1. Fetch
    try:
        report_scraper.run_report_scraper(limit=10)
    except Exception as e:
        print(Fore.RED + f"[Pipeline] [Error] Failed running report scraper: {e}")

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
        similar_record = find_similar_in_db(primary_item["title"], analyzer)
        if similar_record:
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
        save_analysis_result(primary_item, rel_check, analysis, batch_other_sources, analyzer)
        append_to_logfile(primary_item, rel_check, analysis, batch_other_sources)
        
        # Trigger Slack/Telegram instant notification if it is a high level warning
        if rel_check.relevant and analysis and analysis.alert_level == "HIGH":
            slack_url = config.get("slack_webhook_url")
            if slack_url and slack_url.strip():
                send_slack_alert(slack_url, primary_item["title"], analysis.korean_summary, analysis.alert_level, analysis.sentiment)
                
            tg_token = config.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
            tg_chat_id = config.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID")
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
    
    # 4. Auto-Purge old records
    try:
        retention_days = config.get("data_retention_days", 14)
        db.purge_old_records(retention_days)
    except Exception as e:
        print(f"[Warning] Auto-Purge failed: {str(e)}")
