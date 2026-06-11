import os
import sys
from unittest.mock import patch, MagicMock

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trading_engine

def run_red_light_tests():
    print("==================================================")
    print("       TESTING PYTHON-SIDE RED LIGHT PRE-FILTERS  ")
    print("==================================================")

    # Mock DB states
    mock_state = {
        "balance": 5000000.0,
        "total_asset": 5000000.0,
        "system_lock": False,
        "start_date": "2026-06-01T00:00:00"
    }

    mock_portfolio = {} # Empty portfolio

    mock_news = [] # Empty news

    # Mock market indicators for candidate tickers
    # Candidates are returned by get_active_tickers
    mock_candidates = ["005930"] # Samsung Electronics

    mock_indicators = {
        "005930": {
            "current_price": 75000.0,
            "ma_20": 78000.0,
            "disparity": 96.1,
            "daily_volume": 1000000,
            "avg_volume_5d": 1500000,
            "volume_ratio": 0.67,
            "volume_breakout": False,
            "market": "KOSPI",
            "frgn_net_5d": 0,
            "inst_net_5d": 0,
            "avg_volume_5d": 1500000
        }
    }

    # 1. Test Case: USD_KRW crash (Exchange rate > 1400 and surging)
    print("\n--- TEST 1: Exchange Rate Red Light (USD/KRW >= 1400, surging) ---")
    mock_index_changes = {"KOSPI": 0.0, "KOSDAQ": 0.0}
    mock_market_indicators_global = {
        "USD_KRW": {"price": 1415.0, "percent": 1.2} # Surging by 1.2%
    }

    import pandas as pd
    mock_history = pd.DataFrame({"Close": [1350.0] * 20})

    with patch('trading_engine.get_agent_state', return_value=mock_state), \
         patch('trading_engine.get_portfolio_holdings', return_value=mock_portfolio), \
         patch('trading_engine.get_active_tickers', return_value=mock_candidates), \
         patch('trading_engine.get_market_index_change', return_value=mock_index_changes), \
         patch('market.get_market_indicators', return_value=mock_market_indicators_global), \
         patch('trading_engine.get_stock_indicators', return_value=mock_indicators["005930"]), \
         patch('trading_engine.update_agent_state_in_db', return_value=True), \
         patch('trading_engine.save_transaction_to_db', return_value=True), \
         patch('trading_engine.update_portfolio_holding_in_db', return_value=True), \
         patch('trading_engine.trigger_telegram_trade_alert', return_value=None), \
         patch('yfinance.Ticker') as mock_ticker_class:
        
        # Setup yfinance mocks
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = mock_history
        mock_ticker_class.return_value = mock_ticker_inst

        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Result Action: {result.get('action')}")
        print(f"Result Reasoning: {result.get('reasoning')}")
        
        # Verify that it returned HOLD with [Python 시스템 차단: 매크로 불안] in blocked reasons
        # Wait, run_simulation_cycle returns a dict with status/action/reasoning if executed stop-loss/trailing-stop,
        # or it calls generate_trading_decision and returns order updates. Let's see if it skipped Gemini call.
        # Since portfolio is empty and all candidate tickers are blocked, it should skip Gemini call and return a HOLD.
        assert "HOLD" == result.get("action")
        assert "[Python 시스템 차단]" in result.get("reasoning")
        print("[SUCCESS] Exchange Rate Red Light correctly triggered pre-filtering bypass!")

    # 2. Test Case: KOSPI Index crash (daily change <= -1.5%)
    print("\n--- TEST 2: KOSPI Crash Red Light (KOSPI Daily change <= -1.5%) ---")
    mock_index_changes = {"KOSPI": -2.3, "KOSDAQ": 0.0}
    mock_market_indicators_global = {
        "USD_KRW": {"price": 1350.0, "percent": 0.0}
    }

    with patch('trading_engine.get_agent_state', return_value=mock_state), \
         patch('trading_engine.get_portfolio_holdings', return_value=mock_portfolio), \
         patch('trading_engine.get_active_tickers', return_value=mock_candidates), \
         patch('trading_engine.get_market_index_change', return_value=mock_index_changes), \
         patch('market.get_market_indicators', return_value=mock_market_indicators_global), \
         patch('trading_engine.get_stock_indicators', return_value=mock_indicators["005930"]), \
         patch('trading_engine.update_agent_state_in_db', return_value=True), \
         patch('trading_engine.save_transaction_to_db', return_value=True), \
         patch('trading_engine.update_portfolio_holding_in_db', return_value=True), \
         patch('trading_engine.trigger_telegram_trade_alert', return_value=None), \
         patch('yfinance.Ticker') as mock_ticker_class:
        
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = mock_history
        mock_ticker_class.return_value = mock_ticker_inst

        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Result Action: {result.get('action')}")
        print(f"Result Reasoning: {result.get('reasoning')}")
        
        assert "HOLD" == result.get("action")
        assert "[Python 시스템 차단]" in result.get("reasoning")
        print("[SUCCESS] KOSPI Crash Red Light correctly triggered pre-filtering bypass!")

    # 3. Test Case: Ticker Falling Blade (price < 20MA and volume_ratio < 1.0)
    print("\n--- TEST 3: Falling Blade Red Light (Price < 20MA and volume_ratio < 1.0) ---")
    mock_index_changes = {"KOSPI": 0.5, "KOSDAQ": 0.5}
    mock_market_indicators_global = {
        "USD_KRW": {"price": 1350.0, "percent": 0.0}
    }
    # Ticker 005930 indicators: ma_20 = 78000, current_price = 75000, volume_ratio = 0.67 (Falling Blade!)
    with patch('trading_engine.get_agent_state', return_value=mock_state), \
         patch('trading_engine.get_portfolio_holdings', return_value=mock_portfolio), \
         patch('trading_engine.get_active_tickers', return_value=mock_candidates), \
         patch('trading_engine.get_market_index_change', return_value=mock_index_changes), \
         patch('market.get_market_indicators', return_value=mock_market_indicators_global), \
         patch('trading_engine.get_stock_indicators', return_value=mock_indicators["005930"]), \
         patch('trading_engine.update_agent_state_in_db', return_value=True), \
         patch('trading_engine.save_transaction_to_db', return_value=True), \
         patch('trading_engine.update_portfolio_holding_in_db', return_value=True), \
         patch('trading_engine.trigger_telegram_trade_alert', return_value=None), \
         patch('yfinance.Ticker') as mock_ticker_class:
        
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = mock_history
        mock_ticker_class.return_value = mock_ticker_inst

        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Result Action: {result.get('action')}")
        print(f"Result Reasoning: {result.get('reasoning')}")
        
        assert "HOLD" == result.get("action")
        assert "[Python 시스템 차단]" in result.get("reasoning")
        print("[SUCCESS] Falling Blade Red Light correctly triggered pre-filtering bypass!")

    print("\n==================================================")
    print("      ALL RED LIGHT PRE-FILTER TESTS PASSED!      ")
    print("==================================================")

if __name__ == "__main__":
    run_red_light_tests()
