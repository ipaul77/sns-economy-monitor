import os
import sys
import unittest
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_engine import evaluate_macro_circuit_breaker, _evaluate_buy_guardrails

class TestFeedbackImprovements(unittest.TestCase):
    def test_evaluate_macro_circuit_breaker_rebound(self):
        # Disparity is low (e.g. 96.0), but daily change is positive (+0.8%) and RSI > 30
        state = evaluate_macro_circuit_breaker(
            kospi_disparity=96.0,
            kospi_daily_change=0.8,
            kospi_rsi=42.0
        )
        self.assertEqual(state, "REBOUND_ALLOWED")

    def test_whipsaw_noise_zone_blocked(self):
        monitored_tickers = ["005930"]
        portfolio = {}
        balance = 10000000.0
        market_prices = {"005930": 70000.0}
        market_indicators = {"005930": {"rsi": 45.0, "market": "KOSPI"}}
        index_changes = {"KOSPI": 0.0}
        news_context = []
        now = datetime.now()

        blocked = _evaluate_buy_guardrails(
            monitored_tickers, portfolio, balance, market_prices, market_indicators,
            index_changes, 1350.0, 0.0, 100.0, 100.0, 100.0, False, {}, news_context, now,
            macro_state="NORMAL"
        )
        self.assertIn("005930", blocked)
        self.assertIn("WHIPSAW", blocked["005930"])

    def test_pyramiding_price_distance_blocked(self):
        monitored_tickers = ["005930"]
        portfolio = {"005930": {"quantity": 10, "average_price": 70000.0}}
        balance = 9300000.0
        # Price moved only +1.0% (to 70700), less than 3% required
        market_prices = {"005930": 70700.0}
        market_indicators = {"005930": {"rsi": 60.0, "market": "KOSPI"}}
        index_changes = {"KOSPI": 0.0}
        news_context = []
        now = datetime.now()

        blocked = _evaluate_buy_guardrails(
            monitored_tickers, portfolio, balance, market_prices, market_indicators,
            index_changes, 1350.0, 0.0, 100.0, 100.0, 100.0, False, {}, news_context, now,
            macro_state="NORMAL"
        )
        self.assertIn("005930", blocked)
        self.assertIn("추가매수 이격 미달", blocked["005930"])

if __name__ == "__main__":
    unittest.main()
