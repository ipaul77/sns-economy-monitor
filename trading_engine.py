import os
import sys
import json
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from typing_extensions import Literal
from concurrent.futures import ThreadPoolExecutor

import db
from trading_db import *
from market_analysis import *

# ---------------------------------------------------------------------------
# PHASE 2: GEMINI API STRUCTURED INVESTMENT DECISION FORMULATION
# ---------------------------------------------------------------------------
class TradingDecision(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="The trading action to execute: BUY, SELL, or HOLD.")
    ticker: str = Field(description="A 6-digit stock ticker code to trade (e.g. '005930' for Samsung Electronics, '000660' for SK Hynix).")
    allocation_pct: float = Field(description="Percentage of cash balance (for BUY) or owned shares (for SELL) to allocate (0.0 to 100.0).")
    reasoning: str = Field(description="Detailed multi-agent debate and reasoning behind the decision.")
    mode: Literal["VALUE", "TECHNICAL"] = Field(default="VALUE", description="Investment style: 'VALUE' (fundamental focus) or 'TECHNICAL' (momentum/breakout focus).")
    win_probability: float = Field(default=0.5, description="Estimated probability of a profitable outcome (0.0 to 1.0).")
    reward_to_risk_ratio: float = Field(default=1.0, description="Estimated reward-to-risk ratio (expected gain / expected loss, >= 0.1).")

def evaluate_macro_circuit_breaker(
    kospi_disparity: float, 
    kospi_daily_change: float, 
    kospi_rsi: float = 50.0,
    disparity_mean: float = 100.0, 
    disparity_std: float = 3.0
) -> str:
    """
    [전면수정] 지연지표(이격도)와 선행/동행지표(당일 변동률, RSI)의 괴리를 해결한 다차원 매크로 필터
    """
    crash_limit = disparity_mean - 2.5 * disparity_std        # 100 - 7.5 = 92.5
    value_buy_limit = disparity_mean - 1.5 * disparity_std    # 100 - 4.5 = 95.5
    no_buy_limit = disparity_mean - 0.5 * disparity_std       # 100 - 1.5 = 98.5

    # [핵심 1] V자 반등 (Short-covering / Rebound) 보호 가드레일
    # 이격도는 박살났지만 당일 변동률이 +1.5% 이상 강하게 튀어오를 때 -> 청산 금지 및 역발상 매수
    if kospi_disparity <= value_buy_limit and kospi_daily_change >= 1.5:
        return "V_SHAPE_REBOUND_BUY"

    # [핵심 2] 진짜 시스템 붕괴 조건 (AND 조건으로 변경)
    # 이격도도 무너지고 '동시에' 당일 폭락이 나와야 락다운
    if (kospi_disparity <= crash_limit and kospi_daily_change <= -2.0) or (kospi_daily_change <= -5.0):
        return "SYSTEM_CRASH_LOCKDOWN"
        
    # [핵심 3] 투매 구간 (역발상 매수) - RSI 과매도 필터 추가
    # 가격만 싸다고 사는게 아니라, RSI 30 이하로 투매가 나왔을 때만 진입
    if (kospi_disparity <= value_buy_limit) or (kospi_daily_change <= -3.0):
        if kospi_rsi <= 30.0:
            return "CONTRARIAN_VALUE_BUY"
        else:
            return "HARD_NO_BUY" # 이격도는 낮으나 RSI가 애매하면 추가 하락 여지 있음
        
    # 4. 마의 늪 구간 (애매한 하락장 - Whipsaw 방지)
    if value_buy_limit < kospi_disparity <= no_buy_limit:
        return "HARD_NO_BUY" 
        
    # 5. 약한 조정/횡보 구간
    if no_buy_limit < kospi_disparity < 99.0:
        if kospi_daily_change < -1.5:
            return "HARD_NO_BUY"
        return "CONSERVATIVE_BUY"
            
    return "NORMAL"

