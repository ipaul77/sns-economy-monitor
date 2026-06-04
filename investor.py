import os
import sqlite3
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "monitor.db")

def get_kst_now():
    """
    Returns the current datetime in KST (UTC+9) without tzinfo.
    """
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).replace(tzinfo=None)

def setup_investor_db():
    """
    Sets up local SQLite tables for investor trends.
    This runs completely locally to avoid exhausting cloud Firestore quotas.
    """
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Table for storing daily net buy/sell volumes by foreigner and institution
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investor_trends (
            ticker TEXT,
            date TEXT,
            close_price INTEGER,
            inst_net_vol INTEGER,
            frgn_net_vol INTEGER,
            frgn_ratio REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    
    # 2. Table for tracking the last successful crawl time per ticker for cache validation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investor_trends_status (
            ticker TEXT PRIMARY KEY,
            last_updated TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    print("[Investor DB] SQLite tables initialized/verified.")

def fetch_and_cache_investor_trend(ticker: str) -> bool:
    """
    Scrapes Naver Finance investor trading trends and stores the last 20 days in SQLite.
    Optimized: Implements a 4-hour cache expiry to prevent rate-limiting and minimize network calls.
    """
    ticker = ticker.strip()
    if not ticker or len(ticker) != 6 or not ticker.isdigit():
        print(f"[Investor Scraper] Invalid ticker code skipped: '{ticker}'")
        return False

    setup_investor_db()
    
    now = get_kst_now()
    
    # Check cache status
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT last_updated FROM investor_trends_status WHERE ticker = ?", (ticker,))
    row = cursor.fetchone()
    
    if row:
        try:
            last_updated = datetime.fromisoformat(row[0])
            # Cache duration: 4 hours
            if now - last_updated < timedelta(hours=4):
                # Cache is hot. Skip fetching.
                conn.close()
                return True
        except Exception as e:
            print(f"[Investor Scraper] Cache timestamp parse error for {ticker}: {e}")

    # Cache expired or does not exist. Perform scrape.
    print(f"[Investor Scraper] Cache expired/missing for {ticker}. Fetching Naver Finance...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://finance.naver.com/item/frgn.naver?code={ticker}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"[Investor Scraper] [Error] Failed to fetch Naver page for {ticker}, HTTP {response.status_code}")
            conn.close()
            return False
            
        response.encoding = 'euc-kr'
        soup = BeautifulSoup(response.text, "html.parser")
        
        type2_tables = soup.find_all("table", {"class": "type2"})
        if not type2_tables:
            print(f"[Investor Scraper] [Warning] No tables with class type2 found for {ticker}")
            conn.close()
            return False
            
        data_inserted = False
        
        for table in type2_tables:
            rows = table.find_all("tr")
            parsed_rows = []
            
            for r in rows:
                cells = r.find_all("td")
                if len(cells) < 9:
                    continue
                    
                date = cells[0].text.strip()
                if not re.match(r"\d{4}\.\d{2}\.\d{2}", date):
                    continue
                    
                try:
                    # Clean the date to standard YYYY-MM-DD
                    clean_date = date.replace(".", "-")
                    
                    close_price = int(cells[1].text.strip().replace(",", ""))
                    
                    # Institution net buying volume
                    inst_volume = int(cells[5].text.strip().replace(",", ""))
                    
                    # Foreigner net buying volume
                    frgn_volume = int(cells[6].text.strip().replace(",", ""))
                    
                    # Foreigner holding ratio percentage (float)
                    frgn_ratio = float(cells[8].text.strip().replace("%", ""))
                    
                    parsed_rows.append((ticker, clean_date, close_price, inst_volume, frgn_volume, frgn_ratio))
                except Exception:
                    continue
            
            if parsed_rows:
                # Save to database
                cursor.executemany("""
                    INSERT OR REPLACE INTO investor_trends (
                        ticker, date, close_price, inst_net_vol, frgn_net_vol, frgn_ratio
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, parsed_rows)
                data_inserted = True
                break  # Successfully parsed the correct table
                
        if data_inserted:
            # Update cache status
            cursor.execute("""
                INSERT OR REPLACE INTO investor_trends_status (ticker, last_updated)
                VALUES (?, ?)
            """, (ticker, now.isoformat()))
            conn.commit()
            print(f"[Investor Scraper] Successfully cached {len(parsed_rows)} days of data for {ticker}.")
            conn.close()
            return True
        else:
            print(f"[Investor Scraper] [Warning] Failed to parse any data rows for {ticker}")
            conn.close()
            return False
            
    except Exception as e:
        print(f"[Investor Scraper] [Error] Scraper exception occurred for {ticker}: {e}")
        conn.close()
        return False

def get_investor_indicators(ticker: str) -> dict:
    """
    Retrieves sugeup indicators from SQLite (scraping if cache is expired).
    Computes aggregated features to minimize tokens for Gemini.
    """
    # Auto scrape/update if cache is expired
    fetch_and_cache_investor_trend(ticker)
    
    result = {
        "frgn_net_5d": 0,
        "inst_net_5d": 0,
        "frgn_net_10d": 0,
        "inst_net_10d": 0,
        "dual_buy_5d_count": 0,
        "frgn_ratio": 0.0,
        "frgn_trend_sig": "HOLD",
        "inst_trend_sig": "HOLD"
    }
    
    setup_investor_db()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Fetch last 10 days of sugeup data sorted by date descending
        cursor.execute("""
            SELECT inst_net_vol, frgn_net_vol, frgn_ratio 
            FROM investor_trends 
            WHERE ticker = ? 
            ORDER BY date DESC 
            LIMIT 10
        """, (ticker,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return result
            
        # Current Foreigner Ratio (from the most recent trading day)
        result["frgn_ratio"] = rows[0][2]
        
        # Calculate 5-day indicators
        rows_5d = rows[:5]
        frgn_5d = [r[1] for r in rows_5d]
        inst_5d = [r[0] for r in rows_5d]
        
        result["frgn_net_5d"] = sum(frgn_5d)
        result["inst_net_5d"] = sum(inst_5d)
        
        # Count dual buy days (both inst > 0 and frgn > 0)
        result["dual_buy_5d_count"] = sum(1 for r in rows_5d if r[0] > 0 and r[1] > 0)
        
        # Calculate 10-day indicators
        result["frgn_net_10d"] = sum(r[1] for r in rows)
        result["inst_net_10d"] = sum(r[0] for r in rows)
        
        # Calculate trend signals (BUY if net buying is positive, SELL if negative, HOLD if neutral)
        if result["frgn_net_5d"] > 10000:  # Threshold to avoid noise
            result["frgn_trend_sig"] = "BUY"
        elif result["frgn_net_5d"] < -10000:
            result["frgn_trend_sig"] = "SELL"
        else:
            result["frgn_trend_sig"] = "HOLD"
            
        if result["inst_net_5d"] > 10000:
            result["inst_trend_sig"] = "BUY"
        elif result["inst_net_5d"] < -10000:
            result["inst_trend_sig"] = "SELL"
        else:
            result["inst_trend_sig"] = "HOLD"
            
    except Exception as e:
        print(f"[Investor DB] [Error] Failed to query sugeup indicators for {ticker}: {e}")
        try:
            conn.close()
        except:
            pass
            
    return result

def calculate_leading_flow_score(soxx_change: float, usdkrw_change: float) -> int:
    """
    Translates SOXX and USD/KRW exchange rate changes into a 1-10 integer score.
    Score represents the probability/intensity of foreigner inflow today.
    - Base score is 5.
    - Positive SOXX adds up to +3. Negative SOXX subtracts up to -3.
    - Negative USD/KRW change (won strengthens) adds up to +2. Positive subtracts up to -2.
    """
    score = 5
    
    # 1. SOXX impact (Philadelphia Semiconductor Index)
    if soxx_change > 0:
        score += min(int(soxx_change * 1.5), 3)
    elif soxx_change < 0:
        score -= min(int(abs(soxx_change) * 1.5), 3)
        
    # 2. USD/KRW Exchange Rate impact (Won appreciation/depreciation)
    # Note: Exchange rate drop is GOOD for foreigner inflows.
    if usdkrw_change < 0:
        score += min(int(abs(usdkrw_change) * 2.0), 2)
    elif usdkrw_change > 0:
        score -= min(int(usdkrw_change * 2.0), 2)
        
    # Boundary clipping
    score = max(min(score, 10), 1)
    return score

if __name__ == "__main__":
    setup_investor_db()
    ticker = "005930"
    print(f"Fetching indicators for {ticker}...")
    ind = get_investor_indicators(ticker)
    print("Indicators result:")
    for k, v in ind.items():
        print(f"  {k}: {v}")
    
    print("\nTesting Leading Flow Score:")
    # High SOXX, dropping exchange rate -> Expect score 9-10
    print(f"SOXX +3%, USD/KRW -0.8% -> Score: {calculate_leading_flow_score(3.0, -0.8)}")
    # Dropping SOXX, rising exchange rate -> Expect score 1-2
    print(f"SOXX -2.5%, USD/KRW +0.6% -> Score: {calculate_leading_flow_score(-2.5, 0.6)}")
