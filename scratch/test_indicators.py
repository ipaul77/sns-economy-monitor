import os
import sys

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trading_engine

def run_indicators_test():
    print("==================================================")
    print("       INDICATORS TEST: yfinance METRICS FETCH     ")
    print("==================================================")
    
    # 1. Test Market Index Changes
    print("\n--- 1. Fetching KOSPI & KOSDAQ Daily Returns ---")
    index_changes = trading_engine.get_market_index_change()
    print(f"Market Indices daily changes:")
    for name, val in index_changes.items():
        print(f"  - {name}: {val:+.2f}%")
    
    # KOSPI / KOSDAQ keys must exist
    assert "KOSPI" in index_changes, "KOSPI key missing!"
    assert "KOSDAQ" in index_changes, "KOSDAQ key missing!"
    print("[SUCCESS] Market indices daily changes parsed successfully!")
    
    # 2. Test Stock-level Technical Indicators
    test_tickers = ["005930", "000660"]  # Samsung Electronics, SK Hynix
    print("\n--- 2. Fetching Stock-level Indicators (20 MA, Disparity, Volume 5d) ---")
    
    for ticker in test_tickers:
        print(f"\nEvaluating ticker {ticker}:")
        ind = trading_engine.get_stock_indicators(ticker)
        
        print(f"  - Current Price: {ind['current_price']:,.0f} KRW")
        print(f"  - 20-day MA    : {ind['ma_20']:,.1f} KRW")
        print(f"  - Disparity Idx: {ind['disparity']}%")
        print(f"  - Daily Volume : {ind['daily_volume']:,} shares")
        print(f"  - 5-day Avg Vol: {ind['avg_volume_5d']:,.1f} shares")
        print(f"  - Volume Ratio : {ind['volume_ratio']}x (Breakout: {ind['volume_breakout']})")
        
        assert ind['current_price'] > 0, f"Current price for {ticker} should be > 0"
        assert ind['ma_20'] > 0, f"ma_20 for {ticker} should be > 0"
        assert 50.0 <= ind['disparity'] <= 200.0, f"Disparity for {ticker} is outlier: {ind['disparity']}%"
        assert ind['daily_volume'] >= 0, f"Volume should be >= 0"
        
    print("\n[SUCCESS] Indicators 유닛 테스트가 성공적으로 완수되었습니다!")
    print("==================================================")

if __name__ == "__main__":
    run_indicators_test()