def generate_trading_decision(
    portfolio: Dict[str, Dict[str, Any]],
    balance: float,
    market_prices: Dict[str, float],
    news_context: List[Dict[str, Any]],
    market_indicators: Optional[Dict[str, Dict[str, Any]]] = None,
    index_changes: Optional[Dict[str, float]] = None,
    api_key: Optional[str] = None,
    blocked_buy_reasons: Optional[Dict[str, str]] = None
) -> TradingDecision:
    """
    Formulates a structured trading decision via Gemini structured API.
    """
    import google.generativeai as genai

    # Setup API Key
    gemini_key = api_key or os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("[Trading Engine] [Warning] GEMINI_API_KEY is not configured. Running in Mock/Demo mode.")
        # Fallback Mock Decision
        first_tick = list(market_prices.keys())[0] if market_prices else "005930"
        return TradingDecision(
            action="HOLD",
            ticker=first_tick,
            allocation_pct=0.0,
            reasoning="[Mock Mode] Gemini API key not found.",
            mode="VALUE",
            win_probability=0.5,
            reward_to_risk_ratio=1.0
        )

    genai.configure(api_key=gemini_key)

    # Format portfolio context
    portfolio_str = ""
    if not portfolio:
        portfolio_str = "보유 포지션이 없습니다 (예수금 100% 현금 상태).\n"
    else:
        for ticker, info in portfolio.items():
            qty = info.get("quantity", 0)
            avg = info.get("average_price", 0.0)
            highest = info.get("highest_price_after_buy", avg)
            mode = info.get("mode", "VALUE")
            curr_p = market_prices.get(ticker, 0.0)
            profit_pct = ((curr_p - avg) / avg) * 100 if avg > 0 else 0.0
            comp_name = ticker
            for c, t in COMPANY_TO_TICKER.items():
                if t == ticker:
                    comp_name = c
                    break
            portfolio_str += f"- {comp_name} ({ticker}): {qty}주 보유 | 평균매입가 {avg:,.0f}원 | 현재가 {curr_p:,.0f}원 (수익률 {profit_pct:+.2f}%) | 최고점 {highest:,.0f}원 | 투자모드: {mode}\n"

    # Format watchlist indicators context
    watchlist_str = ""
    for ticker, ind in market_indicators.items():
        comp_name = ticker
        for c, t in COMPANY_TO_TICKER.items():
            if t == ticker:
                comp_name = c
                break
        
        roe_str = f"{ind.get('roe'):.2f}%" if ind.get("roe") is not None else "N/A"
        debt_str = f"{ind.get('debt_to_equity'):.1f}%" if ind.get("debt_to_equity") is not None else "N/A"
        pe_str = f"{ind.get('pe_ratio'):.1f}x" if ind.get("pe_ratio") is not None else "N/A"
        pb_str = f"{ind.get('pb_ratio'):.2f}x" if ind.get("pb_ratio") is not None else "N/A"
        safety_str = f"{ind.get('margin_of_safety'):+.1f}%" if ind.get("margin_of_safety") is not None else "N/A"
        target_str = f"{ind.get('target_price'):,.0f}원" if ind.get("target_price") is not None else "N/A"

        watchlist_str += (
            f"- {comp_name} ({ticker}): 현재가 {ind.get('current_price'):,.0f}원 | "
            f"20MA {ind.get('ma_20'):,.0f}원 | 이격도 {ind.get('disparity'):.2f}% | RSI {ind.get('rsi'):.1f} | "
            f"당일거래량: {ind.get('daily_volume', 0):,}주 | "
            f"외인5일누적: {ind.get('frgn_net_5d', 0):+d}주 | "
            f"기관5일누적: {ind.get('inst_net_5d', 0):+d}주 | "
            f"ROE: {roe_str} | 부채비율: {debt_str} | PER: {pe_str} | PBR: {pb_str} | 안전마진: {safety_str} (목표주가: {target_str})\n"
        )

    # Format news analysis context
    news_items = [item for item in news_context if item.get("source") != "Naver Research"]
    report_items = [item for item in news_context if item.get("source") == "Naver Research"]

    news_str = ""
    if not news_items:
        news_str = "최근 24시간 동안 수집된 한국 경제 관련 신규 뉴스가 없습니다."
    else:
        total_news = len(news_items)
        pos_news = sum(1 for item in news_items if item.get('sentiment') == 'POSITIVE')
        neg_news = sum(1 for item in news_items if item.get('sentiment') == 'NEGATIVE')
        neu_news = sum(1 for item in news_items if item.get('sentiment') == 'NEUTRAL')
        avg_sentiment = sum(item.get('sentiment_score', 0.0) for item in news_items) / total_news if total_news > 0 else 0.0
        
        news_str = f"시장 전체 뉴스 감성 통계: 총 {total_news}건 (긍정 {pos_news}건, 부정 {neg_news}건, 중립 {neu_news}건) | 평균 감성 점수: {avg_sentiment:+.2f}\n"
        news_str += "최근 핵심 뉴스 헤드라인:\n"
        for idx, item in enumerate(news_items[:10]):
            news_str += f"- {idx+1}. [{item.get('source', '뉴스')}] {item.get('title', '')} (중요도: {item.get('relevance_score', 5)}/10 | 감성: {item.get('sentiment', 'NEUTRAL')}({item.get('sentiment_score', 0.0):+.2f}))\n"

    report_str = ""
    if not report_items:
        report_str = "최근 24시간 동안 발표된 증권사 분석 리포트가 없습니다."
    else:
        total_reports = len(report_items)
        pos_rep = sum(1 for item in report_items if item.get('sentiment') == 'POSITIVE')
        neg_rep = sum(1 for item in report_items if item.get('sentiment') == 'NEGATIVE')
        neu_rep = sum(1 for item in report_items if item.get('sentiment') == 'NEUTRAL')
        avg_rep_sentiment = sum(item.get('sentiment_score', 0.0) for item in report_items) / total_reports if total_reports > 0 else 0.0
        
        report_str = f"증권사 리포트 감성 통계: 총 {total_reports}건 (긍정 {pos_rep}건, 부정 {neg_rep}건, 중립 {neu_rep}건) | 평균 리포트 점수: {avg_rep_sentiment:+.2f}\n"
        report_str += "최근 핵심 리포트 헤드라인:\n"
        for idx, item in enumerate(report_items[:10]):
            report_str += f"- {idx+1}. [{item.get('source', '리포트')}] {item.get('title', '')} (중요도: {item.get('relevance_score', 7)}/10 | 감성: {item.get('sentiment', 'NEUTRAL')}({item.get('sentiment_score', 0.0):+.2f}))\n"

    # Define system instructions (Guardrails & Multi-Agent debate prompting)
    system_instruction = (
        "당신은 거시경제(Macro), 수급(Supply/Demand), 시장 심리(Sentiment)를 최우선으로 고려한 뒤 펀더멘털(Fundamental)을 분석하는 '탑다운(Top-Down) 전략 기반의 최고 수준 애널리스트 겸 트레이더'입니다. 당신의 지능 내부에는 세 명의 금융 전문가 위원이 존재합니다.\n"
        "1. 기술적 분석가 (Technical Analyst): 차트 이평선, 이격도, RSI, 스토캐스틱, 거래량 지표 등을 철저히 분석하고 단기 추세와 가격적 진입 지점을 제시합니다.\n"
        "2. 거시/재료 분석가 (Macro/Sentiment Analyst): 뉴스 속보, 뉴스 감성(Sentiment) 정보, 미국 지수(SOXX), 원/달러 환율 등 거시적 유동성과 재료의 파급력을 분석합니다.\n"
        "3. 리스크 관리자 (Risk Manager): 포트폴리오 비중, 섹터 편중 리스크, 약세장 도래 시 자산 배분 방침, 손절/추적손절매 발생 이력 등을 따져 원금 보존 가이드를 제시합니다.\n\n"
        "의사결정을 내릴 때 이 세 명의 전문가 위원이 각자의 관점에서 열띤 토론을 벌여 합의(Consensus)를 이끌어내도록 시뮬레이션하십시오. 토론의 세부 내용은 판단 근거(`reasoning`) 필드에 기술해야 합니다.\n\n"
        "또한 새로 제공되는 `win_probability`(성공 확률, 0.0~1.0)과 `reward_to_risk_ratio`(손익비, 예상 이익/예상 손실, >= 0.1) 필드를 지표 데이터와 분석을 바탕으로 합리적으로 추정하여 채워 넣으십시오. 만약 성공 확률이 낮거나 손익비가 좋지 않다면 합의는 `HOLD` 또는 `SELL`로 기울어야 합니다. 매수를 추천하려면 최종 세 위원의 합의 점수(Consensus Score)가 최소 70% 이상이어야 합니다.\n\n"
        "의사결정을 내릴 때 반드시 아래의 1단계부터 3단계까지 순차적으로 통과한 경우에만 매수(BUY)를 결정하십시오. 하나라도 붉은등(Red Light)이 켜지면 철저히 관망(HOLD)하거나 매도(SELL)하십시오.\n\n"
        "1단계: 매크로 및 시장 투심 (Macro & Sentiment)\n"
        "- 코스피/코스닥 지수의 급락(사이드카 등), 환율의 급등(예: 1,400원 이상 고공행진 등) 등 거시경제 불확실성이 큰가?\n"
        "- 해당 종목이나 시장 전체에 대한 최신 뉴스 감성 점수(Sentiment)가 악재로 편향되어 있는가?\n"
        "-> [판단 기준] 매크로 지표가 붕괴 중이거나 뉴스 감성이 악재라면, 아무리 주가가 싸 보여도 절대 매수하지 말고 'HOLD' 하십시오.\n\n"
        "2단계: 수급 및 모멘텀 (Supply & Demand)\n"
        "- 최근 외국인과 기관의 대규모 양매도가 쏟아지고 있는가? (수급 폭락 상태)\n"
        "- 주가가 20일 이동평균선 아래에서 거래량 없이 흘러내리고 있는가?\n"
        "-> [판단 기준] 외국인/기관의 강한 이탈은 해당 기업의 펀더멘털 훼손을 선반영한 스마트 머니의 움직임일 확률이 높습니다. '떨어지는 칼날'이므로 절대 신규 진입(BUY)을 하지 마십시오.\n\n"
        "3단계: 펀더멘털 및 밸류에이션 (Fundamental & Valuation)\n"
        "- 1단계와 2단계를 모두 안전하게 통과했을 때만 이 지표를 봅니다.\n"
        "- PER, ROE, 부채비율, 안전마진(목표가 대비 현재가 괴리율)이 훌륭한가?\n"
        "-> [판단 기준] 시장이 안정적이고 수급이 꼬이지 않은 상태에서 안전마진이 15% 이상 확보된 저평가 우량주라면 적극적으로 'BUY'를 고려하십시오.\n\n"
        "[특별 방어 규칙 (Special Rules)]\n"
        "1. 가치 트랩(Value Trap) 경계: 가격이 하락하여 안전마진이 커졌다는 이유만으로 '물타기(불타기)'를 시도하지 마십시오. 하락의 원인이 수급 악화나 매크로 붕괴라면 이는 싼 것이 아니라 위험한 것입니다.\n"
        "2. 휩쏘(Whipsaw) 방지: 직전 거래에서 '추적손절매'나 '손절'이 발생한 종목은, 명확한 수급의 상향 반전 신호나 뉴스 호재가 새로 발생하지 않는 한 당일 재매수하지 마십시오.\n\n"
        "[출력 포맷 (Output Format)]\n"
        "결정을 내릴 때 판단 근거(reasoning)는 반드시 아래 구조로 명확히 서술하십시오.\n"
        "- 위원회 토론 (Debate):\n"
        "  * 기술적 분석가 의견:\n"
        "  * 거시/재료 분석가 의견:\n"
        "  * 리스크 관리자 의견:\n"
        "- 합의 결론 및 점수 (Consensus Score: XX%): (최종 합의된 액션과 이유 서술. 성공 확률 및 손익비 평가 근거 요약)\n\n"
        "매수(BUY) 시 Pydantic 응답의 `mode` 필드는 펀더멘털 기반 매수 시 'VALUE', 수급/모멘텀 모멘텀 트레이딩 기반 매수 시 'TECHNICAL'로 설정하십시오. (HOLD나 SELL 시에는 기본값인 'VALUE' 또는 기존 보유 모드를 사용하십시오.)"
    )

    blocked_str = ""
    if blocked_buy_reasons:
        blocked_str = "\n[⚠️ 리스크 가드레일에 따른 종목별 매수 제한 사항 - 절대로 이 종목들을 BUY하지 마십시오]\n"
        for tick, reason in blocked_buy_reasons.items():
            comp_name = tick
            for c, t in COMPANY_TO_TICKER.items():
                if t == tick:
                    comp_name = c
                    break
            blocked_str += f"- {comp_name} ({tick}): 매수 불가 사유 - {reason} (이 종목은 오직 SELL 또는 HOLD만 결정할 수 있습니다.)\n"

    user_prompt = (
        f"=== 1. 현재 계정 자산 정보 ===\n- 가용 현금(예수금): {balance:,.0f} KRW\n\n"
        f"=== 2. 현재 보유 중인 포트폴리오 포지션 ===\n{portfolio_str}\n"
        f"=== 3. 현재 시장 감시 및 거래 후보 종목 기술 지표 ===\n{watchlist_str}\n"
        f"{blocked_str}\n"
        f"=== 4. 최근 24시간 동안 수집된 국내/외 시장 거시 속보 ===\n{news_str}\n"
        f"=== 5. 최근 발표된 국내 증권사 기업 실적 분석 리포트 ===\n{report_str}\n\n"
        "위의 시장 상황과 포트폴리오 정보를 바탕으로 3인 전문가 위원회 토론 시뮬레이션을 진행한 뒤, 최종 합의된 투자 의사결정을 내리십시오."
    )

    try:
        model_name = "gemini-3.1-pro-preview"
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
                model_name = config.get("models", {}).get("pro_model", "gemini-3.1-pro-preview")
        except Exception:
            pass

        candidate_models = [model_name, "gemini-3.1-pro-preview", "gemini-3.5-flash"]
        # Remove duplicates while preserving order
        candidate_models = list(dict.fromkeys(candidate_models))
        
        from google.generativeai.types import content_types
        schema = content_types._schema_for_class(TradingDecision)
        
        def _sanitize_schema(d):
            if isinstance(d, dict):
                return {k: _sanitize_schema(v) for k, v in d.items() if k not in ["default", "title"]}
            elif isinstance(d, list):
                return [_sanitize_schema(i) for i in d]
            return d
            
        schema = _sanitize_schema(schema)
        schema["required"] = ["action", "ticker", "allocation_pct", "reasoning", "mode", "win_probability", "reward_to_risk_ratio"]

        last_err = None
        for candidate in candidate_models:
            try:
                print(f"[Trading Engine] Invoking Gemini model '{candidate}' for consensus debate...")
                model = genai.GenerativeModel(
                    model_name=candidate,
                    system_instruction=system_instruction
                )
                response = model.generate_content(
                    user_prompt,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema=schema
                    )
                )
                raw_text = response.text.strip()
                decision_dict = json.loads(raw_text)
                return TradingDecision(**decision_dict)
            except Exception as cand_ex:
                print(f"[Trading Engine] Model '{candidate}' execution failed: {cand_ex}. Trying fallback...")
                last_err = cand_ex

        raise last_err or Exception("All candidate models failed.")
        
    except Exception as e:
        print(f"[Trading Engine] [Error] Gemini structured output generation or parse failed: {e}")
        # Default Safe Fallback: HOLD first asset
        first_tick = list(market_prices.keys())[0] if market_prices else "005930"
        return TradingDecision(
            action="HOLD",
            ticker=first_tick,
            allocation_pct=0.0,
            reasoning=f"[System Fallback due to Gemini Error: {str(e)}]",
            mode="VALUE",
            win_probability=0.5,
            reward_to_risk_ratio=1.0
        )


def _load_config_and_check_eligibility(bypass_hours: bool) -> dict:
    config = {}
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to load config.json: {e}")

    state = get_agent_state()
    if state.get("system_lock", False):
        print("[Trading Engine] CRITICAL: System is locked! Aborting simulation run.")
        return {"status": "error", "message": "System is locked due to past accounting anomalies."}

    now = get_kst_now()
    is_weekday = now.weekday() < 5
    market_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    is_market_open = is_weekday and (market_start <= now <= market_end)
    
    if not is_market_open and not bypass_hours:
        print(f"[Trading Engine] Out of market hours ({now.strftime('%Y-%m-%d %H:%M:%S')} KST). Simulation skipped.")
        return {"status": "skipped", "message": "Market is closed. Simulated runs only occur on weekdays between 09:00 and 15:30 KST."}

    portfolio = get_portfolio_holdings()
    news_context = db.fetch_recent_relevant(hours=24)
    balance = float(state.get("balance", 10000000.0))
    prev_total_asset = float(state.get("total_asset", 10000000.0))

    last_txs = get_latest_transactions(limit=1)
    if last_txs:
        last_tx = last_txs[0]
        try:
            last_time = datetime.fromisoformat(last_tx["timestamp"]).replace(tzinfo=None)
            time_diff = now.replace(tzinfo=None) - last_time
            cooldown = timedelta(minutes=15)
            if time_diff < cooldown and not bypass_hours:
                print(f"[Trading Engine] Idempotency Lock: Trade within 15 minutes cooldown is blocked.")
                return {"status": "skipped", "message": "Idempotency Lock: Minimum 15-minute interval between trades required."}
        except Exception as e:
            print(f"[Trading Engine] Failed to parse last transaction timestamp: {e}")

    return {
        "status": "eligible",
        "config": config,
        "state": state,
        "portfolio": portfolio,
        "news_context": news_context,
        "balance": balance,
        "prev_total_asset": prev_total_asset,
        "now": now,
        "last_txs": last_txs
    }

