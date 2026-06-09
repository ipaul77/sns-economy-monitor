import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

import db
from analyzer import RelevanceCheck, DeepAnalysis

# User-Agent header to bypass potential basic scraping blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove excess whitespace and newlines
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def get_kst_now() -> datetime:
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).replace(tzinfo=None)

def parse_naver_date_to_iso(date_str: str) -> str:
    """
    Converts Naver report date format '26.06.09' or '2026.06.09' to KST ISO 8601 string.
    """
    try:
        date_str = date_str.strip()
        # Handle 'yy.mm.dd' or 'yyyy.mm.dd'
        parts = date_str.split('.')
        if len(parts) == 3:
            year = parts[0]
            month = parts[1]
            day = parts[2]
            if len(year) == 2:
                year = "20" + year
            # Assume 09:00 KST as standard report release time
            dt = datetime(int(year), int(month), int(day), 9, 0, 0)
            return dt.isoformat()
    except Exception as e:
        print(f"[Report Scraper] Failed to parse date '{date_str}': {e}")
    
    # Fallback to current KST time
    return get_kst_now().isoformat()

def scrape_report_detail(detail_url: str) -> Tuple[str, str, str]:
    """
    Scrapes the detail page of a report to extract the content summary, 
    target price, and investment opinion.
    Returns: (summary_text, target_price_str, investment_opinion_str)
    """
    try:
        response = requests.get(detail_url, headers=HEADERS, timeout=10)
        response.encoding = 'cp949'  # Naver Finance uses CP949
        
        if response.status_code != 200:
            return "", "", ""
            
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return "", "", ""
            
        target_table = tables[0]
        tds = target_table.find_all("td")
        
        target_price = ""
        opinion = ""
        summary = ""
        
        # Cell 0 contains Target Price and Opinion
        if len(tds) >= 1:
            cell0_text = tds[0].text.strip()
            # Parse target price e.g., "목표가 450,000"
            price_match = re.search(r"목표가\s*([\d,]+)", cell0_text)
            if price_match:
                target_price = price_match.group(1).replace(",", "")
            # Parse opinion e.g., "투자의견 매수" or "투자의견 BUY"
            opinion_match = re.search(r"투자의견\s*(\S+)", cell0_text)
            if opinion_match:
                opinion = opinion_match.group(1)
                
        # Cell 2 typically contains the main summary text
        if len(tds) >= 3:
            cell2_text = tds[2].text.strip()
            # Clean up the text
            summary = clean_text(cell2_text)
            # Filter out PDF file name at the end if it matches (e.g. NAVER_기업리포트_260609.pdf)
            pdf_match = re.search(r"\S+\.pdf$", summary)
            if pdf_match:
                summary = summary[:pdf_match.start()].strip()
                
        return summary, target_price, opinion
    except Exception as e:
        print(f"[Report Scraper] Error scraping detail page '{detail_url}': {e}")
        return "", "", ""

def analyze_report_locally(
    ticker_name: str, 
    ticker_code: str, 
    title: str, 
    summary: str, 
    opinion: str, 
    target_price: str
) -> Tuple[RelevanceCheck, DeepAnalysis]:
    """
    Executes a local rule-based heuristic analysis on the scraped report content.
    Cost: 0 API Tokens.
    """
    # 1. Determine Sentiment and Score based on opinion, title, and summary keywords
    sentiment = "NEUTRAL"
    sentiment_score = 0.0
    
    # Text pool for keyword search
    search_text = f"{title} {summary} {opinion}".lower()
    
    # Positive triggers
    positive_words = ["매수", "buy", "상향", "호실적", "서프라이즈", "성장", "최선호", "탑픽", "호조", "개선"]
    # Negative triggers
    negative_words = ["매도", "sell", "하향", "부진", "하회", "우려", "쇼크", "둔화", "감소", "리스크"]
    
    pos_count = sum(1 for w in positive_words if w in search_text)
    neg_count = sum(1 for w in negative_words if w in search_text)
    
    # Refine opinion mapping
    opinion_clean = opinion.upper().strip() if opinion else ""
    
    if "매수" in opinion_clean or "BUY" in opinion_clean or "STRONG BUY" in opinion_clean:
        sentiment = "POSITIVE"
        sentiment_score = 0.6
        if "상향" in title or "서프라이즈" in title:
            sentiment_score = 0.8
    elif "매도" in opinion_clean or "SELL" in opinion_clean or "REDUCE" in opinion_clean:
        sentiment = "NEGATIVE"
        sentiment_score = -0.6
        if "하향" in title or "쇼크" in title:
            sentiment_score = -0.8
    else:
        # Fallback to keyword counts
        if pos_count > neg_count + 1:
            sentiment = "POSITIVE"
            sentiment_score = 0.4
        elif neg_count > pos_count + 1:
            sentiment = "NEGATIVE"
            sentiment_score = -0.4
            
    # 2. Build impacted sectors based on keywords
    sectors = ["기타"]
    sector_keywords = {
        "반도체": ["반도체", "hbm", "칩", "파운드", "메모리", "dram", "낸드"],
        "IT H/W": ["디스플레이", "it 하드웨어", "부품", "기기"],
        "이차전지": ["배터리", "이차전지", "양극재", "음극재", "셀", "sdi", "엔솔"],
        "자동차": ["자동차", "현대차", "기아", "완성차", "부품사"],
        "플랫폼/인터넷": ["플랫폼", "인터넷", "네이버", "카카오", "naver", "kakao", "게임"],
        "금융": ["은행", "금융지주", "증권", "보험", "금리", "배당"],
        "바이오": ["바이오", "제약", "셀트리온", "한미", "유한", "임상"]
    }
    
    detected_sectors = []
    for sect, keywords in sector_keywords.items():
        if any(kw in search_text for kw in keywords):
            detected_sectors.append(sect)
            
    if detected_sectors:
        sectors = detected_sectors
        
    # 3. Macro impacts template
    target_info = f"목표가 {int(target_price):,}원 제시" if target_price and target_price.isdigit() else "의견 변동"
    macro_impacts = f"해당 기업({ticker_name})의 애널리스트 분석({opinion if opinion else '의견 제공'}, {target_info}) 정보가 주식 시장 수급 및 업종별 센티먼트에 개별적 영향 유발."
    
    # 4. Korean summary fallback if detail was empty
    summary_text = summary if summary else f"{ticker_name}에 대한 증권사 분석 보고서: {title} ({opinion if opinion else '투자의견 없음'})"
    
    # 5. Alert Level
    alert_level = "MEDIUM"
    if sentiment_score >= 0.8 or sentiment_score <= -0.8:
        alert_level = "HIGH"
        
    rel_check = RelevanceCheck(
        relevant=True,
        reason=f"증권사(네이버 증권 리서치) 종목 분석 리포트 - 대상 기업: {ticker_name}"
    )
    
    analysis = DeepAnalysis(
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        relevance_score=7, # High quality analyst intelligence
        impacted_sectors=sectors,
        impacted_companies=[ticker_name],
        impacted_tickers=[ticker_code],
        macro_impacts=macro_impacts,
        korean_summary=summary_text,
        alert_level=alert_level
    )
    
    return rel_check, analysis

