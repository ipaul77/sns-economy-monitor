# -*- coding: utf-8 -*-
import os
import sys

# Add workspace root to python path
sys.path.append(os.getcwd())

import db
import trading_engine

def fix_balance():
    db.init_db()
    if not db.USE_FIREBASE or db.db_client is None:
        print("[Error] Firebase is not initialized. Cannot run Firestore fix.")
        return
        
    client = db.db_client
    
    # Correct values
    correct_balance = 7581520.0
    
    # Get current stock price for 삼성전자 (005930) to compute exact total asset
    samsung_price = trading_engine.get_stock_price("005930")
    if samsung_price <= 0:
        samsung_price = 299000.0  # Fallback to June 11 close price
        
    portfolio = trading_engine.get_portfolio_holdings()
    samsung_qty = portfolio.get("005930", {}).get("quantity", 9)
    
    portfolio_value = samsung_qty * samsung_price
    correct_total_asset = correct_balance + portfolio_value
    
    print("=== APPLYING BALANCE CORRECTION ===")
    print(f"Current stored balance in SQLite/Firestore: 10,367,036.25 KRW")
    print(f"Correct balance (after BUYs on June 10): {correct_balance:,.0f} KRW")
    print(f"Portfolio value (Samsung 005930 x {samsung_qty} shares at {samsung_price:,.0f} KRW): {portfolio_value:,.0f} KRW")
    print(f"Correct Total Asset: {correct_total_asset:,.0f} KRW")
    
    # 1. Update SQLite
    try:
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("balance", str(correct_balance)))
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("total_asset", str(correct_total_asset)))
        conn.commit()
        conn.close()
        print("[SUCCESS] SQLite local cache updated.")
    except Exception as e:
        print(f"[Warning] Failed to update SQLite cache: {e}")
        
    # 2. Update Firestore
    try:
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "balance": float(correct_balance),
            "total_asset": float(correct_total_asset)
        })
        print("[SUCCESS] Firestore agents/state document updated.")
    except Exception as e:
        print(f"[Error] Failed to update Firestore: {e}")

if __name__ == "__main__":
    fix_balance()