def _fetch_market_indices_and_trends(now) -> dict:
    index_changes = get_market_index_change()
    print(f"[Trading Engine] Market Indices changes: {index_changes}")
    
    usdkrw_price = 1350.0
    usdkrw_change_pct = 0.0
    try:
        import market
        m_data = market.get_market_indicators()
        if m_data and "USD_KRW" in m_data:
            usdkrw_price = m_data["USD_KRW"].get("price", 1350.0)
            usdkrw_change_pct = m_data["USD_KRW"].get("percent", 0.0)
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to fetch USD_KRW details: {e}")
    print(f"[Trading Engine] USD_KRW exchange rate: {usdkrw_price:,.2f} KRW (당일 등락률: {usdkrw_change_pct:+.2f}%)")

    usdkrw_disparity = 100.0
    usdkrw_high_3m = usdkrw_price
    usdkrw_drop_from_high_pct = 0.0
    usdkrw_trend_state = "STABLE"
    try:
        yt_krw = yf.Ticker("USDKRW=X")
        hist_krw = yt_krw.history(period="3mo")
        if not hist_krw.empty:
            usdkrw_ma20 = hist_krw["Close"].iloc[-20:].mean()
            usdkrw_disparity = (usdkrw_price / usdkrw_ma20) * 100
            usdkrw_high_3m = float(hist_krw["High"].max())
            if usdkrw_high_3m > 0:
                usdkrw_drop_from_high_pct = ((usdkrw_price - usdkrw_high_3m) / usdkrw_high_3m) * 100.0
            
            # Classify Exchange Rate Peak-to-Trough Trend State
            if usdkrw_drop_from_high_pct <= -2.5:
                usdkrw_trend_state = "STABILIZING_WON_STRENGTH"  # 원화 강세 전환기 (전고점 대비 하락 중 -> 대형주/외인 수혜)
            elif usdkrw_disparity >= 102.0 or usdkrw_change_pct >= 1.0:
                usdkrw_trend_state = "SURGING_DOLLAR_WEAKNESS"  # 환율 급등 위험기
            else:
                usdkrw_trend_state = "STABLE"
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to calculate USD_KRW trend metrics: {e}")

    kospi_disparity = 100.0
    kosdaq_disparity = 100.0
    kospi_rsi = 50.0
    kospi_ewma_vol = 1.2
    try:
        hist_kospi = yf.Ticker("^KS11").history(period="1mo")
        if not hist_kospi.empty:
            kospi_ma20 = hist_kospi["Close"].mean()
            kospi_curr = hist_kospi["Close"].iloc[-1]
            kospi_disparity = (kospi_curr / kospi_ma20) * 100
            
            # Calculate KOSPI RSI
            close_prices = hist_kospi["Close"].tolist()
            from market_analysis import calculate_rsi
            kospi_rsi = calculate_rsi(close_prices, 14)
            
            # Calculate KOSPI EWMA daily return volatility
            returns_kospi = hist_kospi["Close"].pct_change().dropna() * 100
            if len(returns_kospi) > 1:
                kospi_ewma_vol = float(returns_kospi.ewm(span=10).std().iloc[-1])
            if pd.isna(kospi_ewma_vol) or kospi_ewma_vol <= 0:
                kospi_ewma_vol = 1.2
            
        hist_kosdaq = yf.Ticker("^KQ11").history(period="1mo")
        if not hist_kosdaq.empty:
            kosdaq_ma20 = hist_kosdaq["Close"].mean()
            kosdaq_curr = hist_kosdaq["Close"].iloc[-1]
            kosdaq_disparity = (kosdaq_curr / kosdaq_ma20) * 100
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to calculate index disparities: {e}")
    print(f"[Trading Engine] 20MA Disparities -> USD_KRW: {usdkrw_disparity:.2f}% (Trend: {usdkrw_trend_state}, High3M: {usdkrw_high_3m:,.1f}원, Drop: {usdkrw_drop_from_high_pct:+.2f}%), KOSPI: {kospi_disparity:.2f}%, KOSPI RSI: {kospi_rsi:.1f}, KOSPI EWMA Vol: {kospi_ewma_vol:.2f}%, KOSDAQ: {kosdaq_disparity:.2f}%")

    is_downtrend = False
    kospi_disparity_std = 1.5
    kospi_disparity_mean = 100.0
    try:
        regime = get_market_trend_regime()
        is_downtrend = regime.get("is_downtrend", False)
        kospi_disparity_std = regime.get("disparity_std", 1.5)
        kospi_disparity_mean = regime.get("disparity_mean", 100.0)
        print(f"[Trading Engine] Market Regime check: {'Downtrend' if is_downtrend else 'Uptrend'} - {regime.get('message')}")
    except Exception as e:
        print(f"[Trading Engine] [Warning] Failed to resolve market trend regime: {e}")

    return {
        "index_changes": index_changes,
        "usdkrw_price": usdkrw_price,
        "usdkrw_change_pct": usdkrw_change_pct,
        "usdkrw_disparity": usdkrw_disparity,
        "usdkrw_high_3m": usdkrw_high_3m,
        "usdkrw_drop_from_high_pct": usdkrw_drop_from_high_pct,
        "usdkrw_trend_state": usdkrw_trend_state,
        "kospi_disparity": kospi_disparity,
        "kosdaq_disparity": kosdaq_disparity,
        "is_downtrend": is_downtrend,
        "kospi_disparity_std": kospi_disparity_std,
        "kospi_disparity_mean": kospi_disparity_mean,
        "kospi_rsi": kospi_rsi,
        "kospi_ewma_vol": kospi_ewma_vol
    }

def _apply_preflight_cooldown_filters(monitored_tickers, portfolio, now) -> tuple:
    filtered_tickers = []
    pre_blocked_reasons = {}
    for ticker in monitored_tickers:
        if ticker in portfolio:
            filtered_tickers.append(ticker)
            continue
            
        last_sell = get_last_sell_transaction(ticker)
        if last_sell:
            try:
                last_time = datetime.fromisoformat(last_sell["timestamp"]).replace(tzinfo=None)
                time_diff = now.replace(tzinfo=None) - last_time
                action = last_sell.get("action", "SELL")
                
                if action in ["STOP_LOSS_EXIT", "TRAILING_STOP_EXIT"]:
                    cooldown_limit = timedelta(minutes=120)
                    cooldown_desc = "120분(2시간) 재진입 제한(쿨타임)"
                    cooldown_hours = 2.0
                else:
                    cooldown_limit = timedelta(hours=24)
                    cooldown_desc = "24시간 재진입 제한(쿨타임)"
                    cooldown_hours = 24.0
                    
                if time_diff < cooldown_limit:
                    pre_blocked_reasons[ticker] = f"직전 매도({action}) 후 {cooldown_desc}이 진행 중입니다. (남은 시간: {cooldown_hours - time_diff.total_seconds() / 3600:.1f}시간)"
                    print(f"[Trading Engine] Pre-flight filter: Ticker {ticker} is blocked by time-based cooldown ({action}).")
                    continue
            except Exception as e:
                print(f"[Trading Engine] [Warning] Failed to parse last sell timestamp for {ticker}: {e}")

        filtered_tickers.append(ticker)
    return filtered_tickers, pre_blocked_reasons

def _fetch_prices_and_indicators(monitored_tickers) -> tuple:
    market_indicators = {}
    market_prices = {}
    
    def fetch_indicators(tick):
        return tick, get_stock_indicators(tick)
        
    try:
        with ThreadPoolExecutor(max_workers=max(len(monitored_tickers), 1)) as executor:
            results = list(executor.map(fetch_indicators, monitored_tickers))
            for tick, ind in results:
                market_indicators[tick] = ind
                price = ind.get("current_price", 0.0)
                if price > 0:
                    market_prices[tick] = price
    except Exception as e:
        print(f"[Trading Engine] [Warning] Parallel indicator fetching failed: {e}. Falling back to sequential.")
        for tick in monitored_tickers:
            ind = get_stock_indicators(tick)
            market_indicators[tick] = ind
            price = ind.get("current_price", 0.0)
            if price > 0:
                market_prices[tick] = price
                
    return market_indicators, market_prices

def _check_technical_and_news_idempotency(market_indicators, news_context, last_txs, bypass_hours) -> Optional[dict]:
    has_technical_trigger = False
    
    last_tx = last_txs[0] if last_txs else None
    last_snapshot = last_tx.get("snapshot_context", {}) if last_tx else {}
    last_indicators = last_snapshot.get("market_indicators", {})
    
    for tick, ind in market_indicators.items():
        if ind.get("volume_breakout", False):
            has_technical_trigger = True
            print(f"[Trading Engine] Technical Trigger: Volume breakout detected for {tick}.")
            break
            
        if abs(ind.get("disparity", 100.0) - 100.0) >= 10.0:
            has_technical_trigger = True
            print(f"[Trading Engine] Technical Trigger: Extreme disparity ({ind.get('disparity')}% ) detected for {tick}.")
            break
            
        if last_indicators and tick in last_indicators:
            last_tick_ind = last_indicators[tick]
            last_price = last_tick_ind.get("current_price", 0.0)
            curr_price = ind.get("current_price", 0.0)
            if last_price > 0 and curr_price > 0:
                price_change_pct = abs(curr_price - last_price) / last_price
                if price_change_pct >= 0.03:
                    has_technical_trigger = True
                    print(f"[Trading Engine] Technical Trigger: Price shifted by {price_change_pct:.1%} since last trade for {tick}.")
                    break
                    
            last_frgn_sig = last_tick_ind.get("frgn_trend_sig", "HOLD")
            curr_frgn_sig = ind.get("frgn_trend_sig", "HOLD")
            last_inst_sig = last_tick_ind.get("inst_trend_sig", "HOLD")
            curr_inst_sig = ind.get("inst_trend_sig", "HOLD")
            
            if last_frgn_sig != curr_frgn_sig or last_inst_sig != curr_inst_sig:
                has_technical_trigger = True
                print(f"[Trading Engine] Technical Trigger: Sugeup signal changed for {tick}.")
                break
            
    if news_context and not has_technical_trigger:
        latest_news_url = news_context[0].get("url", "")
        already_processed_news = False
        for tx in get_latest_transactions(limit=5):
            snapshot = tx.get("snapshot_context", {})
            if snapshot.get("latest_news_url") == latest_news_url and tx.get("action") != "HOLD" and not bypass_hours:
                already_processed_news = True
                break
        
        if already_processed_news:
            print(f"[Trading Engine] Idempotency Lock: Already processed and acted upon the latest news URL: {latest_news_url}")
            return {"status": "skipped", "message": "Idempotency Lock: Latest news context has already been acted upon."}

    return None