def run_report_scraper(limit: int = 10) -> int:
    """
    Main entry point for scraping and saving analyst reports.
    Returns: The number of new reports successfully processed and saved.
    """
    url = "https://finance.naver.com/research/company_list.naver"
    print(f"[Report Scraper] Checking for new analyst reports at {url}...")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.encoding = 'cp949'
        
        if response.status_code != 200:
            print(f"[Report Scraper] Failed to fetch report list. Status: {response.status_code}")
            return 0
            
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", class_="type_1")
        if not table:
            print("[Report Scraper] Could not find report table with class 'type_1'")
            return 0
            
        rows = table.find_all("tr")
        new_count = 0
        
        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 5:
                continue
                
            ticker_td = tds[0]
            title_td = tds[1]
            writer_td = tds[2]
            date_td = tds[4]
            
            ticker_a = ticker_td.find("a")
            title_a = title_td.find("a")
            
            if not title_a:
                continue
                
            ticker_name = ticker_a.text.strip() if ticker_a else ""
            ticker_code = ""
            if ticker_a and 'href' in ticker_a.attrs:
                href = ticker_a['href']
                match = re.search(r"code=(\d{6})", href)
                if match:
                    ticker_code = match.group(1)
                    
            report_title = title_a.text.strip()
            detail_url = "https://finance.naver.com/research/" + title_a['href']
            writer = writer_td.text.strip()
            pub_date_str = date_td.text.strip()
            
            # Check duplicate before wasting request on detail page
            if db.is_already_processed(detail_url):
                # Since reports are sorted by date desc, meeting a processed link might mean we are caught up
                # However, to be robust, we'll continue checking other rows in the page, but not request details
                continue
                
            print(f"[Report Scraper] New report found! Title: {report_title} | Company: {ticker_name}")
            
            # Scrape detail page
            summary, target_price, opinion = scrape_report_detail(detail_url)
            
            # Local analysis (0 API tokens!)
            rel_check, analysis = analyze_report_locally(
                ticker_name=ticker_name,
                ticker_code=ticker_code,
                title=report_title,
                summary=summary,
                opinion=opinion,
                target_price=target_price
            )
            
            # Prepare item structure for DB saving
            item = {
                "url": detail_url,
                "title": f"[증권사 리포트 - {writer}] {ticker_name}: {report_title}",
                "content": summary if summary else report_title,
                "source": "Naver Research",
                "published_at": parse_naver_date_to_iso(pub_date_str)
            }
            
            # Save to SQLite and Firestore
            db.save_analysis_result(item, rel_check, analysis)
            new_count += 1
            
            if new_count >= limit:
                print(f"[Report Scraper] Hit batch limit of {limit}. Stopping.")
                break
                
        print(f"[Report Scraper] Completed cycle. Saved {new_count} new analyst reports.")
        return new_count
        
    except Exception as e:
        print(f"[Report Scraper] Critical error in report scraper run: {e}")
        return 0

if __name__ == "__main__":
    # Test script locally when run directly
    print("[Report Scraper] Running manual test cycle...")
    db.setup_db()
    count = run_report_scraper(limit=3)
    print(f"[Report Scraper] Test finished. Processed {count} items.")
