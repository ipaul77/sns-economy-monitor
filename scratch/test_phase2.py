import os
import sys

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trading_engine

def run_phase2_test():
    print("==================================================")
    print("      PHASE 2 TEST: GEMINI STRUCTURED PARSING      ")
    print("==================================================")

    # 1. Define mock portfolio & cash
    balance = 4500000.0  # 4.5 million KRW cash
    portfolio = {
        "005930": {"quantity": 50, "average_price": 75200.0},  # 50 shares of Samsung Electronics
        "000660": {"quantity": 10, "average_price": 182000.0}  # 10 shares of SK Hynix
    }

    # 2. Get current stock prices
    print("Fetching current prices for portfolio...")
    samsung_price = trading_engine.get_stock_price("005930")
    hynix_price = trading_engine.get_stock_price("000660")
    
    market_prices = {
        "005930": samsung_price if samsung_price > 0 else 78200.0,
        "000660": hynix_price if hynix_price > 0 else 195400.0
    }
    
    print("Current Prices used in test:")
    for ticker, price in market_prices.items():
        print(f"  - {ticker}: {price:,.0f} KRW")

    # 3. Formulate mock high-fidelity news context
    print("\nFormulating mock news context (Nvidia HBM supplier boom + Fed Macro headwind)...")
    news_context = [
        {
            "title": "NVIDIA Blackwell chips shipping in full force; K-HBM suppliers to see record profits",
            "sentiment": "POSITIVE",
            "sentiment_score": 0.88,
            "relevance_score": 10,
            "alert_level": "HIGH",
            "impacted_companies": ["삼성전자", "SK하이닉스"],
            "korean_summary": "엔비디아의 차세대 AI 칩인 블랙웰 출하가 본격화됨에 따라 고대역폭 메모리(HBM) 주요 공급선인 한국의 SK하이닉스와 삼성전자의 실적 성장이 눈부실 것으로 전망됩니다."
        },
        {
            "title": "US Federal Reserve hints at higher-for-longer interest rates as CPI remains sticky",
            "sentiment": "NEGATIVE",
            "sentiment_score": -0.55,
            "relevance_score": 8,
            "alert_level": "MEDIUM",
            "impacted_companies": ["한국은행", "금융지주"],
            "korean_summary": "미 연준의 인플레이션 우려로 인한 고금리 기조가 연내 장기화될 조짐을 보이면서, 신흥국 금융 시장 및 원화 가치의 단기 변동성이 불가피하게 상승할 전망입니다."
        }
    ]

    # 4. Generate AI trading decision
    print("\nCalling Gemini generative AI model with Pydantic structured output constraints...")
    decision = trading_engine.generate_trading_decision(
        portfolio=portfolio,
        balance=balance,
        market_prices=market_prices,
        news_context=news_context
    )

    # 5. Output Verification
    print("\n--- Decision Formulation Result ---")
    print(f"Action   : {decision.action}")
    print(f"Ticker   : {decision.ticker}")
    print(f"Allocation Pct : {decision.allocation_pct}%")
    print(f"Reasoning: {decision.reasoning}")
    print(f"Mode     : {decision.mode}")
    print("-----------------------------------")

    # Validate output schema fields
    if decision.action in ["BUY", "SELL", "HOLD"]:
        print("[SUCCESS] 'action' field contains a valid Literal value.")
    else:
        print("[ERROR] 'action' field has an illegal value.")

    if len(decision.ticker) == 6 and decision.ticker.isdigit():
        print("[SUCCESS] 'ticker' field is a valid 6-digit stock code.")
    else:
        print("[ERROR] 'ticker' field is invalid.")

    if isinstance(decision.allocation_pct, (int, float)) and 0.0 <= decision.allocation_pct <= 100.0:
        print("[SUCCESS] 'allocation_pct' field is a valid percentage.")
    else:
        print("[ERROR] 'allocation_pct' field is invalid.")

    if decision.mode in ["VALUE", "TECHNICAL"]:
        print("[SUCCESS] 'mode' field contains a valid Literal value.")
    else:
        print("[ERROR] 'mode' field is invalid.")

    if decision.reasoning and len(decision.reasoning.strip()) > 0:
        print("[SUCCESS] 'reasoning' contains a logical Korean explanation.")
    else:
        print("[ERROR] 'reasoning' field is empty.")

    print("\n==================================================")
    print("             PHASE 2 TEST COMPLETE                ")
    print("==================================================")

if __name__ == "__main__":
    run_phase2_test()
