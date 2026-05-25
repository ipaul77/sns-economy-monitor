import os
import json
import google.generativeai as genai

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                api_key = config.get("GEMINI_API_KEY")
                
    if not api_key or not api_key.strip():
        print("[Error] GEMINI_API_KEY is not set in environment or config.json.")
        return
        
    print(f"[Diagnostic] Querying Gemini models available to your key...")
    try:
        genai.configure(api_key=api_key.strip())
        models = genai.list_models()
        print("\n--- AVAILABLE MODELS FOR YOUR API KEY ---")
        for m in models:
            # print model name and supported generation methods
            support = ", ".join(m.supported_generation_methods)
            print(f"- {m.name} (Methods: {support})")
        print("\n[Recommendation] Update 'config.json' model values with the names above (e.g. 'gemini-3.5-flash').")
    except Exception as e:
        print(f"[Error] Failed to list models: {str(e)}")

if __name__ == "__main__":
    main()