def _handle_macro_circuit_breaker_liquidation(
    macro_state, portfolio, balance, market_prices, kospi_disparity, kospi_change
) -> Optional[dict]:
    if macro_state == "SYSTEM_CRASH_LOCKDOWN":
        print(f"[EMERGENCY] 시장 붕괴 감지 (KOSPI 이격도 {kospi_disparity:.2f}%, 당일 변동률 {kospi_change:+.2f}%).")
        print("[EMERGENCY] AI 토론을 생략하고 전 종목 시장가 일괄 매도 후 시스템을 즉시 관망 모드로 전환합니다.")
        
        emergency_orders_executed = []
        total_sell_val = 0.0
        total_fee = 0.0
        
        current_portfolio_value = sum(holding.get("quantity", 0) * market_prices.get(t, 0.0) for t, holding in portfolio.items())
        current_total_asset = balance + current_portfolio_value
        
        for ticker, info in list(portfolio.items()):
            qty = info.get("quantity", 0)
            if qty > 0:
                curr_price = market_prices.get(ticker, 0.0)
                if curr_price <= 0:
                    curr_price = get_stock_price(ticker)
                if curr_price > 0:
                    sell_val = qty * curr_price
                    fee = sell_val * 0.001
                    total_sell_val += sell_val
                    total_fee += fee
                    
                    update_portfolio_holding_in_db(ticker, 0, info.get("average_price", 0.0))
                    
                    reasoning = f"[매크로 서킷 브레이커: 기계적 일괄 청산] KOSPI 이격도({kospi_disparity:.2f}%) 및 당일 변동률({kospi_change:+.2f}%)이 초극단적 시스템 붕괴 기준을 초과하여 전 종목 일괄 기계적 현금화(전량 청산)가 집행되었습니다. (체결가: {curr_price:,.0f}원, 수량: {qty}주)"
                    snapshot = {
                        "prev_balance": balance,
                        "new_balance": balance + sell_val - fee,
                        "prev_total_asset": current_total_asset,
                        "new_total_asset": current_total_asset - fee,
                        "transaction_fee": fee,
                        "market_prices": market_prices,
                        "circuit_breaker": True
                    }
                    save_transaction_to_db(ticker, "SYSTEMIC_LIQUIDATION", qty, curr_price, reasoning, snapshot)
                    trigger_telegram_trade_alert(
                        ticker=ticker,
                        action="SYSTEMIC_LIQUIDATION",
                        quantity=qty,
                        price=curr_price,
                        reasoning=reasoning,
                        balance=balance + sell_val - fee,
                        total_asset=current_total_asset - fee
                    )
                    emergency_orders_executed.append(ticker)
                    
        if emergency_orders_executed:
            new_balance = balance + total_sell_val - total_fee
            update_agent_state_in_db(new_balance, new_balance, system_lock=False)
            return {
                "status": "success",
                "action": "SYSTEMIC_LIQUIDATION",
                "message": f"Emergency liquidation executed for {', '.join(emergency_orders_executed)}."
            }
            
        reasoning = f"[매크로 서킷 브레이커: 시스템 락다운] KOSPI 이격도({kospi_disparity:.2f}%) 및 당일 변동률({kospi_change:+.2f}%)이 시스템 붕괴 수준에 도달하여 신규 매수가 전면 금지되고 관망 상태를 유지합니다."
        snapshot = {
            "prev_balance": balance,
            "new_balance": balance,
            "prev_total_asset": balance,
            "new_total_asset": balance,
            "transaction_fee": 0.0,
            "market_prices": market_prices,
            "circuit_breaker": True
        }
        save_transaction_to_db(
            ticker="",
            action="HOLD",
            quantity=0,
            price=0.0,
            reasoning=reasoning,
            snapshot_context=snapshot
        )
        return {
            "status": "success",
            "action": "HOLD",
            "message": "System lockdown active. Portfolio is already empty. All buys are disabled.",
            "reasoning": reasoning
        }
    return None

def _evaluate_mechanical_exits(
    portfolio, balance, market_prices, market_indicators, is_downtrend, kospi_change, news_context, prev_total_asset
) -> Optional[dict]:
    today_str = get_kst_now().strftime("%Y-%m-%d")

    for ticker, holding in portfolio.items():
        current_price = market_prices.get(ticker, 0.0)
        if current_price <= 0:
            continue
            
        avg_price = holding["average_price"]
        prev_highest = holding["highest_price_after_buy"]
        mode = holding.get("mode", "VALUE")
        last_scale_out = holding.get("last_scale_out_date")
        is_scale_out_today = (last_scale_out == today_str)
        
        ticker_sector = TICKER_TO_SECTOR.get(ticker, "기타")
        sector_changes = [
            ind.get("daily_change_pct", 0.0)
            for t, ind in market_indicators.items()
            if TICKER_TO_SECTOR.get(t, "기타") == ticker_sector
        ]
        sector_avg_change = sum(sector_changes) / len(sector_changes) if sector_changes else 0.0
        is_relaxed = (kospi_change >= 1.0) and (sector_avg_change > 0.0)
        
        if is_downtrend:
            if mode == "VALUE":
                stop_loss_rate = 0.08
                trailing_stop_rate = 0.10 if is_relaxed else 0.08
            else:
                stop_loss_rate = 0.03
                trailing_stop_rate = 0.035 if is_relaxed else 0.03
        else:
            if mode == "VALUE":
                stop_loss_rate = 0.15
                trailing_stop_rate = 0.20 if is_relaxed else 0.15
            else:
                stop_loss_rate = 0.045
                trailing_stop_rate = 0.05 if is_relaxed else 0.045
            
        new_highest = max(current_price, prev_highest)
        if new_highest > prev_highest:
            update_portfolio_holding_in_db(ticker, holding["quantity"], avg_price, new_highest, mode=mode, last_scale_out_date=last_scale_out)
            holding["highest_price_after_buy"] = new_highest
            
        stop_loss_limit = avg_price * (1 - stop_loss_rate)
        if current_price <= stop_loss_limit:
            print(f"[Trading Engine] [EX-SL] Stop-Loss triggered for {ticker}! Mode={mode}, Price {current_price:,.0f} <= Limit {stop_loss_limit:,.0f} KRW.")
            qty = holding["quantity"]
            total_sell_val = qty * current_price
            fee_rate = 0.001
            tx_fee = total_sell_val * fee_rate
            new_balance = balance + (total_sell_val - tx_fee)
            
            update_portfolio_holding_in_db(ticker, 0, avg_price)
            new_total_asset = new_balance + sum(
                p_info["quantity"] * market_prices.get(p_tick, 0.0)
                for p_tick, p_info in portfolio.items() if p_tick != ticker
            )
            update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
            
            reasoning = f"[기계적 손절매 청산] 주가가 매수가({avg_price:,.0f}원) 대비 -{stop_loss_rate*100:.1f}% 손실 한계선({stop_loss_limit:,.0f}원)에 도달하여 추가 손실 차단을 위해 전량 시장가 매도 처리하였습니다. [투자모드: {mode}] (현재가: {current_price:,.0f}원)"
            snapshot = {
                "prev_balance": balance,
                "new_balance": new_balance,
                "prev_total_asset": prev_total_asset,
                "new_total_asset": new_total_asset,
                "transaction_fee": tx_fee,
                "market_prices": market_prices,
                "highest_price_after_buy": new_highest,
                "mode": mode
            }
            save_transaction_to_db(ticker, "STOP_LOSS_EXIT", qty, current_price, reasoning, snapshot)
            trigger_telegram_trade_alert(
                ticker=ticker,
                action="STOP_LOSS_EXIT",
                quantity=qty,
                price=current_price,
                reasoning=reasoning,
                balance=new_balance,
                total_asset=new_total_asset
            )
            return {
                "status": "success",
                "action": "SELL",
                "ticker": ticker,
                "quantity": qty,
                "price": current_price,
                "reasoning": reasoning,
                "balance": new_balance,
                "total_asset": new_total_asset
            }
            
        if is_scale_out_today:
            print(f"[Trading Engine] [EX-TS] Trailing-Stop check skipped for {ticker} (Scale-out occurred today, T+0 protection active).")
            continue
            
        trailing_stop_limit = new_highest * (1 - trailing_stop_rate)
        if current_price <= trailing_stop_limit:
            qty = holding["quantity"]
            sell_qty = max(int(qty * 0.5), 1)
            remaining_qty = qty - sell_qty
            
            print(f"[Trading Engine] [EX-TS] Trailing-Stop triggered for {ticker}! Mode={mode}, Price {current_price:,.0f} <= Limit {trailing_stop_limit:,.0f} KRW (Highest: {new_highest:,.0f}). Selling 50% ({sell_qty}/{qty} shares).")
            
            total_sell_val = sell_qty * current_price
            fee_rate = 0.001
            tx_fee = total_sell_val * fee_rate
            new_balance = balance + (total_sell_val - tx_fee)
            
            if current_price > avg_price:
                prefix = "기계적 추적손절매 익절"
            elif current_price < avg_price:
                prefix = "기계적 손절(TS)"
            else:
                prefix = "본전 청산"

            if remaining_qty > 0:
                update_portfolio_holding_in_db(ticker, remaining_qty, avg_price, highest_price_after_buy=current_price, mode=mode, last_scale_out_date=today_str)
                reasoning = f"[{prefix} (50% 분할 매도)] 주가가 매수 후 최고점({new_highest:,.0f}원) 대비 트레일링 스탑 한계선({trailing_stop_limit:,.0f}원) 이하로 하락하여, 보유 수량의 50%({sell_qty}주)를 분할 매도 처리하였습니다. 남은 물량({remaining_qty}주)에 대해서는 당일(T+0) 트레일링 스탑 평가가 정지되며 현재가({current_price:,.0f}원) 기준으로 다시 고점을 추적합니다. [투자모드: {mode}, 완화여부: {is_relaxed}]"
            else:
                update_portfolio_holding_in_db(ticker, 0, avg_price)
                reasoning = f"[{prefix} (전량 청산)] 주가가 매수 후 최고점({new_highest:,.0f}원) 대비 트레일링 스탑 한계선({trailing_stop_limit:,.0f}원) 이하로 하락하여, 보유 수량이 1주 이하이므로 전량 시장가 매도 처리하였습니다. [투자모드: {mode}, 완화여부: {is_relaxed}] (현재가: {current_price:,.0f}원)"

            new_total_asset = new_balance + sum(
                (p_info["quantity"] if p_tick != ticker else remaining_qty) * market_prices.get(p_tick, 0.0)
                for p_tick, p_info in portfolio.items()
            )
            update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
            
            snapshot = {
                "prev_balance": balance,
                "new_balance": new_balance,
                "prev_total_asset": prev_total_asset,
                "new_total_asset": new_total_asset,
                "transaction_fee": tx_fee,
                "latest_news_url": news_context[0].get("url", "") if news_context else "",
                "market_prices": market_prices,
                "highest_price_after_buy": new_highest,
                "mode": mode,
                "is_relaxed": is_relaxed,
                "sector_avg_change": sector_avg_change,
                "scale_out_qty": sell_qty,
                "remaining_qty": remaining_qty
            }
            
            save_transaction_to_db(ticker, "TRAILING_STOP_EXIT", sell_qty, current_price, reasoning, snapshot)
            trigger_telegram_trade_alert(
                ticker=ticker,
                action="TRAILING_STOP_EXIT",
                quantity=sell_qty,
                price=current_price,
                reasoning=reasoning,
                balance=new_balance,
                total_asset=new_total_asset
            )
            return {
                "status": "success",
                "action": "SELL",
                "ticker": ticker,
                "quantity": sell_qty,
                "price": current_price,
                "reasoning": reasoning,
                "balance": new_balance,
                "total_asset": new_total_asset
            }
    return None

