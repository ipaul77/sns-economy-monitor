import os
import sys
import sqlite3

# Import application components from workspace
sys.path.append(os.path.abspath('.'))
import db
import main

def clear_and_recrawl():
    print("Clearing SQLite database history...")
    try:
        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history")
        conn.commit()
        conn.close()
        print("SQLite database history cleared successfully.")
    except Exception as e:
        print(f"Error clearing SQLite: {e}")

    if db.USE_FIREBASE and db.db_client:
        print("Clearing Firestore history collection...")
        try:
            docs = db.db_client.collection("history").stream()
            batch = db.db_client.batch()
            deleted = 0
            for doc in docs:
                batch.delete(doc.reference)
                deleted += 1
            if deleted > 0:
                batch.commit()
            print(f"Firestore history cleared successfully ({deleted} docs).")
        except Exception as e:
            print(f"Error clearing Firestore: {e}")

    # Clear briefing cache
    try:
        from briefing import clear_briefing_cache
        clear_briefing_cache()
    except Exception as e:
        print(f"Error clearing briefing cache: {e}")

    print("\nRe-running the pipeline to analyze all articles dynamically...")
    try:
        main.run_pipeline(main.global_config, main.global_analyzer)
        print("Pipeline run completed successfully with dynamic summaries!")
    except Exception as e:
        print(f"Error running pipeline: {e}")

if __name__ == "__main__":
    clear_and_recrawl()
