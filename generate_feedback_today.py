import os
import sys
import json

# 1. Load config to check API Key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            api_key = config.get("GEMINI_API_KEY")

if not api_key or not api_key.strip():
    print("[Error] GEMINI_API_KEY is not set in environment or config.json.")
    print("Please run this script in a terminal where the environment variable is set, or write it in config.json temporarily.")
    sys.exit(1)

# 2. Configure google-generativeai globally
import google.generativeai as genai
genai.configure(api_key=api_key.strip())

# 3. Import Flask app and global analyzer
from main import app, global_analyzer
global_analyzer.api_configured = True

print("[Diagnostic] Running handle_daily_feedback logic...")
with app.test_request_context():
    from main import handle_daily_feedback
    response = handle_daily_feedback()
    print("\n=== EXECUTION COMPLETE ===")
    print(response.get_data(as_text=True))