def _evaluate_buy_guardrails(
    monitored_tickers, portfolio, balance, market_prices, market_indicators, 
    index_changes, usdkrw_price, usdkrw_change_pct, usdkrw_disparity, 
    kospi_disparity, kosdaq_disparity, is_downtrend, config, news_context, now,
    macro_state: str = "NORMAL",
    kospi_ewma_vol: float = 1.2
) -> dict:
    blocked_buy_reasons = {}
    total_asset = balance + sum(p.get("quantity", 0) * market_prices.get(t, 0.0) for t, p in portfolio.items())

    # Compile sector weights
    sector_values = {}
    for t, holding in portfolio.items():
        qty = holding.get("quantity", 0)
        if qty > 0:
            price = market_prices.get(t, 0.0)
            val = qty * price
            sect = TICKER_TO_SECTOR.get(t, "기타")
            sector_values[sect] = sector_values.get(sect, 0.0) + val

    sector_weights = {}
    for sect, val in sector_values.items():
        sector_weights[sect] = (val / total_asset) if total_asset > 0 else 0.0

    for ticker in monitored_tickers:
        curr_price = market_prices.get(ticker, 0.0)
        if curr_price <= 0:
            blocked_buy_reasons[ticker] = "실시간 시세 조회가 불가능합니다."
            continue

        last_exit = get_last_sell_transaction(ticker)
        if last_exit and last_exit.get("action") in ["STOP_LOSS_EXIT", "TRAILING_STOP_EXIT"]:
            try:
                last_time = datetime.fromisoformat(last_exit["timestamp"]).replace(tzinfo=None)
                time_diff = now.replace(tzinfo=None) - last_time
                if time_diff < timedelta(minutes=120):
                    blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 청산 후 쿨다운] 직전 손절/트레일링스탑 청산({last_exit['action']}) 후 120분 재매수 제한(쿨타임)이 진행 중입니다. (남은 시간: {120 - time_diff.total_seconds() / 60:.1f}분)"
                    continue
            except Exception as e:
                print(f"[Trading Engine] Failed to evaluate cooldown for {ticker}: {e}")

        # [수정됨] 분할 매수 (물타기/불타기) 가드레일 강화 (개별 종목 20일 변동성 및 RSI를 기반으로 동적 스케일링)
        last_tx = get_last_transaction_of_ticker(ticker)
        if last_tx and last_tx.get("action") == "BUY":
            try:
                last_price = float(last_tx.get("price", 0.0))
                last_time = datetime.fromisoformat(last_tx["timestamp"]).replace(tzinfo=None)
                time_diff = now.replace(tzinfo=None) - last_time
                
                # 20일 일일 수익률 변동성 및 RSI 가져오기 (기본값 각각 2.0%, 50.0)
                vol_20d = market_indicators.get(ticker, {}).get("volatility_20d", 2.0)
                if vol_20d is None or not isinstance(vol_20d, (int, float)) or vol_20d != vol_20d or vol_20d <= 0.0:
                    vol_20d = 2.0
                ticker_rsi = market_indicators.get(ticker, {}).get("rsi", 50.0)
                if ticker_rsi is None or not isinstance(ticker_rsi, (int, float)) or ticker_rsi != ticker_rsi:
                    ticker_rsi = 50.0
                
                # 지수 변동성에 연동하여 최소 대기 시간 동적 조정 (평균 1.2% 기준, 최대 240분 제한)
                cooldown_mult = max(1.0, min(2.0, kospi_ewma_vol / 1.2))
                cooldown_minutes = int(120 * cooldown_mult)
                time_ok = time_diff >= timedelta(minutes=cooldown_minutes)
                
                is_downside = curr_price < last_price
                if is_downside:
                    # 물타기(Averaging Down): 낙폭 + RSI 과매도(35 이하) 조건 '동시' 만족 시에만 허용
                    averaging_down_pct = max(1.5, 1.5 * vol_20d)
                    price_dropped_enough = curr_price <= last_price * (1.0 - averaging_down_pct / 100.0)
                    rsi_oversold = ticker_rsi <= 35.0
                    price_ok = price_dropped_enough and rsi_oversold
                else:
                    # 불타기(Pyramiding): 돌파 시 RSI가 과매수(70 이상)가 아닐 때만 허용
                    pyramiding_pct = max(1.2, 1.2 * vol_20d)
                    price_surged_enough = curr_price >= last_price * (1.0 + pyramiding_pct / 100.0)
                    rsi_not_overbought = ticker_rsi < 70.0
                    price_ok = price_surged_enough and rsi_not_overbought
                
                if not (time_ok and price_ok):
                    reasons = []
                    if not time_ok:
                        reasons.append(f"시간 대기 미달: {time_diff.total_seconds() / 60:.1f}분 (최소 {cooldown_minutes}분 필요)")
                    if not price_ok:
                        if is_downside:
                            reasons.append(f"물타기 조건 미달: 낙폭 {(curr_price-last_price)/last_price*100:+.2f}% (요구: -{averaging_down_pct:.2f}%), RSI {ticker_rsi:.1f} (요구: 35.0 이하)")
                        else:
                            reasons.append(f"불타기 조건 미달: 돌파 {(curr_price-last_price)/last_price*100:+.2f}% (요구: +{pyramiding_pct:.2f}%), RSI {ticker_rsi:.1f} (요구: 70.0 미만)")
                    
                    blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 스마트 분할매수 가드레일] {', '.join(reasons)}"
                    continue
            except Exception as e:
                print(f"[Trading Engine] Failed to evaluate split-buy guardrail for {ticker}: {e}")

        is_usdkrw_surge = (usdkrw_price >= 1400.0) and (usdkrw_change_pct >= 1.0 or usdkrw_disparity >= 102.0)
        if is_usdkrw_surge:
            blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 매크로 불안] USD/KRW 환율({usdkrw_price:,.2f}원)이 1,400원을 돌파하고 급등(전일대비: {usdkrw_change_pct:+.2f}%, 이격도: {usdkrw_disparity:.1f}%) 중이므로 신규 매수가 차단됩니다."
            continue

        risk_profile = config.get("risk_profile", 3)
        disparity_limits = {1: 98.0, 2: 97.0, 3: 95.0, 4: 93.0, 5: 90.0}
        disp_limit = disparity_limits.get(risk_profile, 95.0)

        ticker_market = market_indicators.get(ticker, {}).get("market", "KOSPI")
        market_change = index_changes.get(ticker_market, 0.0)
        market_disp = kospi_disparity if ticker_market == "KOSPI" else kosdaq_disparity
        is_market_crash = (market_change <= -1.5) or (market_disp <= disp_limit)
        is_macro_bypass = macro_state in ["CONTRARIAN_VALUE_BUY", "CONSERVATIVE_BUY", "V_SHAPE_REBOUND_BUY"]
        
        if is_market_crash and not is_macro_bypass:
            rsi_val = market_indicators.get(ticker, {}).get("rsi", 50.0)
            rsi_prev = market_indicators.get(ticker, {}).get("rsi_prev", 50.0)
            daily_change_pct = market_indicators.get(ticker, {}).get("daily_change_pct", 0.0)
            
            # [수정됨] 과매도 반등 요건 강화 (RSI 25 -> 30 완화하되, 확실한 상승 반전 확인)
            is_rebound = (rsi_val <= 30.0) and (rsi_val > rsi_prev) and (daily_change_pct >= 1.0)
            
            if is_rebound:
                print(f"[Trading Engine] Exception Triggered: Oversold Rebound for {ticker}. Bypassing market crash guardrail.")
            else:
                blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 매크로 불안] 지수 약세(당일 {market_change:+.2f}%, 20MA 이격 {market_disp:.1f}%). 반등 시그널 없음."
                continue
                
        elif is_market_crash and is_macro_bypass:
            if macro_state == "CONTRARIAN_VALUE_BUY":
                rsi_val = market_indicators.get(ticker, {}).get("rsi", 50.0)
                rsi_prev = market_indicators.get(ticker, {}).get("rsi_prev", 50.0)
                
                # [수정됨] 떨어지는 칼날 완벽 방지: RSI가 35 미만이면서, 전일보다 하락중이면 절대 진입 불가 (지하실 파고드는 중)
                if rsi_val < 35.0 and rsi_val <= rsi_prev:
                    blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 떨어지는 칼날 방지] RSI({rsi_val:.1f})가 하락 진행 중. 바닥 확인 전까지 역발상 매수 차단."
                    continue
            print(f"[Trading Engine] Contrarian/Conservative Macro State ({macro_state}) bypasses crash guardrail for {ticker}.")

        ticker_news = []
        for n in news_context:
            try:
                tickers_list = json.loads(n.get("impacted_tickers") or "[]")
                if ticker in tickers_list:
                    ticker_news.append(n)
            except:
                pass
        if ticker_news:
            avg_sent = sum(n.get("sentiment_score", 0.0) for n in ticker_news) / len(ticker_news)
            if avg_sent <= -0.3:
                blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 시장 투심 악화] 종목 관련 최신 뉴스 감성 평균 점수가 {avg_sent:+.2f}로 악재 편향되어 있어 신규 매수가 차단됩니다."
                continue

        frgn_net_5d = market_indicators.get(ticker, {}).get("frgn_net_5d", 0)
        inst_net_5d = market_indicators.get(ticker, {}).get("inst_net_5d", 0)
        avg_vol_5d = market_indicators.get(ticker, {}).get("avg_volume_5d", 0)
        if frgn_net_5d < 0 and inst_net_5d < 0:
            combined_net_sell = abs(frgn_net_5d + inst_net_5d)
            if combined_net_sell > (avg_vol_5d * 0.5):
                blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 수급 폭락] 최근 5일간 외인({frgn_net_5d:+,}주)과 기관({inst_net_5d:+,}주)의 동시 대규모 순매도 합산량({combined_net_sell:,}주)이 5일 평균 거래량의 50%를 초과하는 수급 이탈 상태이므로 신규 매수가 차단됩니다."
                continue

        ma_20 = market_indicators.get(ticker, {}).get("ma_20", 0.0)
        volume_ratio = market_indicators.get(ticker, {}).get("volume_ratio", 1.0)
        if ma_20 > 0 and curr_price < ma_20 and volume_ratio < 1.0:
            blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 모멘텀 붕괴] 주가가 20일 이동평균선({ma_20:,.0f}원) 아래에서 거래량 없이 흘러내리는(거래량 비율: {volume_ratio:.2f}x) 떨어지는 칼날 상태이므로 신규 매수가 차단됩니다."
            continue

        ticker_sector = TICKER_TO_SECTOR.get(ticker, "기타")
        if sector_weights.get(ticker_sector, 0.0) >= 0.50:
            blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 포트폴리오 비중 초과] 해당 섹터({ticker_sector})의 포트폴리오 비중({sector_weights[ticker_sector]*100:.1f}%)이 한계치(50%)를 초과하였습니다."
            continue

        owned_qty = portfolio.get(ticker, {}).get("quantity", 0)
        if owned_qty > 0:
            owned_val = owned_qty * curr_price
            stock_weight = owned_val / total_asset
            if stock_weight >= 0.30:
                blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 포트폴리오 비중 초과] 해당 종목의 포트폴리오 비중({stock_weight*100:.1f}%)이 개별 종목 한계치(30%)를 초과하였습니다."
                continue

        if owned_qty <= 0:
            last_sell = get_last_sell_transaction(ticker)
            if last_sell:
                try:
                    last_price = float(last_sell["price"])
                    min_whipsaw = last_price * 0.90
                    max_whipsaw = last_price * 1.05
                    if min_whipsaw <= curr_price <= max_whipsaw:
                        blocked_buy_reasons[ticker] = f"[Python 시스템 차단: 휩쏘 방지] 직전 매도 가격({last_price:,.0f}원) 대비 휩쏘 방지 범위 [-10%, +5%] ({min_whipsaw:,.0f}원 ~ {max_whipsaw:,.0f}원) 내에서 주가가 횡보 중이므로 재진입이 차단됩니다. (현재가: {curr_price:,.0f}원)"
                except Exception as ex:
                    print(f"[Trading Engine] Failed to evaluate whipsaw cooldown for {ticker}: {ex}")

    return blocked_buy_reasons

