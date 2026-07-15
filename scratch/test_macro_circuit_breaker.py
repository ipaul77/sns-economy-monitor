import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trading_engine
import db
db.USE_FIREBASE = False
trading_engine.db.USE_FIREBASE = False
from trading_engine import TradingDecision, get_kst_now

class TestMacroCircuitBreaker(unittest.TestCase):
    def setUp(self):
        # Backup original functions
        self.orig_get_agent_state = trading_engine.get_agent_state
        self.orig_get_portfolio_holdings = trading_engine.get_portfolio_holdings
        self.orig_get_stock_indicators = trading_engine.get_stock_indicators
        self.orig_generate_decision = trading_engine.generate_trading_decision
        self.orig_get_latest_transactions = trading_engine.get_latest_transactions
        self.orig_get_market_index_change = trading_engine.get_market_index_change
        self.orig_update_state = trading_engine.update_agent_state_in_db
        self.orig_update_holding = trading_engine.update_portfolio_holding_in_db
        self.orig_save_tx = trading_engine.save_transaction_to_db
        self.orig_telegram = trading_engine.trigger_telegram_trade_alert
        self.orig_bear = trading_engine.is_kospi_bear_market
        self.orig_yfinance_ticker = trading_engine.yf.Ticker

        # Mock general environment
        trading_engine.trigger_telegram_trade_alert = lambda *args, **kwargs: None
        trading_engine.update_agent_state_in_db = lambda *args, **kwargs: True
        trading_engine.update_portfolio_holding_in_db = lambda *args, **kwargs: True
        trading_engine.get_latest_transactions = lambda *args, **kwargs: []

        # Start market indicator patch
        self.patcher_market = patch('market.get_market_indicators', return_value={"USD_KRW": {"price": 1350.0, "percent": 0.0}})
        self.mock_get_market = self.patcher_market.start()

    def tearDown(self):
        # Stop market indicator patch
        self.patcher_market.stop()

        # Restore original functions
        trading_engine.get_agent_state = self.orig_get_agent_state
        trading_engine.get_portfolio_holdings = self.orig_get_portfolio_holdings
        trading_engine.get_stock_indicators = self.orig_get_stock_indicators
        trading_engine.generate_trading_decision = self.orig_generate_decision
        trading_engine.get_latest_transactions = self.orig_get_latest_transactions
        trading_engine.get_market_index_change = self.orig_get_market_index_change
        trading_engine.update_agent_state_in_db = self.orig_update_state
        trading_engine.update_portfolio_holding_in_db = self.orig_update_holding
        trading_engine.save_transaction_to_db = self.orig_save_tx
        trading_engine.trigger_telegram_trade_alert = self.orig_telegram
        trading_engine.is_kospi_bear_market = self.orig_bear
        trading_engine.yf.Ticker = self.orig_yfinance_ticker

    @patch('trading_engine.yf.Ticker')
    def test_system_crash_lockdown(self, mock_yf_ticker):
        print("\n=== Test case: SYSTEM_CRASH_LOCKDOWN ===")
        # Setup market indicators: KOSPI crashes by -5.0%
        trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": -5.0, "KOSDAQ": 0.0}
        
        # Setup yfinance mock to return a low disparity (e.g. 85%)
        mock_kospi = MagicMock()
        import pandas as pd
        mock_kospi.history.return_value = pd.DataFrame({"Close": [100.0] * 19 + [85.0]}) # Mean will be around 99.25, last close is 85 -> disparity = 85.6%
        
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = pd.DataFrame({"Close": [1350.0] * 20})
        
        def ticker_side_effect(symbol):
            if symbol == "^KS11":
                return mock_kospi
            return mock_ticker_inst
        mock_yf_ticker.side_effect = ticker_side_effect

        # Setup holdings
        trading_engine.get_agent_state = lambda: {
            "balance": 2000000.0,
            "total_asset": 10000000.0,
            "system_lock": False
        }
        portfolio_mock = {
            "005930": {"quantity": 100, "average_price": 80000.0, "highest_price_after_buy": 80000.0}
        }
        trading_engine.get_portfolio_holdings = lambda: portfolio_mock

        # Mock stock price & indicators
        trading_engine.get_stock_indicators = lambda ticker: {
            "current_price": 80000.0,
            "market": "KOSPI",
            "disparity": 100.0,
            "daily_volume": 100000,
            "avg_volume_5d": 100000,
            "volume_ratio": 1.0
        }

        # Track DB updates
        liquidated = []
        def mock_update_holding(ticker, quantity, avg_price, highest_price_after_buy=None, mode=None, last_scale_out_date=None):
            if quantity == 0:
                liquidated.append(ticker)
            return True
        trading_engine.update_portfolio_holding_in_db = mock_update_holding

        # Run cycle
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print("Result Action:", result.get("action"))
        print("Message:", result.get("message"))
        
        self.assertEqual(result.get("action"), "SYSTEMIC_LIQUIDATION")
        self.assertIn("005930", liquidated)

    @patch('trading_engine.yf.Ticker')
    def test_hard_no_buy_with_minor_position_liquidation(self, mock_yf_ticker):
        print("\n=== Test case: HARD_NO_BUY with Minor Position Liquidation ===")
        # Setup KOSPI drops by -3.5%
        trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": -3.5, "KOSDAQ": 0.0}
        
        # Setup yfinance mock to return a low disparity (e.g. 91%)
        mock_kospi = MagicMock()
        import pandas as pd
        mock_kospi.history.return_value = pd.DataFrame({"Close": [100.0] * 19 + [91.0]})
        
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = pd.DataFrame({"Close": [1350.0] * 20})
        
        def ticker_side_effect(symbol):
            if symbol == "^KS11":
                return mock_kospi
            return mock_ticker_inst
        mock_yf_ticker.side_effect = ticker_side_effect

        # Setup holdings:
        # Total Asset = 10,000,000 KRW
        # Samsung: 100 shares * 80,000 KRW = 8,000,000 KRW (80% weight) -> should NOT liquidate
        # Hynix: 2 shares * 200,000 KRW = 400,000 KRW (4% weight) -> minor position (< 5%) -> should liquidate!
        trading_engine.get_agent_state = lambda: {
            "balance": 1600000.0,
            "total_asset": 10000000.0,
            "system_lock": False
        }
        portfolio_mock = {
            "005930": {"quantity": 100, "average_price": 80000.0, "highest_price_after_buy": 80000.0},
            "000660": {"quantity": 2, "average_price": 200000.0, "highest_price_after_buy": 200000.0}
        }
        trading_engine.get_portfolio_holdings = lambda: portfolio_mock

        # Mock stock price & indicators
        def mock_get_stock_indicators(ticker):
            price = 80000.0 if ticker == "005930" else 200000.0
            return {
                "current_price": price,
                "market": "KOSPI",
                "disparity": 100.0,
                "daily_volume": 100000,
                "avg_volume_5d": 100000,
                "volume_ratio": 1.0
            }
        trading_engine.get_stock_indicators = mock_get_stock_indicators

        # Track DB updates
        liquidated = []
        def mock_update_holding(ticker, quantity, avg_price, highest_price_after_buy=None, mode=None, last_scale_out_date=None):
            if quantity == 0:
                liquidated.append(ticker)
            return True
        trading_engine.update_portfolio_holding_in_db = mock_update_holding

        # Run cycle
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print("Result Action:", result.get("action"))
        print("Message:", result.get("message"))
        
        self.assertEqual(result.get("action"), "MINOR_POSITION_LIQUIDATION")
        self.assertIn("000660", liquidated)
        self.assertNotIn("005930", liquidated)

    @patch('trading_engine.yf.Ticker')
    def test_hard_no_buy_forces_hold_decision(self, mock_yf_ticker):
        print("\n=== Test case: HARD_NO_BUY forces HOLD decision ===")
        # Setup KOSPI drops by -3.5%
        trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": -3.5, "KOSDAQ": 0.0}
        
        # Setup yfinance mock to return a low disparity (e.g. 91%)
        mock_kospi = MagicMock()
        import pandas as pd
        mock_kospi.history.return_value = pd.DataFrame({"Close": [100.0] * 19 + [91.0]})
        
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = pd.DataFrame({"Close": [1350.0] * 20})
        
        def ticker_side_effect(symbol):
            if symbol == "^KS11":
                return mock_kospi
            return mock_ticker_inst
        mock_yf_ticker.side_effect = ticker_side_effect

        # Setup holdings: empty portfolio
        trading_engine.get_agent_state = lambda: {
            "balance": 10000000.0,
            "total_asset": 10000000.0,
            "system_lock": False
        }
        portfolio_mock = {}
        trading_engine.get_portfolio_holdings = lambda: portfolio_mock

        # Mock stock price & indicators
        trading_engine.get_stock_indicators = lambda ticker: {
            "current_price": 80000.0,
            "market": "KOSPI",
            "disparity": 100.0,
            "daily_volume": 100000,
            "avg_volume_5d": 100000,
            "volume_ratio": 1.0
        }

        # Verify that Gemini generate_trading_decision is NOT called
        gemini_called = False
        def mock_generate_decision(*args, **kwargs):
            nonlocal gemini_called
            gemini_called = True
            return TradingDecision(action="BUY", ticker="005930", win_probability=0.8, reward_to_risk_ratio=2.0, allocation_pct=50.0, reasoning="test")
        trading_engine.generate_trading_decision = mock_generate_decision

        # Run cycle
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print("Result Action:", result.get("action"))
        print("Reasoning:", result.get("reasoning"))
        
        self.assertEqual(result.get("action"), "HOLD")
        self.assertFalse(gemini_called, "Gemini API call should have been skipped!")
        self.assertIn("[Python 시스템 차단: HARD_NO_BUY]", result.get("reasoning"))

    @patch('trading_engine.yf.Ticker')
    def test_guardrails_multipliers(self, mock_yf_ticker):
        print("\n=== Test case: Guardrail 2 & 3 multiplier updates ===")
        # Normal market index change
        trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": 0.0, "KOSDAQ": 0.0}
        
        # Setup yfinance mock to return a normal disparity (e.g. 100%)
        mock_kospi = MagicMock()
        import pandas as pd
        mock_kospi.history.return_value = pd.DataFrame({"Close": [100.0] * 20})
        
        mock_ticker_inst = MagicMock()
        mock_ticker_inst.history.return_value = pd.DataFrame({"Close": [1350.0] * 20})
        
        def ticker_side_effect(symbol):
            if symbol == "^KS11":
                return mock_kospi
            return mock_ticker_inst
        mock_yf_ticker.side_effect = ticker_side_effect

        # Empty portfolio, but we want to simulate a BUY decision
        trading_engine.get_agent_state = lambda: {
            "balance": 10000000.0,
            "total_asset": 10000000.0,
            "system_lock": False
        }
        portfolio_mock = {}
        trading_engine.get_portfolio_holdings = lambda: portfolio_mock

        # Setup bear market to trigger Guardrail 2
        trading_engine.is_kospi_bear_market = lambda *args, **kwargs: True

        # Mock stock price & indicators
        trading_engine.get_stock_indicators = lambda ticker: {
            "current_price": 80000.0,
            "market": "KOSPI",
            "disparity": 110.0, # Triggers Guardrail 3 (disparity 108%-115%)
            "daily_volume": 100000,
            "avg_volume_5d": 100000,
            "volume_ratio": 1.0
        }

        # Mock Gemini Decision to BUY 005930
        decision_mock = TradingDecision(
            action="BUY",
            ticker="005930",
            allocation_pct=100.0, # 10,000,000 allocated cash
            win_probability=0.75,
            reward_to_risk_ratio=3.0,
            reasoning="test",
            mode="TECHNICAL"
        )
        trading_engine.generate_trading_decision = lambda *args, **kwargs: decision_mock

        # Capture spend_cash in a wrapper or check result purchase amount
        # Let's patch update_agent_state_in_db to see the final balance.
        saved_balance = 0
        def mock_update_state(balance_val, total_asset_val, system_lock=False):
            nonlocal saved_balance
            saved_balance = balance_val
            return True
        trading_engine.update_agent_state_in_db = mock_update_state

        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print("Result Action:", result.get("action"))
        print("Quantity bought:", result.get("quantity"))
        
        # Sizing verification:
        # Allocated = 10,000,000 * half_kelly
        # expectation = 0.75 - 0.25 / 3.0 = 0.666
        # half_kelly = 0.5 * 0.666 = 0.333
        # Allocated cash = 3,333,333 KRW
        # Max order cash = total_asset * 0.1 = 1,000,000 KRW
        # Max new cash = total_asset * 0.15 (since bear regime is active) = 1,500,000 KRW
        # min(Allocated, Max order, Max new) = 1,000,000 KRW
        # Now apply Guardrail 2 (bear market): spend_cash *= 0.3 -> 300,000 KRW
        # Now apply Guardrail 3 (disparity 110): spend_cash *= 0.3 -> 90,000 KRW
        # 90,000 KRW / (80,000 * 1.001) = 1 share.
        self.assertEqual(result.get("action"), "BUY")
        self.assertEqual(result.get("quantity"), 1)

if __name__ == "__main__":
    unittest.main()
