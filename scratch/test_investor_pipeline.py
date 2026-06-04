import os
import sys
import time
import sqlite3

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import investor
import trading_engine

def run_tests():
    print("==================================================")
    print("        INVESTOR PIPELINE INTEGRATION TEST        ")
    print("==================================================")

    # Clean cache DB table for testing if exists
    print("\n--- 1. Resetting test cache status ---")
    investor.setup_investor_db()
    conn = sqlite3.connect(investor.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM investor_trends_status WHERE ticker = ?", ("005930",))
    cursor.execute("DELETE FROM investor_trends WHERE ticker = ?", ("005930",))
    conn.commit()
    conn.close()
    print("[RESET OK] SQLite test cache cleared.")

    # 2. Test Crawling & Cache Invalidation
    print("\n--- 2. Testing Scraper and SQLite Cache Insertion ---")
    start_time = time.time()
    success = investor.fetch_and_cache_investor_trend("005930")
    duration_crawled = time.time() - start_time
    print(f"First fetch (crawled) took: {duration_crawled:.2f} seconds")
    
    assert success, "First crawl failed!"
    
    # 3. Test Cache hit (should bypass network request and return instantly)
    print("\n--- 3. Testing 4-Hour Cache Hit (Zero Network Call) ---")
    start_time = time.time()
    success_cache = investor.fetch_and_cache_investor_trend("005930")
    duration_cached = time.time() - start_time
    print(f"Second fetch (cached) took: {duration_cached:.4f} seconds")
    
    assert success_cache, "Second cached fetch failed!"
    assert duration_cached < 0.1, f"Cached fetch took too long ({duration_cached:.4f}s)! Network bypass failed."
    print("[CACHE HIT OK] Local cache bypass verified successfully!")

    # 4. Test Indicator Computation (Feature Engineering)
    print("\n--- 4. Testing Indicator Aggregations ---")
    ind = investor.get_investor_indicators("005930")
    print("Computed Indicators:")
    for k, v in ind.items():
        print(f"  - {k}: {v}")
        
    expected_keys = [
        "frgn_net_5d", "inst_net_5d", "frgn_net_10d", "inst_net_10d",
        "dual_buy_5d_count", "frgn_ratio", "frgn_trend_sig", "inst_trend_sig"
    ]
    for key in expected_keys:
        assert key in ind, f"Missing indicator key: {key}"
        
    assert isinstance(ind["frgn_ratio"], float), "frgn_ratio must be float"
    assert 0 <= ind["dual_buy_5d_count"] <= 5, "dual_buy_5d_count must be between 0 and 5"
    assert ind["frgn_trend_sig"] in ["BUY", "SELL", "HOLD"], "Invalid frgn_trend_sig value"
    print("[INDICATORS OK] Feature engineering aggregations verified!")

    # 5. Test Leading Flow Score Formula
    print("\n--- 5. Testing Leading Flow Score Formulas ---")
    # Case A: Strong SOXX, Strong currency (USD_KRW down) -> Score should be high (>= 8)
    score_high = investor.calculate_leading_flow_score(3.5, -0.9)
    print(f"Case A: SOXX +3.5%, USD/KRW -0.9% -> Score: {score_high}/10")
    assert score_high >= 8, f"Expect high score >= 8, got {score_high}"

    # Case B: Crash SOXX, Weak currency (USD_KRW up) -> Score should be low (<= 3)
    score_low = investor.calculate_leading_flow_score(-2.8, 0.7)
    print(f"Case B: SOXX -2.8%, USD/KRW +0.7% -> Score: {score_low}/10")
    assert score_low <= 3, f"Expect low score <= 3, got {score_low}"
    
    # Case C: Neutral
    score_mid = investor.calculate_leading_flow_score(0.0, 0.0)
    print(f"Case C: SOXX 0.0%, USD/KRW 0.0% -> Score: {score_mid}/10")
    assert score_mid == 5, f"Expect neutral score 5, got {score_mid}"
    
    # Bound clipping check
    assert investor.calculate_leading_flow_score(10.0, -10.0) == 10, "Score clip upper bound failed"
    assert investor.calculate_leading_flow_score(-10.0, 10.0) == 1, "Score clip lower bound failed"
    print("[SCORE OK] Leading Flow Score formula logic verified!")

    # 6. Test Trading Engine integration
    print("\n--- 6. Testing Trading Engine get_stock_indicators integration ---")
    te_ind = trading_engine.get_stock_indicators("005930")
    print(f"Trading Engine integration check for Samsung Electronics (005930):")
    print(f"  - Current Price  : {te_ind.get('current_price'):,.0f} KRW")
    print(f"  - 5d Foreign Net : {te_ind.get('frgn_net_5d'):+d} shares")
    print(f"  - 5d Inst Net    : {te_ind.get('inst_net_5d'):+d} shares")
    print(f"  - Dual Buy Days  : {te_ind.get('dual_buy_5d_count')} days")
    print(f"  - Foreign Ratio  : {te_ind.get('frgn_ratio')}%")
    
    assert te_ind.get("frgn_net_5d") is not None, "Trading Engine indicators didn't receive sugeup info!"
    print("[TRADING ENGINE OK] Integration with get_stock_indicators verified!")
    
    print("\n==================================================")
    print("      ALL TESTS PASSED SUCCESSFULLY! (100% OK)     ")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
