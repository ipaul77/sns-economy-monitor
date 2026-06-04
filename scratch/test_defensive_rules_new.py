import os
import sys
import sqlite3
from datetime import datetime

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import investor
import trading_engine
from trading_engine import TradingDecision

def test_dynamic_fallback_price():
    print("\n--- Test Case 1: Dynamic DB Fallback Price ---")
    
    # 1. Setup mock database records in SQLite investor_trends
    investor.setup_investor_db()
    conn = sqlite3.connect(investor.DB_PATH)
    cursor = conn.cursor()
    
    # Clean previous test values
    cursor.execute("DELETE FROM investor_trends WHERE ticker = ?", ("999999",))
    cursor.execute("DELETE FROM investor_trends WHERE ticker = ?", ("035720",))
    
    # Insert custom price for a mock ticker "999999"
    test_price = 123456
    cursor.execute("""
        INSERT INTO investor_trends (ticker, date, close_price, inst_net_vol, frgn_net_vol, frgn_ratio)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("999999", "2026-06-04", test_price, 100, 100, 1.5))
    
    conn.commit()
    conn.close()
    
    # 2. Query price using investor.get_latest_cached_price
    cached_price = investor.get_latest_cached_price("999999")
    print(f"Injected price: {test_price}, Retrieved cached price: {cached_price}")
    assert cached_price == test_price, f"Expected {test_price}, got {cached_price}"
    
    # 3. Query non-existent ticker to check fallback dictionary / default values
    fallback_price = investor.get_latest_cached_price("035720")
    print(f"Fallback price for 035720 (Kakao): {fallback_price}")
    assert fallback_price == 48500.0, f"Expected 48500.0, got {fallback_price}"
    
    print("[SUCCESS] Dynamic DB Fallback Price test passed!")

def test_sector_concentration_cap():
    print("\n--- Test Case 2: Sector Concentration Limit (45%) ---")
    
    # Save original functions to restore later
    orig_get_agent_state = trading_engine.get_agent_state
    orig_get_portfolio_holdings = trading_engine.get_portfolio_holdings
    orig_get_stock_indicators = trading_engine.get_stock_indicators
    orig_generate_decision = trading_engine.generate_trading_decision
    orig_get_latest_transactions = trading_engine.get_latest_transactions
    orig_get_market_index_change = trading_engine.get_market_index_change
    orig_update_state = trading_engine.update_agent_state_in_db
    orig_update_holding = trading_engine.update_portfolio_holding_in_db
    orig_save_tx = trading_engine.save_transaction_to_db
    orig_telegram = trading_engine.trigger_telegram_trade_alert
    orig_bear = trading_engine.is_kospi_bear_market

    # Stub state and portfolio
    # Total Asset = 10,000,000 KRW
    # 45% Limit = 4,500,000 KRW
    # Current owned Semiconductor/IT (005930) = 50 shares * 80,000 KRW = 4,000,000 KRW (40% of total assets)
    # Remaining sector allowance: 500,000 KRW
    trading_engine.get_agent_state = lambda: {
        "balance": 6000000.0,
        "total_asset": 10000000.0,
        "system_lock": False,
        "start_date": "2026-06-01T00:00:00"
    }
    
    trading_engine.get_portfolio_holdings = lambda: {
        "005930": {
            "quantity": 50,
            "average_price": 80000.0,
            "highest_price_after_buy": 80000.0
        }
    }
    
    # Stub stock indicators/prices
    def mock_get_stock_indicators(ticker):
        price = 80000.0 if ticker == "005930" else 200000.0 # 000660 SK Hynix
        return {
            "current_price": price,
            "ma_20": price,
            "disparity": 100.0,
            "daily_volume": 100000,
            "avg_volume_5d": 100000,
            "volume_ratio": 1.0,
            "volume_breakout": False,
            "market": "KOSPI"
        }
    trading_engine.get_stock_indicators = mock_get_stock_indicators
    
    # Stub trading decision: BUY "000660" (also Semiconductor/IT) allocating 50% of balance (3,000,000 KRW)
    trading_engine.generate_trading_decision = lambda *args, **kwargs: TradingDecision(
        action="BUY",
        ticker="000660",
        allocation_pct=50.0,
        reasoning="반도체 업황 개선 기대에 따른 SK하이닉스 추가 매수."
    )
    
    # Bypass DB modifications & network tasks
    trading_engine.get_latest_transactions = lambda *args, **kwargs: []
    trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": 0.0, "KOSDAQ": 0.0}
    trading_engine.update_agent_state_in_db = lambda *args, **kwargs: True
    trading_engine.update_portfolio_holding_in_db = lambda *args, **kwargs: True
    
    tx_logged = []
    def mock_save_tx(ticker, action, quantity, price, reasoning, snapshot_context):
        tx_logged.append({
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "price": price,
            "reasoning": reasoning
        })
        return True
    trading_engine.save_transaction_to_db = mock_save_tx
    
    trading_engine.trigger_telegram_trade_alert = lambda *args, **kwargs: None
    trading_engine.is_kospi_bear_market = lambda *args, **kwargs: False

    try:
        # Run simulation cycle (bypass_hours=True to force execution)
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        
        print("\n--- Simulation Result ---")
        print(f"Action   : {result.get('action')}")
        print(f"Ticker   : {result.get('ticker')}")
        print(f"Quantity : {result.get('quantity')}")
        print(f"Price    : {result.get('price'):,.0f} KRW" if result.get("price") else "")
        print(f"Reasoning: {result.get('reasoning')}")
        
        # Validation checks
        assert result.get("action") == "BUY", "Expected BUY action"
        assert result.get("ticker") == "000660", "Expected BUY ticker 000660"
        
        # Capping validation:
        # Remaining allowance: 500,000 KRW.
        # SK Hynix price = 200,000 KRW. Transaction fee rate = 0.001.
        # Max quantity: int(500,000 / (200,000 * 1.001)) = 2 shares.
        # Cost: 2 * 200,000 = 400,000 KRW (under 500,000 KRW).
        # (3 shares would be 600,000 KRW, exceeding 500,000 KRW).
        # So quantity MUST be 2.
        assert result.get("quantity") == 2, f"Expected quantity to be capped at 2, got {result.get('quantity')}"
        assert "섹터 비중 45% 제한" in result.get("reasoning"), "Reasoning should contain Sector Concentration Limit warning"
        
        print("[SUCCESS] Sector Concentration Cap (45%) test passed!")
        
    finally:
        # Restore original functions
        trading_engine.get_agent_state = orig_get_agent_state
        trading_engine.get_portfolio_holdings = orig_get_portfolio_holdings
        trading_engine.get_stock_indicators = orig_get_stock_indicators
        trading_engine.generate_trading_decision = orig_generate_decision
        trading_engine.get_latest_transactions = orig_get_latest_transactions
        trading_engine.get_market_index_change = orig_get_market_index_change
        trading_engine.update_agent_state_in_db = orig_update_state
        trading_engine.update_portfolio_holding_in_db = orig_update_holding
        trading_engine.save_transaction_to_db = orig_save_tx
        trading_engine.trigger_telegram_trade_alert = orig_telegram
        trading_engine.is_kospi_bear_market = orig_bear

if __name__ == "__main__":
    test_dynamic_fallback_price()
    test_sector_concentration_cap()
    print("\nAll defensive rules tests passed successfully!")
