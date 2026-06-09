import sys
import os
import time

# Adjust sys.path to run from the root workspace
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import trading_engine

def run_fundamental_test():
    print("=== [Fundamental Test] 1. Initializing databases ===")
    db.setup_db()
    
    # Test ticker: Samsung Electronics
    ticker = "005930"
    
    print(f"\n=== [Fundamental Test] 2. Checking initial indicator fetch for {ticker} ===")
    start_time = time.time()
    # First fetch (should trigger scraping because cache is empty)
    result_first = trading_engine.get_stock_indicators(ticker)
    first_duration = time.time() - start_time
    print(f"First Fetch Duration: {first_duration:.2f} seconds")
    print(f"Current Price: {result_first.get('current_price'):,}원")
    print(f"ROE: {result_first.get('roe')}%")
    print(f"Debt-to-Equity: {result_first.get('debt_to_equity')}%")
    print(f"Target Price: {result_first.get('target_price'):,}원")
    print(f"Calculated PER: {result_first.get('pe_ratio')}x")
    print(f"Calculated PBR: {result_first.get('pb_ratio')}x")
    print(f"Margin of Safety: {result_first.get('margin_of_safety')}%")
    
    # Verify DB writing (SQLite)
    sqlite_fund = db._sqlite_fetch_fundamentals(ticker)
    print("\nVerified SQLite cache contents:")
    if sqlite_fund:
        for k, v in sqlite_fund.items():
            print(f"  {k}: {v}")
    else:
        print("  [ERROR] No record in SQLite cache!")
        
    print(f"\n=== [Fundamental Test] 3. Running second fetch (Cache Hit check) ===")
    start_time = time.time()
    # Second fetch (should be instant and hit SQLite cache)
    result_second = trading_engine.get_stock_indicators(ticker)
    second_duration = time.time() - start_time
    print(f"Second Fetch Duration: {second_duration:.4f} seconds (Cache Hit!)")
    
    # Check if Cache hits are significantly faster
    if second_duration < first_duration / 5:
         print("  [PASS] Cache hit is indeed blazing fast (network skip confirmed!)")
    else:
         print("  [WARNING] Cache hit did not yield expected speedup. Investigate.")

    print("\n=== [Fundamental Test] 4. Simulating trading prompt formatting ===")
    # Format indicators exactly like in generate_trading_decision
    market_indicators = {ticker: result_first}
    indicators_str = ""
    for tick, ind in market_indicators.items():
        comp_name = "삼성전자"
        roe_val = ind.get("roe")
        roe_str = f"{roe_val:.1f}%" if roe_val is not None else "N/A"
        debt_val = ind.get("debt_to_equity")
        debt_str = f"{debt_val:.1f}%" if debt_val is not None else "N/A"
        pe_val = ind.get("pe_ratio")
        pe_str = f"{pe_val:.1f}x" if pe_val is not None else "N/A"
        pb_val = ind.get("pb_ratio")
        pb_str = f"{pb_val:.1f}x" if pb_val is not None else "N/A"
        target_val = ind.get("target_price")
        target_str = f"{target_val:,.0f}원" if target_val is not None else "N/A"
        safety_val = ind.get("margin_of_safety")
        safety_str = f"{safety_val:+.1f}%" if safety_val is not None else "N/A"

        indicators_str += (
            f"- 종목명: {comp_name} ({tick}) | "
            f"현재가: {ind.get('current_price', 0.0):,.0f}원 | "
            f"20일선 MA: {ind.get('ma_20', 0.0):,.0f}원 | "
            f"이격도: {ind.get('disparity', 100.0):.1f}% | "
            f"당일거래량: {ind.get('daily_volume', 0):,}주 | "
            f"외인5일누적: {ind.get('frgn_net_5d', 0):+d}주 | "
            f"기관5일누적: {ind.get('inst_net_5d', 0):+d}주 | "
            f"ROE: {roe_str} | 부채비율: {debt_str} | PER: {pe_str} | PBR: {pb_str} | 안전마진: {safety_str} (목표주가: {target_str})\n"
        )
        
    print("Formatted indicators_str in prompt:")
    print(indicators_str)

if __name__ == "__main__":
    run_fundamental_test()