def _formulate_decision(
    monitored_tickers, portfolio, balance, market_prices, market_indicators, 
    index_changes, news_context, blocked_buy_reasons, kospi_disparity, 
    kospi_change, macro_state
) -> TradingDecision:
    has_active_holdings = any(h.get("quantity", 0) > 0 for h in portfolio.values())
    all_monitored_blocked = all(ticker in blocked_buy_reasons for ticker in monitored_tickers)
    
    if (not has_active_holdings and all_monitored_blocked) or macro_state == "HARD_NO_BUY":
        print("[Trading Engine] OPTIMIZATION: Skipping Gemini API call.")
        first_blocked_ticker = monitored_tickers[0] if monitored_tickers else "005930"
        
        if macro_state == "HARD_NO_BUY":
            reasoning = f"[Python 시스템 차단: HARD_NO_BUY] KOSPI 이격도({kospi_disparity:.2f}%) 및 당일 변동률({kospi_change:+.2f}%)이 심각한 약세장 기준에 도달하여 신규 매수가 전면 금지되고 관망(HOLD) 상태를 강제 유지합니다. 기존 보유분은 기계적 손절매/추적청산으로만 대응합니다."
        else:
            first_reason = blocked_buy_reasons.get(first_blocked_ticker, "매수 제한")
            reasoning = f"[Python 시스템 차단: API 호출 최적화] 현재 포트폴리오가 비어 있고 모든 거래 후보 종목이 매수 제한 상태이므로 Gemini API 호출을 스킵하고 기계적으로 관망(HOLD) 결정을 실행합니다. (대표 사유: {first_reason})"
            
        return TradingDecision(
            action="HOLD",
            ticker=first_blocked_ticker,
            allocation_pct=0.0,
            reasoning=reasoning,
            mode="VALUE",
            win_probability=0.5,
            reward_to_risk_ratio=1.0
        )
    else:
        return generate_trading_decision(
            portfolio=portfolio,
            balance=balance,
            market_prices=market_prices,
            news_context=news_context,
            market_indicators=market_indicators,
            index_changes=index_changes,
            blocked_buy_reasons=blocked_buy_reasons
        )

