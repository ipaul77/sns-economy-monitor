import sys
import os

# Adjust sys.path to run from the root workspace
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import report_scraper
from datetime import datetime

def run_integration_test():
    print("=== [Integration Test] 1. Initializing database and warming start ===")
    db.setup_db()
    
    print("\n=== [Integration Test] 2. Running report scraper ===")
    # Run the report scraper to fetch at most 3 items to avoid clutter
    reports_saved = report_scraper.run_report_scraper(limit=3)
    print(f"Scraper run finished. Saved {reports_saved} new reports.")
    
    print("\n=== [Integration Test] 3. Querying reports from local SQLite ===")
    recent_relevant = db.fetch_recent_relevant(hours=24)
    reports = [x for x in recent_relevant if x.get("source") == "Naver Research"]
    news = [x for x in recent_relevant if x.get("source") != "Naver Research"]
    
    print(f"Total relevant records in last 24h: {len(recent_relevant)}")
    print(f"- General news/SNS count: {len(news)}")
    print(f"- Naver analyst reports count: {len(reports)}")
    
    if reports:
        print("\nSample Saved Report:")
        sample = reports[0]
        print(f"  URL: {sample['url']}")
        print(f"  Title: {sample['title']}")
        print(f"  Source: {sample['source']}")
        print(f"  Sentiment: {sample['sentiment']} (Score: {sample['sentiment_score']})")
        print(f"  Summary: {sample['korean_summary'][:150]}...")
        print(f"  Impacted Companies: {sample['impacted_companies']}")
        print(f"  Impacted Tickers: {sample['impacted_tickers']}")
    else:
        print("\n[WARNING] No reports found. (If all items were already scraped, run with empty DB or clear URL cache to verify)")

    print("\n=== [Integration Test] 4. Simulating trading prompt formatting ===")
    # Let's verify the prompt rendering by simulating the same logic from trading_engine.py
    news_items = [item for item in recent_relevant if item.get("source") != "Naver Research"]
    report_items = [item for item in recent_relevant if item.get("source") == "Naver Research"]

    news_str = ""
    if not news_items:
        news_str = "최근 24시간 동안 수집된 한국 경제 관련 신규 뉴스가 없습니다."
    else:
        for idx, item in enumerate(news_items[:5]):
            news_str += (
                f"{idx+1}. [{item.get('source', '뉴스')}] {item.get('title', '')} (중요도: {item.get('relevance_score', 5)}/10) \n"
                f"   - 감성수준: {item.get('sentiment', 'NEUTRAL')} (점수: {item.get('sentiment_score', 0.0):+.2f}) \n"
                f"   - AI 분석 요약: {item.get('korean_summary', '')} \n"
            )

    report_str = ""
    if not report_items:
        report_str = "최근 24시간 동안 발표된 증권사 분석 리포트가 없습니다."
    else:
        for idx, item in enumerate(report_items[:5]):
            report_str += (
                f"{idx+1}. [{item.get('source', '리포트')}] {item.get('title', '')} (중요도: {item.get('relevance_score', 7)}/10) \n"
                f"   - 투자 의견/감성: {item.get('sentiment', 'NEUTRAL')} (점수: {item.get('sentiment_score', 0.0):+.2f}) \n"
                f"   - 리포트 요약 내용: {item.get('korean_summary', '')} \n"
            )

    # Output the test prompt template
    test_prompt = f"""
[최근 24시간 실시간 경제 뉴스 분석 컨텍스트]
{news_str}

[최근 24시간 증권사 분석 및 기관 보고서 요약 컨텍스트]
{report_str}
"""
    print("\nRendered Prompt Preview:")
    print(test_prompt)

if __name__ == "__main__":
    run_integration_test()
