import os
import sys

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trading_engine
import db
db.USE_FIREBASE = False
trading_engine.db.USE_FIREBASE = False

def run_defensive_rules_test():
    print("==================================================")
    print("    DEFENSIVE RULES TEST: STOP-LOSS / TRAILING    ")
    print("==================================================")
    
    # Pre-test cleanup: delete potential test portfolio document
    trading_engine.update_portfolio_holding_in_db("005930", 0, 0.0)
    
    # 1. Setup Virtual Portfolio for Stop-Loss test
    # Buy Samsung Electronics (005930) at 340,000 KRW (higher than current ~317,000 KRW)
    # Stop-Loss threshold: 340,000 * 0.955 = 324,700 KRW.
    # Current price (~317,000 KRW) is <= 324,700 KRW, so Stop-Loss MUST trigger!
    print("\n[Step 1] Injecting virtual test holding (Stop-Loss target):")
    print("  - Ticker: 005930 (Samsung Electronics)")
    print("  - Qty: 10 shares")
    print("  - Average Buy Price: 340,000 KRW")
    print("  - Highest Price: 340,000 KRW")
    
    success = trading_engine.update_portfolio_holding_in_db(
        ticker="005930",
        quantity=10,
        average_price=340000.0,
        highest_price_after_buy=340000.0
    )
    assert success, "Failed to inject test holding!"
    
    # Verify DB writing
    holdings = trading_engine.get_portfolio_holdings()
    assert "005930" in holdings, "005930 not found in holdings!"
    print("[SUCCESS] Test holding successfully injected in Firestore!")
    
    # 2. Trigger simulation cycle with bypass_hours=True
    # The rules engine must immediately trigger STOP_LOSS_EXIT
    print("\n[Step 2] Executing simulation cycle to trigger Stop-Loss...")
    result = trading_engine.run_simulation_cycle(bypass_hours=True)
    
    print("\n--- Execution Result ---")
    print(f"Status   : {result.get('status')}")
    print(f"Action   : {result.get('action')}")
    print(f"Ticker   : {result.get('ticker')}")
    print(f"Quantity : {result.get('quantity')}")
    print(f"Price    : {result.get('price'):,.0f} KRW" if result.get("price") else "")
    print(f"Reasoning: {result.get('reasoning')}")
    print("------------------------")
    
    # Asserts
    assert result.get("status") == "success", "Simulation cycle failed!"
    assert result.get("action") == "SELL", "Action should be SELL!"
    assert "손절매" in result.get("reasoning"), "Reasoning should mention 손절매!"
    
    # 3. Verify database updates (Samsung Electronics should be deleted from portfolio)
    holdings_after = trading_engine.get_portfolio_holdings()
    assert "005930" not in holdings_after, "Samsung Electronics should have been liquidated!"
    print("[SUCCESS] Samsung Electronics successfully liquidated and portfolio document cleaned up in Firestore!")
    
    # 4. Verify Transaction Logging
    txs = trading_engine.get_latest_transactions(limit=1)
    assert len(txs) > 0, "No transactions logged!"
    tx = txs[0]
    assert tx.get("action") == "STOP_LOSS_EXIT", f"Logged transaction action is not STOP_LOSS_EXIT: {tx.get('action')}"
    print(f"[SUCCESS] Transaction log verified! Logged action: {tx.get('action')}")
    print("==================================================")
    print("          DEFENSIVE RULES TEST COMPLETED          ")
    print("==================================================")

if __name__ == "__main__":
    run_defensive_rules_test()