def _execute_trading_decision(
    decision, portfolio, balance, market_prices, market_indicators, 
    index_changes, news_context, blocked_buy_reasons, prev_total_asset, 
    config, is_downtrend, kospi_disparity, kospi_change, macro_state, now
) -> dict:
    action = decision.action
    ticker = decision.ticker
    allocation_pct = decision.allocation_pct
    reasoning = decision.reasoning
    
    if action == "HOLD" and not reasoning.startswith("["):
        reasoning = f"[Gemini AI 자체 관망] {reasoning}"
        
    current_price = market_prices.get(ticker, 0.0)
    
    quantity = 0
    transaction_fee = 0.0
    fee_rate = 0.001
    risk_profile = config.get("risk_profile", 3)

    # Compile portfolio value at current prices
    portfolio_value = sum(
        portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) 
        for t in portfolio
    )
    total_asset = balance + portfolio_value
    expected_prev_total_asset_at_current_prices = total_asset

    if action == "BUY":
        disparity = market_indicators.get(ticker, {}).get("disparity", 100.0) if ticker else 100.0
        
        has_bad_news = False
        bad_news_reason = ""
        ticker_news = []
        for n in news_context:
            try:
                tickers_list = json.loads(n.get("impacted_tickers") or "[]")
                if ticker in tickers_list:
                    ticker_news.append(n)
            except:
                pass
                
        if ticker_news:
            avg_sent = sum(n.get("sentiment_score", 0.0) for n in ticker_news) / len(ticker_news)
            if avg_sent <= -0.3:
                has_bad_news = True
                bad_news_reason = f"최근 24시간 감성 점수 극도 악재 ({avg_sent:+.2f})"
        
        ticker_market = market_indicators.get(ticker, {}).get("market", "KOSPI") if ticker else "KOSPI"
        market_change = index_changes.get(ticker_market, 0.0)
        is_ticker_market_shock = market_change <= -1.5
        shock_reason = f"소속 거래소: {ticker_market} | 지수 당일 등락률: {market_change:+.2f}%"

        frgn_net_5d = market_indicators.get(ticker, {}).get("frgn_net_5d", 0)
        inst_net_5d = market_indicators.get(ticker, {}).get("inst_net_5d", 0)
        avg_vol_5d = market_indicators.get(ticker, {}).get("avg_volume_5d", 0)
        
        is_sugeup_dump = False
        combined_net_sell = 0
        if frgn_net_5d < 0 and inst_net_5d < 0:
            combined_net_sell = abs(frgn_net_5d + inst_net_5d)
            if combined_net_sell > (avg_vol_5d * 0.5):
                is_sugeup_dump = True

        if ticker in blocked_buy_reasons:
            print(f"[Trading Engine] BUY Order Overridden by risk guardrail: {blocked_buy_reasons[ticker]}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 리스크 가드레일] Gemini AI가 매수를 결정했으나 {blocked_buy_reasons[ticker]} 사유로 인해 가드레일 필터가 작동하여 HOLD 처리했습니다."
        elif has_bad_news:
            print(f"[Trading Engine] BUY Order Overridden by bad news: {bad_news_reason}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 종목 뉴스 악재] Gemini AI가 매수를 결정했으나 {bad_news_reason} 사유로 인해 가드레일 필터가 작동하여 HOLD 처리했습니다."
        elif is_ticker_market_shock:
            print(f"[Trading Engine] BUY Order Overridden by market shock: {shock_reason}")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 시장 쇼크] Gemini AI가 매수를 결정했으나 해당 종목 거래소({ticker_market}) 급락 쇼크 경보가 작동({shock_reason})하여 HOLD 처리했습니다."
        elif is_sugeup_dump:
            print(f"[Trading Engine] BUY Order Overridden by sugeup dump: {combined_net_sell} shares sold.")
            action = "HOLD"
            reasoning = f"[백엔드 규칙 기각: 수급 폭락] Gemini AI가 매수를 결정했으나 최근 5일간 외국인({frgn_net_5d:+,}주)과 기관({inst_net_5d:+,}주)의 동시 순매도 합산량({combined_net_sell:,}주)이 5일 평균 거래량({avg_vol_5d:,.0f}주)의 50%를 초과하는 수급 폭락 상태이므로 대방어 기각 규칙이 작동하여 HOLD 처리했습니다."
        else:
            win_p = getattr(decision, "win_probability", 0.5)
            r_r = getattr(decision, "reward_to_risk_ratio", 1.0)
            if r_r <= 0.0:
                r_r = 0.1
            expectation = win_p - (1.0 - win_p) / r_r
            
            kelly_multipliers = {1: 0.25, 2: 0.35, 3: 0.50, 4: 0.75, 5: 1.00}
            kelly_multiplier = kelly_multipliers.get(risk_profile, 0.50)
            half_kelly = kelly_multiplier * expectation
            
            if expectation <= 0.0:
                action = "HOLD"
                reasoning = f"[Kelly 가드레일 기각: 기대치 음수] 기대치(기대 승률 {win_p:.1%}, 손익비 {r_r:.1f})가 음수여서 자산 보호를 위해 매수를 기각하고 HOLD 처리했습니다."
                quantity = 0
                spend_cash = 0.0
            else:
                allocated_cash = balance * (allocation_pct / 100.0)
                allocated_cash *= half_kelly
                
                max_order_cash = total_asset * 0.10
                
                max_allowed_cash_ratio = 0.15 if is_downtrend else 0.30
                max_allowed_cash = total_asset * max_allowed_cash_ratio
                
                owned_value = portfolio.get(ticker, {}).get("quantity", 0) * current_price
                max_new_cash = max(max_allowed_cash - owned_value, 0.0)
                
                spend_cash = min(allocated_cash, max_order_cash, max_new_cash)
                
                # [고도화] 변동성 조절 사이징 (Volatility-Targeting Sizing)
                # 기준 종목 일일 변동성 = 2.0%. 기준 KOSPI 일일 변동성 = 1.2%
                vol_20d = market_indicators.get(ticker, {}).get("volatility_20d", 2.0)
                if vol_20d is None or not isinstance(vol_20d, (int, float)) or vol_20d != vol_20d or vol_20d <= 0.0:
                    vol_20d = 2.0
                kospi_vol = market_context.get("kospi_ewma_vol", 1.2)
                
                vol_factor = 2.0 / vol_20d
                kospi_vol_factor = 1.2 / kospi_vol
                sizing_mult = min(1.0, vol_factor) * min(1.0, kospi_vol_factor)
                
                if sizing_mult < 1.0:
                    spend_cash *= sizing_mult
                    print(f"[{ticker}] Volatility Sizing Activated: scaled cash by {sizing_mult:.2f}x (Stock Vol: {vol_20d:.2f}%, KOSPI Vol: {kospi_vol:.2f}%)")
                sizing_triggered = allocated_cash > max_new_cash
                order_limit_triggered = allocated_cash > max_order_cash
                
                bear_triggered = False
                if macro_state == "HARD_NO_BUY":
                    spend_cash = 0.0
                    bear_triggered = True
                    print(f"[{ticker}] 매크로 시스템 경보(HARD_NO_BUY) 작동: 매수 한도를 0원으로 강제 제한합니다.")
                elif macro_state in ["CONTRARIAN_VALUE_BUY", "V_SHAPE_REBOUND_BUY"]:
                    # [반영] 2026-07-20 피드백 제안: 역발상 분할 매수 구간(CONTRARIAN_VALUE_BUY, V_SHAPE_REBOUND_BUY)에서는 투자 비중을 30%(0.3x)로 제한하여 분할 매수로 대응
                    spend_cash *= 0.3
                    bear_triggered = True
                    print(f"[{ticker}] 역발상 분할 매수 구간({macro_state}) 작동: 투자 비중을 30%(0.3x)로 제한하여 분할 매수를 집행합니다.")
                else:
                    if is_kospi_bear_market():
                        spend_cash *= 0.3
                        bear_triggered = True
                    
                disparity_50_triggered = False
                if 108.0 <= disparity < 115.0:
                    spend_cash *= 0.3
                    disparity_50_triggered = True

                target_sector = TICKER_TO_SECTOR.get(ticker, "기타")
                current_sector_value = sum(
                    info.get("quantity", 0) * market_prices.get(t, 0.0)
                    for t, info in portfolio.items()
                    if TICKER_TO_SECTOR.get(t, "기타") == target_sector
                )
                max_sector_ratio = 0.20 if is_downtrend else 0.50
                max_sector_allowed_value = total_asset * max_sector_ratio
                max_additional_sector_cash = max(max_sector_allowed_value - current_sector_value, 0.0)
                
                sector_cap_triggered = False
                if spend_cash > max_additional_sector_cash:
                    spend_cash = max_additional_sector_cash
                    sector_cap_triggered = True
                    
                vol_stop = get_stock_volatility_multiplier(ticker, fallback_vol=0.045)
                risk_parity_cash = (total_asset * 0.0125) / vol_stop
                risk_parity_triggered = False
                if spend_cash > risk_parity_cash:
                    spend_cash = risk_parity_cash
                    risk_parity_triggered = True
                    
                min_cash_reserves = {
                    1: (0.50, 0.20), 2: (0.45, 0.15), 3: (0.40, 0.10), 4: (0.30, 0.05), 5: (0.10, 0.00)
                }
                bear_cash, bull_cash = min_cash_reserves.get(risk_profile, (0.40, 0.10))
                min_cash_ratio = bear_cash if is_downtrend else bull_cash
                max_spend_due_to_cash_reserve = max(balance - (total_asset * min_cash_ratio), 0.0)
                cash_reserve_triggered = False
                if spend_cash > max_spend_due_to_cash_reserve:
                    spend_cash = max_spend_due_to_cash_reserve
                    cash_reserve_triggered = True

                rsi_val = market_indicators.get(ticker, {}).get("rsi", 50.0)
                rsi_prev = market_indicators.get(ticker, {}).get("rsi_prev", 50.0)
                daily_change = market_indicators.get(ticker, {}).get("daily_change_pct", 0.0)
                is_rsi_rebound_triggered = (rsi_val <= 25 or rsi_prev <= 25) and (daily_change >= 1.5 and (rsi_val - rsi_prev) >= 1.5)
                
                rsi_rebound_cap_triggered = False
                if is_rsi_rebound_triggered:
                    max_rebound_cash = balance * 0.02
                    if spend_cash > max_rebound_cash:
                        spend_cash = max_rebound_cash
                        rsi_rebound_cap_triggered = True

                is_recovery_phase = (not is_ticker_market_shock and not is_sugeup_dump) and (kospi_disparity < 100.0)
                recovery_cap_triggered = False
                if is_recovery_phase and not is_rsi_rebound_triggered:
                    max_recovery_cash = balance * 0.15
                    if spend_cash > max_recovery_cash:
                        spend_cash = max_recovery_cash
                        recovery_cap_triggered = True

                quantity = int(spend_cash / (current_price * (1 + fee_rate)))
                
                gate_reasons = []
                profile_names = {1: "극단안정", 2: "안정", 3: "중립", 4: "공격", 5: "극단공격"}
                p_name = profile_names.get(risk_profile, "중립")
                gate_reasons.append(f"[{p_name}] 켈리비율 {half_kelly:.2f}배")
                if order_limit_triggered:
                    gate_reasons.append("1회 주문 10% 제한")
                if sizing_triggered:
                    gate_reasons.append(f"보유 한도 {max_allowed_cash_ratio*100:.0f}% 제한")
                if bear_triggered:
                    gate_reasons.append("약세장 방어")
                if disparity_50_triggered:
                    gate_reasons.append("이격 과열 50% 감폭")
                if sector_cap_triggered:
                    gate_reasons.append(f"섹터 비중 {max_sector_ratio*100:.0f}% 제한")
                if risk_parity_triggered:
                    gate_reasons.append(f"변동성 리스크 리미트(최대 손실 1.25% 제한)")
                if cash_reserve_triggered:
                    gate_reasons.append(f"예수금 {min_cash_ratio*100:.0f}% 의무 적립 적용")
                if rsi_rebound_cap_triggered:
                    gate_reasons.append("극단침체 RSI 반등 분할매수 2% 한도 제한")
                if recovery_cap_triggered:
                    gate_reasons.append("가드레일 해제 회복 과도기 분할매수 15% 한도 적용")
                    
                if gate_reasons:
                    reasoning += f" [가드레일 작동: {', '.join(gate_reasons)}]"
                    
                if quantity <= 0:
                    action = "HOLD"
                    if sector_cap_triggered:
                        reasoning += f" (섹터 비중 {max_sector_ratio*100:.0f}% 초과로 인해 HOLD 처리됨)"
                    elif cash_reserve_triggered:
                        reasoning += f" (예수금 {min_cash_ratio*100:.0f}% 보존 규칙 충족을 위한 가용자금 부족으로 HOLD 처리됨)"
                    else:
                        reasoning += " (매수 가용 자금 또는 수량 부족으로 HOLD 처리됨)"

    elif action == "SELL":
        owned_quantity = portfolio.get(ticker, {}).get("quantity", 0)
        quantity = int(owned_quantity * (allocation_pct / 100.0))
        if quantity <= 0:
            action = "HOLD"
            reasoning += " (매도 가능 수량 부족으로 HOLD 처리됨)"

    if action in ["BUY", "SELL"] and (current_price <= 0 or not ticker or quantity <= 0):
        if action in ["BUY", "SELL"]:
            print(f"[Trading Engine] Order Rejected: Price for ticker {ticker} is invalid or quantity is 0.")
            action = "HOLD"
            reasoning = f"시스템오류: 종목코드 {ticker}의 시세 조회가 불가능하거나 거래 수량이 0이어서 HOLD 처리했습니다."
            quantity = 0

    if action == "BUY" and quantity > 0:
        required_cash = quantity * current_price * (1 + fee_rate)
        if required_cash > balance:
            print(f"[Trading Engine] REJECTED_BY_BACKEND: BUY order of {quantity} shares of {ticker} requires {required_cash:,.0f} KRW but balance is only {balance:,.0f} KRW.")
            action = "HOLD"
            reasoning = f"REJECTED_BY_BACKEND: 매입 필요 자금({required_cash:,.0f}원)이 가용 예수금({balance:,.0f}원)을 초과하여 주문이 거부되었습니다."
            quantity = 0
            
    elif action == "SELL" and quantity > 0:
        owned_quantity = portfolio.get(ticker, {}).get("quantity", 0)
        if quantity > owned_quantity:
            print(f"[Trading Engine] REJECTED_BY_BACKEND: SELL order of {quantity} shares of {ticker} exceeds owned quantity ({owned_quantity} shares).")
            action = "HOLD"
            reasoning = f"REJECTED_BY_BACKEND: 매도 요청 수량({quantity}주)이 실제 보유 수량({owned_quantity}주)을 초과하여 주문이 거부되었습니다."
            quantity = 0

    new_balance = balance
    new_portfolio = {t: dict(info) for t, info in portfolio.items()}

    if action == "BUY" and quantity > 0:
        total_buy_cost = quantity * current_price
        transaction_fee = total_buy_cost * fee_rate
        
        new_balance = balance - (total_buy_cost + transaction_fee)
        
        current_holding = portfolio.get(ticker, {"quantity": 0, "average_price": 0.0})
        prev_qty = current_holding["quantity"]
        prev_avg = current_holding["average_price"]
        
        new_qty = prev_qty + quantity
        new_avg = ((prev_qty * prev_avg) + (quantity * current_price)) / new_qty
        
        new_portfolio[ticker] = {
            "quantity": new_qty,
            "average_price": new_avg,
            "highest_price_after_buy": max(current_price, current_holding.get("highest_price_after_buy", current_price)),
            "mode": decision.mode,
            "last_scale_out_date": current_holding.get("last_scale_out_date")
        }
        
        update_portfolio_holding_in_db(ticker, new_qty, new_avg, new_portfolio[ticker]["highest_price_after_buy"], mode=decision.mode, last_scale_out_date=new_portfolio[ticker]["last_scale_out_date"])

    elif action == "SELL" and quantity > 0:
        total_sell_val = quantity * current_price
        transaction_fee = total_sell_val * fee_rate
        
        new_balance = balance + (total_sell_val - transaction_fee)
        
        current_holding = portfolio.get(ticker, {"quantity": 0, "average_price": 0.0})
        prev_qty = current_holding["quantity"]
        prev_avg = current_holding["average_price"]
        
        new_qty = prev_qty - quantity
        
        if new_qty <= 0:
            if ticker in new_portfolio:
                del new_portfolio[ticker]
        else:
            new_portfolio[ticker] = {
                "quantity": new_qty,
                "average_price": prev_avg,
                "highest_price_after_buy": current_holding.get("highest_price_after_buy", current_price),
                "mode": current_holding.get("mode", "VALUE"),
                "last_scale_out_date": current_holding.get("last_scale_out_date")
            }
            
        update_portfolio_holding_in_db(ticker, new_qty, prev_avg, current_holding.get("highest_price_after_buy", current_price), mode=current_holding.get("mode", "VALUE"), last_scale_out_date=current_holding.get("last_scale_out_date"))

    new_portfolio_value_at_current_prices = sum(
        new_portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) 
        for t in new_portfolio
    )
    new_total_asset = new_balance + new_portfolio_value_at_current_prices

    expected_new_total_asset = expected_prev_total_asset_at_current_prices - transaction_fee
    accounting_discrepancy = abs(new_total_asset - expected_new_total_asset)

    print(f"[Trading Engine] Accounting Check: Calculated New Asset = {new_total_asset:,.2f} KRW | Expected New Asset = {expected_new_total_asset:,.2f} KRW")
    
    if accounting_discrepancy > 10.0 or new_balance < 0:
        error_msg = f"CRITICAL_ACCOUNTING_FAULT: Discrepancy of {accounting_discrepancy:,.2f} KRW detected or Negative Balance ({new_balance:,.2f} KRW) reached! Mathematical safety breach."
        print(f"[Trading Engine] {error_msg}")
        lock_system()
        save_transaction_to_db(
            ticker=ticker,
            action="SYSTEM_LOCK_ERROR",
            quantity=quantity,
            price=current_price,
            reasoning=error_msg,
            snapshot_context={
                "prev_balance": balance,
                "new_balance": new_balance,
                "discrepancy": accounting_discrepancy,
                "expected_new_total_asset": expected_new_total_asset,
                "new_total_asset": new_total_asset
            }
        )
        sys.exit(error_msg)

    update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
    
    snapshot_context = {
        "prev_balance": balance,
        "new_balance": new_balance,
        "prev_total_asset": prev_total_asset,
        "new_total_asset": new_total_asset,
        "transaction_fee": transaction_fee,
        "latest_news_url": news_context[0].get("url", "") if news_context else "",
        "market_prices": market_prices,
        "mode": decision.mode if action == "BUY" else (portfolio.get(ticker, {}).get("mode", "VALUE") if ticker in portfolio else "VALUE")
    }
    
    save_transaction_to_db(
        ticker=ticker,
        action=action,
        quantity=quantity,
        price=current_price,
        reasoning=reasoning,
        snapshot_context=snapshot_context
    )

    if action in ["BUY", "SELL"]:
        trigger_telegram_trade_alert(
            ticker=ticker,
            action=action,
            quantity=quantity,
            price=current_price,
            reasoning=reasoning,
            balance=new_balance,
            total_asset=new_total_asset
        )

    return {
        "status": "success",
        "action": action,
        "ticker": ticker,
        "quantity": quantity,
        "price": current_price,
        "reasoning": reasoning,
        "balance": new_balance,
        "total_asset": new_total_asset
    }

