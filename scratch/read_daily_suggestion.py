import firebase_admin
from firebase_admin import credentials, firestore
import os
import sys
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Resolve paths
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cred_path = os.path.join(base_dir, "firebase_credentials.json")

if not os.path.exists(cred_path):
    print("Error: firebase_credentials.json not found.")
    sys.exit(1)

# Get date parameter (e.g. 2026-07-14) or default to today
target_date = sys.argv[1] if len(sys.argv) > 1 else None
if not target_date:
    # Use current local date in KST format (UTC+9)
    from datetime import timedelta, timezone
    kst = timezone(timedelta(hours=9))
    target_date = datetime.now(kst).date().isoformat()

print(f"Fetching 피드백 제안서 for date: {target_date}...")

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        
    db_client = firestore.client()
    doc_ref = db_client.collection("daily_suggestions").document(target_date)
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        print("\n==================================================")
        print(f"피드백 제안서 ({target_date})")
        print(f"저장시간: {data.get('timestamp')}")
        print(f"반영여부: {data.get('applied')}")
        print("==================================================\n")
        print(data.get("suggestion"))
        print("\n==================================================")
    else:
        print(f"No 피드백 제안서 found for date {target_date} in Firestore.")
            
except Exception as e:
    print(f"Error fetching 피드백 제안서: {e}")
