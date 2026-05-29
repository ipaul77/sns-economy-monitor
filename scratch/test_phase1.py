import os
import sys
from datetime import datetime

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import trading_engine

def run_phase1_test():
    print("==================================================")
    print("      PHASE 1 TEST: DATA & DB PIPELINE CHECK       ")
    print("==================================================")
    
    # 1. Check database type (Firestore vs SQLite fallback)
    print(f"[DB Status] USE_FIREBASE: {db.USE_FIREBASE}")
    print(f"[DB Status] DB Available: {db.FIREBASE_AVAILABLE}")
    print(f"[DB Status] Firestore Client: {db.db_client}")
    
    # 2. Test yfinance price gathering
    print("\n--- 1. Testing yfinance Price Gathering ---")
    samsung_price = trading_engine.get_stock_price("005930")
    hynix_price = trading_engine.get_stock_price("000660")
    
    print(f"Samsung Electronics (005930) Current Price: {samsung_price:,.0f} KRW")
    print(f"SK Hynix (000660) Current Price: {hynix_price:,.0f} KRW")
    
    if samsung_price > 0 and hynix_price > 0:
        print("[SUCCESS] yfinance successfully fetched real-time market prices!")
    else:
        print("[WARNING] yfinance price fetching failed. Falling back to static mock prices.")

    # 3. Test Firestore state reading & initialization
    print("\n--- 2. Testing Firestore Agent State Reading/Initialization ---")
    state = trading_engine.get_agent_state()
    print("Current State in Firestore:")
    for k, v in state.items():
        print(f"  - {k}: {v}")
        
    # 4. Test Firestore portfolio write & read
    print("\n--- 3. Testing Firestore Portfolio Reading/Writing ---")
    # Fetch current portfolio
    portfolio = trading_engine.get_portfolio_holdings()
    print(f"Initial Holdings (Count: {len(portfolio)}):")
    for ticker, info in portfolio.items():
        print(f"  - {ticker}: {info['quantity']} shares @ average price {info['average_price']:,.0f} KRW")
        
    # Write a test holding: Samsung Electronics (005930) with 10 shares at 75,000 KRW
    test_ticker = "005930"
    test_qty = 15
    test_price = 75000.0
    
    print(f"\nWriting test holding: {test_ticker} -> {test_qty} shares @ {test_price:,.0f} KRW")
    success = trading_engine.update_portfolio_holding_in_db(test_ticker, test_qty, test_price)
    
    if success:
        print("[SUCCESS] Successfully wrote holding to Firestore!")
    else:
        print("[ERROR] Failed to write holding to Firestore.")
        
    # Read it back to verify
    updated_portfolio = trading_engine.get_portfolio_holdings()
    print(f"\nUpdated Holdings (Count: {len(updated_portfolio)}):")
    for ticker, info in updated_portfolio.items():
        print(f"  - {ticker}: {info['quantity']} shares @ average price {info['average_price']:,.0f} KRW")
        
    # Assert writing is correct
    if test_ticker in updated_portfolio:
        holding = updated_portfolio[test_ticker]
        if holding["quantity"] == test_qty and holding["average_price"] == test_price:
            print(f"\n[SUCCESS] Verification successful! Holding matched perfectly.")
        else:
            print(f"\n[ERROR] Verification failed: Holding mismatch.")
    else:
        print(f"\n[ERROR] Verification failed: Holding not found after write.")

    # Restore the original holding or clean up if it was empty, or let's keep it for visual testing
    # We will just update it to 0 to delete it so we leave the database clean!
    print(f"\nCleaning up test holding (setting quantity to 0)...")
    cleanup_success = trading_engine.update_portfolio_holding_in_db(test_ticker, 0, 0.0)
    if cleanup_success:
        print("[CLEANUP SUCCESS] Test holding deleted successfully. Database left clean.")
    else:
        print("[CLEANUP WARNING] Failed to delete test holding during cleanup.")

    print("\n==================================================")
    print("             PHASE 1 TEST COMPLETE                ")
    print("==================================================")

if __name__ == "__main__":
    run_phase1_test()
