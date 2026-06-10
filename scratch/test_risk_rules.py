import os
import sys
import sqlite3
from datetime import datetime, timedelta

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trading_engine
from trading_engine import TradingDecision, get_kst_now

def run_tests():
    print("==================================================")
    print("RUNNING AI INVESTMENT AGENT RISK RULES TEST SUITE")
    print("==================================================")

    # Backup original functions
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
    orig_get_last_sell = trading_engine.get_last_sell_transaction

    try:
        # Stub global/common rules to return predictable states
        trading_engine.is_kospi_bear_market = lambda *args, **kwargs: False

        # ----------------------------------------------------
        # TEST CASE 1: Stop-Loss and Trailing-Stop per Mode
        # ----------------------------------------------------
        print("\n--- Test Case 1: Stop-Loss & Trailing-Stop by Mode ---")
        
        # Stub state and holdings
        # Portfolio contains:
        # - 005930 (Samsung): TECHNICAL mode, bought at 80,000, highest 85,000, current price 76,000 (drop of 10.5% from highest, stop loss is -4.5% from avg_price 80,000)
        # - 000660 (Hynix): TECHNICAL mode, bought at 200,000, highest 220,000, current price 210,000 (drop below -3.0% trailing stop but above -4.5% stop loss)
        
        trading_engine.get_agent_state = lambda: {
            "balance": 10000000.0,
            "total_asset": 24000000.0,
            "system_lock": False,
            "start_date": "2026-06-01T00:00:00"
        }
        
        # Samsung: 100 shares, Hynix: 50 shares
        portfolio_mock = {
            "005930": {
                "quantity": 100,
                "average_price": 80000.0,
                "highest_price_after_buy": 85000.0,
                "mode": "TECHNICAL",
                "last_scale_out_date": None
            },
            "000660": {
                "quantity": 50,
                "average_price": 200000.0,
                "highest_price_after_buy": 220000.0,
                "mode": "TECHNICAL",
                "last_scale_out_date": None
            }
        }
        trading_engine.get_portfolio_holdings = lambda: portfolio_mock
        
        market_prices_mock = {
            "005930": 76000.0,  # Technical SL = 80000 * 0.955 = 76400 -> Triggers Stop-Loss!
            "000660": 210000.0, # Technical TS = 220000 * 0.97 = 213400 -> Triggers Trailing-Stop!
        }
        
        def mock_get_stock_indicators(ticker):
            return {
                "current_price": market_prices_mock.get(ticker, 0.0),
                "ma_20": 80000.0,
                "disparity": 100.0,
                "daily_volume": 100000,
                "avg_volume_5d": 100000,
                "volume_ratio": 1.0,
                "volume_breakout": False,
                "daily_change_pct": 1.0,
                "market": "KOSPI"
            }
        trading_engine.get_stock_indicators = mock_get_stock_indicators
        
        trading_engine.get_latest_transactions = lambda *args, **kwargs: []
        trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": 0.0, "KOSDAQ": 0.0}
        
        # Track DB updates
        portfolio_updates = []
        def mock_update_portfolio(ticker, quantity, average_price, highest_price_after_buy=None, mode=None, last_scale_out_date=None):
            portfolio_updates.append({
                "ticker": ticker,
                "quantity": quantity,
                "average_price": average_price,
                "highest_price_after_buy": highest_price_after_buy,
                "mode": mode,
                "last_scale_out_date": last_scale_out_date
            })
            if quantity <= 0:
                if ticker in portfolio_mock: del portfolio_mock[ticker]
            else:
                if ticker not in portfolio_mock:
                    portfolio_mock[ticker] = {
                        "quantity": quantity,
                        "average_price": average_price,
                        "highest_price_after_buy": highest_price_after_buy if highest_price_after_buy else average_price,
                        "mode": mode if mode else "VALUE",
                        "last_scale_out_date": last_scale_out_date
                    }
                else:
                    portfolio_mock[ticker]["quantity"] = quantity
                    if highest_price_after_buy: portfolio_mock[ticker]["highest_price_after_buy"] = highest_price_after_buy
                    if last_scale_out_date is not None: portfolio_mock[ticker]["last_scale_out_date"] = last_scale_out_date
            return True
            
        trading_engine.update_portfolio_holding_in_db = mock_update_portfolio
        trading_engine.update_agent_state_in_db = lambda *args, **kwargs: True
        
        tx_saved = []
        def mock_save_tx(ticker, action, quantity, price, reasoning, snapshot_context=None, **kwargs):
            tx_saved.append({
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "price": price,
                "reasoning": reasoning
            })
            return True
        trading_engine.save_transaction_to_db = mock_save_tx
        trading_engine.trigger_telegram_trade_alert = lambda *args, **kwargs: None
        trading_engine.get_last_sell_transaction = lambda ticker: None

        # Execute cycle - Samsung Electronics (005930) should trigger Stop Loss and liquidate first!
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Cycle 1 action: {result['action']} on {result['ticker']} (Reason: {result['reasoning']})")
        assert result["action"] == "SELL", "Expected SELL action due to Stop-Loss"
        assert result["ticker"] == "005930", "Expected Samsung Electronics to stop-loss"
        assert result["quantity"] == 100, "Expected full quantity stopped out"
        assert "손절매" in result["reasoning"]

        # Run cycle again - Hynix (000660) should trigger Trailing Stop and partial sell 50%!
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Cycle 2 action: {result['action']} on {result['ticker']} (Reason: {result['reasoning']})")
        assert result["action"] == "SELL", "Expected partial SELL due to Trailing-Stop"
        assert result["ticker"] == "000660", "Expected SK Hynix to trailing-stop"
        assert result["quantity"] == 25, f"Expected 50% scale-out (25 shares), got {result['quantity']}"
        assert "50% 분할 매도" in result["reasoning"]
        # Verify T+0 protection was recorded
        today_str = get_kst_now().strftime("%Y-%m-%d")
        assert portfolio_mock["000660"]["last_scale_out_date"] == today_str, "Should record today's scale-out date"
        assert portfolio_mock["000660"]["highest_price_after_buy"] == 210000.0, "Should reset highest price to current price"

        # Run cycle again - Hynix (000660) should NOT trigger stop today because T+0 protection is active!
        # Set market price lower to test if trailing stop checks it
        market_prices_mock["000660"] = 200000.0 # Way below new trailing stop limit of 210000 * 0.97 = 203700, but above Stop-Loss limit of 191000
        # Mock Gemini to return HOLD
        trading_engine.generate_trading_decision = lambda *args, **kwargs: TradingDecision(
            action="HOLD", ticker="000660", allocation_pct=0.0, reasoning="T+0 보호 중 대기", mode="TECHNICAL"
        )
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Cycle 3 action: {result['action']} (Reason: {result['reasoning']})")
        assert result["action"] == "HOLD", "Expected HOLD action because T+0 trailing-stop protection is active"
        print("[SUCCESS] Stop thresholds and T+0 partial sell protection verified successfully!")

        # ----------------------------------------------------
        # TEST CASE 2: Sector Decoupling Filter
        # ----------------------------------------------------
        print("\n--- Test Case 2: Sector Decoupling Filter ---")
        # Reset Hynix state (Mode: TECHNICAL, Average 200,000, Highest 220,000)
        # Technical Trailing stop rate = -3.0% (Limit = 220000 * 0.97 = 213,400)
        # With relaxation (KOSPI +1% AND sector average > 0%): Trailing stop rate = -5.0% (Limit = 220000 * 0.95 = 209,000)
        portfolio_mock.clear()
        portfolio_mock["000660"] = {
            "quantity": 50,
            "average_price": 200000.0,
            "highest_price_after_buy": 220000.0,
            "mode": "TECHNICAL",
            "last_scale_out_date": None
        }
        market_prices_mock.clear()
        market_prices_mock["000660"] = 210000.0 # Price is 210,000, which triggers normal TS (<=213,400) but is above relaxed TS (209,000)

        # Scenario A: KOSPI up +1.2%, Sector Average up +0.5% (Relaxed TS) -> Should NOT trigger Trailing Stop!
        trading_engine.get_market_index_change = lambda *args, **kwargs: {"KOSPI": 1.2, "KOSDAQ": 0.0}
        # Hynix is in Semiconductor/IT sector. Let's make sector average change +0.5%
        # TICKER_TO_SECTOR mapping: 000660 is Semiconductor/IT
        def mock_indicators_relax(ticker):
            return {
                "current_price": 210000.0 if ticker == "000660" else 100000.0,
                "ma_20": 200000.0,
                "disparity": 100.0,
                "daily_volume": 100000,
                "avg_volume_5d": 100000,
                "volume_ratio": 1.0,
                "volume_breakout": False,
                "daily_change_pct": 0.5, # Sector member positive change
                "market": "KOSPI"
            }
        trading_engine.get_stock_indicators = mock_indicators_relax
        trading_engine.generate_trading_decision = lambda *args, **kwargs: TradingDecision(
            action="HOLD", ticker="000660", allocation_pct=0.0, reasoning="강세장 완화 유지 중", mode="TECHNICAL"
        )
        
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Decoupling Scenario A: Action={result['action']}, Ticker={result.get('ticker')}")
        assert result["action"] == "HOLD", "Expected HOLD because relaxed trailing-stop (-5%) is not breached"

        # Scenario B: KOSPI up +1.2%, but Sector Average is down -0.5% (Decoupled! Normal TS -3% applies) -> Should trigger TS!
        def mock_indicators_decouple(ticker):
            return {
                "current_price": 210000.0 if ticker == "000660" else 100000.0,
                "ma_20": 200000.0,
                "disparity": 100.0,
                "daily_volume": 100000,
                "avg_volume_5d": 100000,
                "volume_ratio": 1.0,
                "volume_breakout": False,
                "daily_change_pct": -0.5, # Sector member negative change (Decoupled!)
                "market": "KOSPI"
            }
        trading_engine.get_stock_indicators = mock_indicators_decouple
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Decoupling Scenario B: Action={result['action']}, Ticker={result.get('ticker')} (Reason: {result.get('reasoning')})")
        assert result["action"] == "SELL" and result["ticker"] == "000660", "Expected TS SELL because sector average is negative (normal -3% stop applies)"
        print("[SUCCESS] Sector Decoupling Filter verified successfully!")

        # ----------------------------------------------------
        # TEST CASE 3: Re-entry Cooldown vs Scaling-in
        # ----------------------------------------------------
        print("\n--- Test Case 3: Re-entry Cooldown vs Scaling-in ---")
        portfolio_mock.clear() # Portfolio empty
        market_prices_mock.clear()
        market_prices_mock["005930"] = 80000.0
        
        # Stub indicator fetch to return KOSPI and prices
        trading_engine.get_stock_indicators = lambda ticker: {
            "current_price": market_prices_mock.get(ticker, 80000.0),
            "ma_20": 80000.0,
            "disparity": 100.0,
            "daily_volume": 100000,
            "avg_volume_5d": 100000,
            "volume_ratio": 1.0,
            "volume_breakout": False,
            "daily_change_pct": 0.0,
            "market": "KOSPI"
        }

        # Scenario A: Re-entry check within 24h of last sell -> should block buy!
        last_sell_time_mock = (get_kst_now() - timedelta(hours=12)).isoformat()
        trading_engine.get_last_sell_transaction = lambda ticker: {
            "timestamp": last_sell_time_mock,
            "price": 82000.0,
            "action": "SELL"
        }
        
        # We pass blocked_buy_reasons to generate_decision, check if block triggers in simulation cycle
        decision_called = False
        def mock_generate_decision_cooldown(*args, **kwargs):
            nonlocal decision_called
            decision_called = True
            blocked = kwargs.get("blocked_buy_reasons", {})
            print(f"Decision call blocked reasons: {blocked}")
            assert "005930" in blocked, "Should include 005930 in blocked reasons"
            assert "24시간" in blocked["005930"]
            # Mock return BUY to see if backend rejects it
            return TradingDecision(action="BUY", ticker="005930", allocation_pct=10.0, reasoning="매수시도", mode="TECHNICAL")
            
        trading_engine.generate_trading_decision = mock_generate_decision_cooldown
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Cooldown Scenario A: Action={result['action']} (Reason: {result['reasoning']})")
        assert result["action"] == "HOLD", "Expected HOLD due to 24h cooldown"
        assert "리스크 가드레일" in result["reasoning"]

        # Scenario B: Re-entry check after 24h, but price is in whipsaw range [last_price * 0.9, last_price * 1.05] -> should block buy!
        last_sell_time_mock = (get_kst_now() - timedelta(hours=30)).isoformat()
        trading_engine.get_last_sell_transaction = lambda ticker: {
            "timestamp": last_sell_time_mock,
            "price": 81000.0, # current price 80000 is 98.7% of last price (within whipsaw range)
            "action": "SELL"
        }
        def mock_generate_decision_whipsaw(*args, **kwargs):
            blocked = kwargs.get("blocked_buy_reasons", {})
            print(f"Decision call blocked reasons: {blocked}")
            assert "005930" in blocked, "Should include 005930 in blocked reasons"
            assert "휩쏘 방지 범위" in blocked["005930"]
            return TradingDecision(action="BUY", ticker="005930", allocation_pct=10.0, reasoning="매수시도", mode="TECHNICAL")
            
        trading_engine.generate_trading_decision = mock_generate_decision_whipsaw
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Cooldown Scenario B: Action={result['action']} (Reason: {result['reasoning']})")
        assert result["action"] == "HOLD", "Expected HOLD due to whipsaw protection"

        # Scenario C: Scaling-in check. Ticker is IN portfolio -> cooldown should be bypassed!
        portfolio_mock["005930"] = {
            "quantity": 10,
            "average_price": 85000.0,
            "highest_price_after_buy": 85000.0,
            "mode": "TECHNICAL",
            "last_scale_out_date": None
        }
        market_prices_mock["005930"] = 83000.0
        # Last sell was 12 hours ago (cooldown time-wise active), but since it is in portfolio, it shouldn't block
        last_sell_time_mock = (get_kst_now() - timedelta(hours=12)).isoformat()
        trading_engine.get_last_sell_transaction = lambda ticker: {
            "timestamp": last_sell_time_mock,
            "price": 85000.0,
            "action": "TRAILING_STOP_EXIT"
        }
        
        def mock_generate_decision_scaling(*args, **kwargs):
            blocked = kwargs.get("blocked_buy_reasons", {})
            print(f"Decision call blocked reasons: {blocked}")
            assert "005930" not in blocked, "005930 should NOT be blocked from BUY since it is an active portfolio holding (scaling-in)"
            return TradingDecision(action="BUY", ticker="005930", allocation_pct=10.0, reasoning="물타기 시도", mode="TECHNICAL")
            
        trading_engine.generate_trading_decision = mock_generate_decision_scaling
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Cooldown Scenario C: Action={result['action']} (Reason: {result['reasoning']})")
        assert result["action"] == "BUY", "Expected BUY action for scaling-in"
        print("[SUCCESS] Re-entry cooldown vs Scaling-in rules verified successfully!")

        # ----------------------------------------------------
        # TEST CASE 4: Sizing Guards (10%, 30%, 50%)
        # ----------------------------------------------------
        print("\n--- Test Case 4: Sizing Guards (10% single buy, 30% stock cap, 50% sector cap) ---")
        portfolio_mock.clear()
        
        # 10,000,000 Total Asset
        # Sector weights: Semiconductor (005930 Samsung) has 40 shares * 80,000 = 3,200,000 KRW (32% of total asset)
        # Let's mock a BUY order of 000660 (SK Hynix, also Semiconductor) allocating 50% of asset
        portfolio_mock["005930"] = {
            "quantity": 40,
            "average_price": 80000.0,
            "highest_price_after_buy": 80000.0,
            "mode": "TECHNICAL",
            "last_scale_out_date": None
        }
        
        trading_engine.get_agent_state = lambda: {
            "balance": 6800000.0,
            "total_asset": 10000000.0,
            "system_lock": False,
            "start_date": "2026-06-01T00:00:00"
        }
        
        market_prices_mock.clear()
        market_prices_mock["005930"] = 80000.0
        market_prices_mock["000660"] = 200000.0
        
        trading_engine.get_stock_indicators = lambda ticker: {
            "current_price": market_prices_mock.get(ticker, 0.0),
            "ma_20": 200000.0,
            "disparity": 100.0,
            "daily_volume": 100000,
            "avg_volume_5d": 100000,
            "volume_ratio": 1.0,
            "volume_breakout": False,
            "daily_change_pct": 0.0,
            "market": "KOSPI"
        }
        trading_engine.get_last_sell_transaction = lambda ticker: None

        # Scenario A: BUY 000660 with 50% allocation (5,000,000 KRW).
        # Constraints:
        # - 10% Single order limit: max_order_cash = 10,000,000 * 0.10 = 1,000,000 KRW (capping buy size to 1,000,000 KRW, approx 5 shares)
        # - Sector limit: Semiconductor has 3,200,000. Max allowed value is 5,000,000. Max additional sector cash is 1,800,000 KRW.
        # - Sizing limit: Ticker is 000660, owned value is 0. Max new cash is 3,000,000.
        # Combined minimum cash constraint is 1,000,000 KRW (10% single buy limit).
        # Quantity should be capped at int(1,000,000 / (200,000 * 1.001)) = 4 shares. (Cost = 800,000 KRW. 5 shares is 1,000,500 KRW, exceeding 1,000,000 limit)
        trading_engine.generate_trading_decision = lambda *args, **kwargs: TradingDecision(
            action="BUY", ticker="000660", allocation_pct=50.0, reasoning="하이닉스 신규 매수 시도", mode="VALUE"
        )
        
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Sizing Scenario A: Action={result['action']}, Ticker={result['ticker']}, Qty={result['quantity']}, Reasoning={result['reasoning']}")
        assert result["action"] == "BUY"
        assert result["quantity"] == 4, f"Expected capped quantity 4 due to 10% single order limit, got {result['quantity']}"
        assert "1회 주문 10% 제한" in result["reasoning"]

        # Scenario B: Try to buy 005930 when owned value is already 32% (> 30% stock cap) -> should block buy in pre-flight!
        portfolio_mock["005930"]["quantity"] = 45
        def mock_generate_decision_stock_cap(*args, **kwargs):
            blocked = kwargs.get("blocked_buy_reasons", {})
            print(f"Decision call blocked reasons: {blocked}")
            assert "005930" in blocked, "005930 should be blocked because its portfolio weight is 32% (exceeding 30% cap)"
            return TradingDecision(action="BUY", ticker="005930", allocation_pct=10.0, reasoning="삼성 추가 매수", mode="VALUE")

        trading_engine.generate_trading_decision = mock_generate_decision_stock_cap
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Sizing Scenario B: Action={result['action']} (Reason: {result['reasoning']})")
        assert result["action"] == "HOLD"
        assert "개별 종목 한계치" in result["reasoning"]

        # Scenario C: Try to buy 000660 when Semiconductor sector is already 52% (> 50% sector cap) -> should block buy in pre-flight!
        portfolio_mock["005930"]["quantity"] = 85 
        def mock_generate_decision_sector_cap(*args, **kwargs):
            blocked = kwargs.get("blocked_buy_reasons", {})
            print(f"Decision call blocked reasons: {blocked}")
            assert "000660" in blocked, "000660 should be blocked because Semiconductor sector weight is 52% (exceeding 50% cap)"
            return TradingDecision(action="BUY", ticker="000660", allocation_pct=10.0, reasoning="하이닉스 추가 매수", mode="VALUE")

        trading_engine.generate_trading_decision = mock_generate_decision_sector_cap
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Sizing Scenario C: Action={result['action']} (Reason: {result['reasoning']})")
        assert result["action"] == "HOLD"
        assert "한계치(50%)를 초과" in result["reasoning"]
        print("[SUCCESS] Sizing guards (10% single buy, 30% stock cap, 50% sector cap) verified successfully!")

        # ----------------------------------------------------
        # TEST CASE 5: Gemini Skip Optimization
        # ----------------------------------------------------
        print("\n--- Test Case 5: Gemini Skip Optimization ---")
        portfolio_mock.clear() # Empty portfolio
        
        # Candidate 005930 has a recent 24h sell cooldown, Candidate 000660 has a recent 24h sell cooldown
        # Empty portfolio, all candidates blocked -> Gemini should NOT be called at all!
        trading_engine.generate_trading_decision = lambda *args, **kwargs: ValueError("Gemini API should NOT be called!")
        
        trading_engine.get_last_sell_transaction = lambda ticker: {
            "timestamp": (get_kst_now() - timedelta(hours=12)).isoformat(),
            "price": 80000.0 if ticker == "005930" else 200000.0,
            "action": "SELL"
        }
        
        # Run simulation cycle. If Gemini is called, it will raise ValueError and fail the test.
        # It should skip Gemini and return HOLD decision.
        result = trading_engine.run_simulation_cycle(bypass_hours=True)
        print(f"Skip Optimization Result: Action={result['action']}, Reasoning={result['reasoning']}")
        assert result["action"] == "HOLD", "Expected HOLD action"
        assert "API 호출 최적화" in result["reasoning"], "Should contain skip optimization warning"
        print("[SUCCESS] Gemini Skip Optimization verified successfully!")

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
        trading_engine.get_last_sell_transaction = orig_get_last_sell

    print("\n==================================================")
    print("ALL TEST CASES PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
