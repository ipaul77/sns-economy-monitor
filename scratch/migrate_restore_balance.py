# -*- coding: utf-8 -*-
import os
import sys
import sqlite3

# Add root directory to python path
sys.path.append(os.getcwd())

import db
import trading_engine

def restore_balance():
    db.init_db()
    
    # Correct values based on cashflow reconstruction before corruption
    correct_balance = 10367036.25
    correct_total_asset = 13058036.25  # Cash + 9 shares of Samsung Electronics at 299,000 KRW
    
    print("=== STARTING DATABASE RESTORATION ===")
    print(f"Target Correct Balance: {correct_balance:,.2f} KRW")
    print(f"Target Correct Total Asset: {correct_total_asset:,.2f} KRW")
    
    # 1. Update SQLite Local Cache
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        
        # Restore agent_state
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("balance", str(correct_balance)))
        cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", ("total_asset", str(correct_total_asset)))
        conn.commit()
        print("[SUCCESS] SQLite: agent_state restored.")
        
        # Delete corrupted transactions (June 11th 17:46:41 transactions)
        cursor.execute("SELECT id, timestamp, action FROM transactions WHERE timestamp LIKE '2026-06-11T17:46:41%'")
        corrupted_txs = cursor.fetchall()
        print(f"SQLite: Found {len(corrupted_txs)} corrupted transactions to delete:")
        for tx in corrupted_txs:
            print(f"  - ID: {tx[0]} | TS: {tx[1]} | Action: {tx[2]}")
            
        cursor.execute("DELETE FROM transactions WHERE timestamp LIKE '2026-06-11T17:46:41%'")
        conn.commit()
        conn.close()
        print("[SUCCESS] SQLite: Corrupted transactions deleted.")
    except Exception as e:
        print(f"[Error] Failed to update SQLite: {e}")
        
    # 2. Update Firestore Live Database
    if not db.USE_FIREBASE or db.db_client is None:
        print("[Warning] Firebase is not initialized. Skipping Firestore updates.")
        return
        
    client = db.db_client
    
    try:
        # Update state document
        state_ref = client.collection("agents").document("state")
        state_ref.update({
            "balance": float(correct_balance),
            "total_asset": float(correct_total_asset)
        })
        print("[SUCCESS] Firestore: agents/state document updated.")
        
        # Find and delete corrupted transactions
        # Query transactions where timestamp starts with '2026-06-11T17:46:41'
        # To do this safely, we can query timestamp >= '2026-06-11T17:46:41' and timestamp < '2026-06-11T17:46:42'
        tx_query = client.collection("transactions")\
                         .where("timestamp", ">=", "2026-06-11T17:46:41")\
                         .where("timestamp", "<", "2026-06-11T17:46:42")
        
        docs = tx_query.stream()
        deleted_count = 0
        for doc in docs:
            doc_data = doc.to_dict()
            print(f"Firestore: Deleting transaction ID {doc.id} | TS: {doc_data.get('timestamp')} | Action: {doc_data.get('action')}")
            doc.reference.delete()
            deleted_count += 1
            
        print(f"[SUCCESS] Firestore: Deleted {deleted_count} corrupted transactions.")
    except Exception as e:
        print(f"[Error] Failed to update Firestore: {e}")

if __name__ == "__main__":
    restore_balance()