def run_simulation_cycle(bypass_hours: bool = False) -> dict:
    """
    Executes a single end-to-end trading simulation cycle.
    Modular Orchestrator.
    """
    # 1. Load config and check eligibility
    eligibility = _load_config_and_check_eligibility(bypass_hours)
    if "status" in eligibility and eligibility["status"] in ["error", "skipped"]:
        return eligibility

    config = eligibility["config"]
    portfolio = eligibility["portfolio"]
    news_context = eligibility["news_context"]
    balance = eligibility["balance"]
    prev_total_asset = eligibility["prev_total_asset"]
    now = eligibility["now"]
    last_txs = eligibility["last_txs"]

    # 2. Fetch market index changes, trends, and disparities
    market_context = _fetch_market_indices_and_trends(now)
    index_changes = market_context["index_changes"]
    usdkrw_price = market_context["usdkrw_price"]
    usdkrw_change_pct = market_context["usdkrw_change_pct"]
    usdkrw_disparity = market_context["usdkrw_disparity"]
    kospi_disparity = market_context["kospi_disparity"]
    kosdaq_disparity = market_context["kosdaq_disparity"]
    is_downtrend = market_context["is_downtrend"]

    # 3. Filter monitored tickers and fetch prices/indicators in parallel
    monitored_tickers = get_active_tickers(portfolio, news_context)
    monitored_tickers, pre_blocked_reasons = _apply_preflight_cooldown_filters(monitored_tickers, portfolio, now)

    market_indicators, market_prices = _fetch_prices_and_indicators(monitored_tickers)

    # 4. Check technical trigger & news idempotency cooldowns
    idempotency = _check_technical_and_news_idempotency(market_indicators, news_context, last_txs, bypass_hours)
    if idempotency:
        return idempotency

    # 5. Check macro circuit breakers
    kospi_change = index_changes.get("KOSPI", 0.0)
    macro_state = evaluate_macro_circuit_breaker(
        kospi_disparity, 
        kospi_change,
        kospi_rsi=market_context.get("kospi_rsi", 50.0),
        disparity_mean=market_context.get("kospi_disparity_mean", 100.0),
        disparity_std=market_context.get("kospi_disparity_std", 3.0)
    )
    circuit_breaker_result = _handle_macro_circuit_breaker_liquidation(
        macro_state, portfolio, balance, market_prices, kospi_disparity, kospi_change
    )
    if circuit_breaker_result:
        return circuit_breaker_result

    # 6. Evaluate mechanical Stop-Loss and Trailing-Stop
    exit_result = _evaluate_mechanical_exits(
        portfolio, balance, market_prices, market_indicators, is_downtrend, kospi_change, news_context, prev_total_asset
    )
    if exit_result:
        return exit_result

    # [HARD_NO_BUY: Minor Position Liquidation check]
    # In the original code, this was run if macro_state == "HARD_NO_BUY".
    # Since we want to preserve exact behavior, we call the minor position liquidation logic here.
    if macro_state == "HARD_NO_BUY":
        # Calculate current total asset
        portfolio_value = sum(portfolio.get(t, {}).get("quantity", 0) * market_prices.get(t, 0.0) for t in portfolio)
        total_asset = balance + portfolio_value
        
        liquidated_tickers = []
        total_sell_val = 0.0
        total_fee = 0.0
        for ticker, holding in list(portfolio.items()):
            qty = holding.get("quantity", 0)
            if qty <= 0:
                continue
            curr_price = market_prices.get(ticker, 0.0)
            if curr_price <= 0:
                curr_price = get_stock_price(ticker)
                
            if curr_price > 0:
                val = qty * curr_price
                weight = val / total_asset if total_asset > 0 else 0.0
                if weight < 0.05:
                    sell_val = qty * curr_price
                    fee = sell_val * 0.001
                    total_sell_val += sell_val
                    total_fee += fee
                    
                    update_portfolio_holding_in_db(ticker, 0, holding.get("average_price", 0.0))
                    
                    reasoning = f"[소액 포지션 룰베이스 청산] 시장 폭락 장세(HARD_NO_BUY, KOSPI 이격도 {kospi_disparity:.2f}%)에서 전체 자산 대비 비중이 {weight*100:.1f}%(< 5%)인 소액 보유 종목을 수수료 및 API 비용 절감을 위해 기계적으로 청산합니다."
                    snapshot = {
                        "prev_balance": balance,
                        "new_balance": balance + sell_val - fee,
                        "prev_total_asset": total_asset,
                        "new_total_asset": total_asset - fee,
                        "transaction_fee": fee,
                        "market_prices": market_prices,
                        "minor_liquidation": True
                    }
                    save_transaction_to_db(ticker, "MINOR_POSITION_LIQUIDATION", qty, curr_price, reasoning, snapshot)
                    trigger_telegram_trade_alert(
                        ticker=ticker,
                        action="MINOR_POSITION_LIQUIDATION",
                        quantity=qty,
                        price=curr_price,
                        reasoning=reasoning,
                        balance=balance + sell_val - fee,
                        total_asset=total_asset - fee
                    )
                    liquidated_tickers.append(ticker)
                    
        if liquidated_tickers:
            new_balance = balance + total_sell_val - total_fee
            for t in liquidated_tickers:
                portfolio.pop(t, None)
            portfolio_value = sum(p.get("quantity", 0) * market_prices.get(t, 0.0) for t, p in portfolio.items())
            new_total_asset = new_balance + portfolio_value
            update_agent_state_in_db(new_balance, new_total_asset, system_lock=False)
            return {
                "status": "success",
                "action": "MINOR_POSITION_LIQUIDATION",
                "message": f"Rule-based minor position cleanup executed for {', '.join(liquidated_tickers)}."
            }

    # 7. Evaluate buy guardrails
    blocked_buy_reasons = _evaluate_buy_guardrails(
        monitored_tickers, portfolio, balance, market_prices, market_indicators, 
        index_changes, usdkrw_price, usdkrw_change_pct, usdkrw_disparity, 
        kospi_disparity, kosdaq_disparity, is_downtrend, config, news_context, now,
        macro_state,
        kospi_ewma_vol=market_context.get("kospi_ewma_vol", 1.2)
    )
    # Add preflight cooldowns
    blocked_buy_reasons.update(pre_blocked_reasons)

    # 8. Formulate final decision (Gemini debate or direct HOLD fallback)
    decision = _formulate_decision(
        monitored_tickers, portfolio, balance, market_prices, market_indicators, 
        index_changes, news_context, blocked_buy_reasons, kospi_disparity, 
        kospi_change, macro_state
    )

    # 9. Execute trading decision and perform accounting validation
    return _execute_trading_decision(
        decision, portfolio, balance, market_prices, market_indicators, 
        index_changes, news_context, blocked_buy_reasons, prev_total_asset, 
        config, is_downtrend, kospi_disparity, kospi_change, macro_state, now
    )

if __name__ == "__main__":
    print("[Trading Engine] Initialized as standalone. Testing yfinance connection...")
    price = get_stock_price("005930")
    print(f"Samsung Electronics (005930) Price: {price:,.0f} KRW")
