import os
import json
import re
from typing import List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai

# Define Pydantic response models for structured outputs
class RelevanceCheck(BaseModel):
    relevant: bool = Field(description="True if the content is directly or indirectly related to South Korea's economy, financial markets, or major industries.")
    reason: str = Field(description="A brief 1-sentence reason in Korean explaining the relevance assessment.")

class DeepAnalysis(BaseModel):
    sentiment: str = Field(description="Overall sentiment towards the Korean economy or markets: POSITIVE, NEGATIVE, or NEUTRAL")
    sentiment_score: float = Field(description="Float value between -1.0 (extremely negative) and 1.0 (extremely positive)")
    relevance_score: int = Field(description="Integer between 0 and 10 indicating the importance/impact on South Korea")
    impacted_sectors: List[str] = Field(description="List of Korean business sectors/industries impacted")
    impacted_companies: List[str] = Field(description="List of Korean companies impacted (e.g. Samsung Electronics, SK Hynix)")
    impacted_tickers: List[str] = Field(description="List of corresponding 6-digit South Korean stock ticker codes (e.g. '005930' for Samsung Electronics, '000660' for SK Hynix) for the impacted companies. Enter empty list if none.")
    macro_impacts: str = Field(description="Summary of macro impacts on exchange rates, inflation, or KOSPI in Korean")
    korean_summary: str = Field(description="Clear and professional 2-3 sentence summary in Korean")
    alert_level: str = Field(description="Alert level: LOW, MEDIUM, or HIGH")



class GeminiEconomyAnalyzer:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = {}
        self.api_configured = False
        
        # Load configuration
        self.load_config()
        
        # Initialize Gemini API
        self.init_api()
        
        # Load prompt templates
        self.load_prompts()

    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                print(f"[Analyzer] Config file {self.config_path} not found. Using defaults.")
        except Exception as e:
            print(f"[Analyzer] Error loading config: {str(e)}")

    def init_api(self):
        # 1. Check environment variable first (best practice)
        api_key = os.getenv("GEMINI_API_KEY")
        
        # 2. Check config file fallback
        if not api_key:
            api_key = self.config.get("GEMINI_API_KEY")
            
        if api_key and api_key.strip():
            try:
                genai.configure(api_key=api_key.strip())
                self.api_configured = True
                print("[Analyzer] Google Gemini API successfully configured.")
            except Exception as e:
                print(f"[Analyzer] Error configuring Gemini API: {str(e)}")
        else:
            print("[Warning] GEMINI_API_KEY is empty or not set. Analyzer will run in DEMO/MOCK mode.")

    def load_prompts(self):
        # Default fallback prompts in case prompt file isn't loaded
        self.prompts = {
            "filtering": {
                "system_instruction": "You are a professional financial filtering system.",
                "prompt_template": "Analyze: Title: {title}\nContent: {content}\nIs it related to Korean economy?"
            },
            "analysis": {
                "system_instruction": "You are a world-class economic analyst for South Korea.",
                "prompt_template": "Deep analysis: Title: {title}\nContent: {content}"
            }
        }
        
        prompts_path = os.path.join(".antigravity", "prompts.json")
        if os.path.exists(prompts_path):
            try:
                with open(prompts_path, "r", encoding="utf-8") as f:
                    self.prompts = json.load(f)
                # print("[Analyzer] Loaded prompt templates from .antigravity/prompts.json")
            except Exception as e:
                print(f"[Analyzer] Error loading prompts.json: {str(e)}")

    def check_relevance(self, item: dict) -> RelevanceCheck:
        """
        Stage 1: Quick filtering using Gemini Flash to determine Korean economic relevance.
        """
        flash_model_name = self.config.get("models", {}).get("flash_model", "gemini-3.5-flash")
        
        if not self.api_configured:
            return self._mock_check_relevance(item)
            
        try:
            prompt = self.prompts["filtering"]["prompt_template"].format(
                title=item.get("title", ""),
                content=item.get("content", ""),
                source=item.get("source", "")
            )
            system_instruction = self.prompts["filtering"]["system_instruction"]
            
            model = genai.GenerativeModel(
                model_name=flash_model_name,
                system_instruction=system_instruction
            )
            
            # Explicitly build schema dict and restore required list to fix SDK popping bug
            from google.generativeai.types import content_types
            schema = content_types._schema_for_class(RelevanceCheck)
            schema["required"] = ["relevant", "reason"]
            
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=schema
                )
            )
            
            result = RelevanceCheck.model_validate_json(response.text)
            return result
        except Exception as e:
            print(f"[Analyzer] Error in Stage 1 relevance check: {str(e)}. Falling back to mock heuristic.")
            return self._mock_check_relevance(item)

    def analyze_deep(self, item: dict) -> DeepAnalysis:
        """
        Stage 2: Deep evaluation using Gemini Pro if relevance is YES.
        """
        pro_model_name = self.config.get("models", {}).get("pro_model", "gemini-3.1-pro")
        
        if not self.api_configured:
            return self._mock_analyze_deep(item)
            
        try:
            prompt = self.prompts["analysis"]["prompt_template"].format(
                title=item.get("title", ""),
                content=item.get("content", ""),
                source=item.get("source", "")
            )
            system_instruction = self.prompts["analysis"]["system_instruction"]
            
            model = genai.GenerativeModel(
                model_name=pro_model_name,
                system_instruction=system_instruction
            )
            
            # Explicitly build schema dict and restore required list to fix SDK popping bug
            from google.generativeai.types import content_types
            schema = content_types._schema_for_class(DeepAnalysis)
            schema["required"] = [
                "sentiment", "sentiment_score", "relevance_score", 
                "impacted_sectors", "impacted_companies", "impacted_tickers", 
                "macro_impacts", "korean_summary", "alert_level"
            ]
            
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=schema
                )
            )
            
            result = DeepAnalysis.model_validate_json(response.text)
            return result
        except Exception as e:
            print(f"[Analyzer] Error in Stage 2 deep analysis: {str(e)}. Falling back to mock heuristic.")
            return self._mock_analyze_deep(item)

    def check_relevance_local(self, item: dict) -> bool:
        """
        Stage 0: Local heuristic pre-filtering using target_keywords.
        Returns True if any target keyword matches the title or content.
        Uses word boundaries for purely English/alphanumeric terms to prevent false positives.
        """
        title = item.get("title", "") or ""
        content = item.get("content", "") or ""
        text = (title + " " + content).lower()
        
        keywords = self.config.get("target_keywords", [])
        if not keywords:
            # If no keywords are defined, default to True (don't filter anything locally)
            return True
            
        for kw in keywords:
            kw = kw.strip()
            if not kw:
                continue
            
            kw_lower = kw.lower()
            if kw_lower.isalnum() and kw_lower.isascii():
                # Enforce word boundaries for English terms to prevent partial substring matches (e.g. 'war' in 'software')
                pattern = r'\b' + re.escape(kw_lower) + r'\b'
                if re.search(pattern, text):
                    return True
            else:
                # Standard substring match for Korean and non-ASCII keywords
                if kw_lower in text:
                    return True
        return False

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generates a vector embedding for the given text using models/text-embedding-004.
        """
        if not self.api_configured:
            return None
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=text,
                task_type="semantic_similarity"
            )
            return result.get("embedding")
        except Exception as e:
            print(f"[Analyzer] [Error] Embedding generation failed: {e}")
            return None

    def process_item(self, item: dict) -> tuple:
        """
        Runs the 3-Stage processing:
        Stage 0: Local keyword pre-filtering.
        Stage 1: Quick filtering using Gemini Flash to determine Korean economic relevance.
        Stage 2: Deep evaluation using Gemini Pro if relevance is YES.
        
        Returns (relevance_check_obj, deep_analysis_obj_or_None)
        """
        # Stage 0: Local keyword pre-filtering to save Gemini API costs!
        if not self.check_relevance_local(item):
            reason = "로컬 사전 필터링: 주요 경제, 산업, 또는 지정학/정세 관련 핵심 키워드가 검출되지 않았습니다."
            return RelevanceCheck(relevant=False, reason=reason), None
            
        # Stage 1: Quick filtering via Gemini Flash
        rel_check = self.check_relevance(item)
        
        # Stage 2: Deep evaluation (if relevant)
        if rel_check.relevant:
            analysis = self.analyze_deep(item)
            return rel_check, analysis
        else:
            return rel_check, None

    # --- HEURISTIC MOCK FALLBACKS (For immediate E2E execution without API keys) ---
    
    def _mock_check_relevance(self, item: dict) -> RelevanceCheck:
        text = (item.get("title", "") + " " + item.get("content", "")).lower()
        keywords = self.config.get("target_keywords", [
            "korea", "samsung", "hynix", "kospi", "won", "krw", "semiconductor", "battery"
        ])
        
        relevant = False
        matched_kw = []
        for kw in keywords:
            if kw.lower() in text:
                relevant = True
                matched_kw.append(kw)
                
        if relevant:
            reason = f"글로벌 이슈 및 핵심 키워드 ({', '.join(matched_kw[:2])}) 검색 매칭에 따른 한국 경제 관련성 판별 완료 (데모 모드)."
        else:
            reason = "한국 경제 또는 주요 기업 관련 연관 키워드가 검출되지 않았습니다."
            
        return RelevanceCheck(relevant=relevant, reason=reason)

    def _mock_analyze_deep(self, item: dict) -> DeepAnalysis:
        title = item.get("title", "")
        content = item.get("content", "")
        text = (title + " " + content).lower()
        
        # Heuristics based on content
        sentiment = "NEUTRAL"
        sentiment_score = 0.0
        relevance_score = 5
        sectors = ["기타"]
        companies = []
        macro_impacts = "국내 매크로 지표 변동성 모니터링 지속 필요."
        korean_summary = f"[{title}] 기사에 대한 모니터링이 필요한 시점입니다."
        alert_level = "LOW"
        
        # 1. Semiconductors / IT
        if any(x in text for x in ["nvidia", "hbm", "semiconductor", "jensen huang", "반도체", "하이닉스", "hynix", "삼성전자", "samsung", "리벨리온", "삼전닉스"]):
            sentiment = "POSITIVE" if not any(y in text for y in ["우려", "악재", "소외"]) else "NEUTRAL"
            sentiment_score = 0.8 if sentiment == "POSITIVE" else 0.1
            relevance_score = 9
            sectors = ["반도체", "IT H/W"]
            companies = []
            if "하이닉스" in text or "hynix" in text or "삼전닉스" in text:
                companies.append("SK하이닉스")
            if "삼성" in text or "samsung" in text or "삼전" in text:
                companies.append("삼성전자")
            if not companies:
                companies = ["삼성전자", "SK하이닉스"]
                
            macro_impacts = "글로벌 반도체 및 AI 수요 강세 지속으로 국내 IT 하드웨어 수출 증가와 KOSPI 상방 모멘텀 지원."
            korean_summary = f"'{title}' 뉴스는 글로벌 AI 및 반도체 공급망 리스크 호재에 따른 국내 주요 반도체 제조사({', '.join(companies)})의 실적 성장 가능성을 시사합니다."
            alert_level = "HIGH" if "1조" in text or "상한가" in text or "상승" in text else "MEDIUM"
            
        # 2. Batteries / EV
        elif any(x in text for x in ["tesla", "giga", "battery", "musk", "배터리", "이차전지", "셀 3사", "lg에너지솔루션", "삼성sdi"]):
            sentiment = "POSITIVE"
            sentiment_score = 0.5
            relevance_score = 8
            sectors = ["이차전지", "자동차"]
            companies = ["LG에너지솔루션", "삼성SDI", "SK온"]
            macro_impacts = "글로벌 완성차 및 배터리 공급망 협력 확대로 관련 산업 자금 유입 및 관련주 변동성 확대."
            korean_summary = f"'{title}' 소식은 아시아 지역 배터리 공급망 인프라 재조명에 따른 국내 이차전지 셀 3사의 장기 공급 파트너십 구축 및 설비 투자 확대 요인으로 평가됩니다."
            alert_level = "MEDIUM"
            
        # 3. Interest Rates / Central Bank / Exchange Rates / Geopolitical Tensions
        elif any(x in text for x in ["powell", "interest rate", "fed", "금리", "연준", "한국은행", "한은", "환율", "외국환", "국채", "지정학", "갈등", "전쟁"]):
            sentiment = "NEGATIVE" if any(y in text for y in ["상방", "상승", "압력", "갈등", "전쟁", "처우", "떠나는"]) else "NEUTRAL"
            sentiment_score = -0.4 if sentiment == "NEGATIVE" else 0.0
            relevance_score = 8
            sectors = ["거시경제", "금융"]
            companies = ["금융지주회사", "한국은행"]
            macro_impacts = "고금리/고환율 기조 장기화 및 대외 리스크 지속에 따른 원화 가치 변동성 가중 및 KOSPI 시장의 외국인 자금 이탈 경계."
            korean_summary = f"'{title}' 분석 결과, 글로벌 통화 정책 불확실성 및 지정학적 리스크가 맞물려 국내 자본 시장 수급 및 외환 시장 변동성 확대 부담으로 작용할 가능성이 큽니다."
            alert_level = "HIGH"
            
        # 4. Stock Market / Stock Prices / Trading
        elif any(x in text for x in ["stock", "kospi", "kosdaq", "증시", "주가", "주식", "코스피", "코스닥", "개미"]):
            sentiment = "POSITIVE" if "상승" in text or "호실적" in text or "랠리" in text or "벌자" in text or "폭발" in text else "NEUTRAL"
            sentiment_score = 0.4 if sentiment == "POSITIVE" else 0.0
            relevance_score = 7
            sectors = ["증시", "금융"]
            companies = ["증권사", "자산운용사"]
            macro_impacts = "개인 투자자 자금 흐름 다변화 및 국내 주식 거래 대금 변동에 따른 증권업종 센티먼트 영향."
            korean_summary = f"'{title}' 뉴스는 국내 자본시장 개미 투자자들의 투자 열기와 증시 거래대금 변화를 보여주며, 시장 유동성 및 증권가 전반의 수수료 수익 구조에 단기적 영향을 미칠 수 있습니다."
            alert_level = "MEDIUM" if sentiment == "POSITIVE" else "LOW"
            
        # 5. Default Fallback
        else:
            sentiment = "NEUTRAL"
            sentiment_score = 0.1
            relevance_score = 4
            sectors = ["일반경제", "기업동향"]
            companies = ["기타 국내 기업"]
            macro_impacts = "특정 섹터의 개별 기업 재무/경영 활동으로 거시경제 전반에 대한 영향은 다소 제한적임."
            korean_summary = f"'{title}' 뉴스는 특정 기업 또는 경제 섹터의 개별 이슈를 반영하며, 중장기적인 거시경제 영향보다는 단기 업종별 흐름 모니터링이 권장됩니다."
            alert_level = "LOW"
            
        # Map mock companies to their standard 6-digit tickers (Extremely expanded for dynamic watchlist selection)
        mock_ticker_map = {
            "삼성전자": "005930",
            "SK하이닉스": "000660",
            "하이닉스": "000660",
            "현대차": "005380",
            "현대자동차": "005380",
            "기아": "000270",
            "기아차": "000270",
            "NAVER": "035420",
            "네이버": "035420",
            "카카오": "035720",
            "LG에너지솔루션": "373220",
            "LG엔솔": "373220",
            "삼성SDI": "006400",
            "LG화학": "051910",
            "포스코홀딩스": "005490",
            "POSCO홀딩스": "005490",
            "셀트리온": "068270",
            "한미반도체": "042700",
            "에코프로": "086520",
            "에코프로비엠": "247540",
            "포스코퓨처엠": "003670",
            "SK이노베이션": "096770",
            "삼성물산": "028260",
            "KB금융": "105560",
            "KB금융지주": "105560",
            "신한지주": "055550",
            "신한금융지주": "055550",
            "하나금융지주": "086790",
            "삼성바이오로직스": "207940",
            "알테오젠": "196170",
            "HLB": "028300",
            "HMM": "011200",
            "대한항공": "003490",
            "두산에너빌리티": "034020",
            "HD현대중공업": "329180",
            "유한양행": "000100"
        }
        tickers = [mock_ticker_map[c] for c in companies if c in mock_ticker_map and mock_ticker_map[c]]

        return DeepAnalysis(
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            relevance_score=relevance_score,
            impacted_sectors=sectors,
            impacted_companies=companies,
            impacted_tickers=tickers,
            macro_impacts=macro_impacts,
            korean_summary=korean_summary,
            alert_level=alert_level
        )



if __name__ == "__main__":
    # Test block
    print("[Analyzer] Running basic mock test...")
    analyzer = GeminiEconomyAnalyzer()
    
    test_items = [
        {
            "title": "@Jensen Huang post: NVIDIA Blackwell chips shipping",
            "content": "Blackwell production is in full swing. Working closely with HBM3e suppliers like Samsung Electronics and SK Hynix in South Korea to secure next-gen memory components.",
            "source": "SNS (Jensen Huang)"
        },
        {
            "title": "General OpenAI news: GPT-5 preparations",
            "content": "Our teams are focused on aligning and safety-testing our next frontier model. The leap in reasoning capabilities will surprise people.",
            "source": "News"
        }
    ]
    
    for item in test_items:
        print("\n" + "="*40)
        print(f"Testing Content: {item['title']}")
        rel, ans = analyzer.process_item(item)
        print(f"Stage 1 Relevant: {rel.relevant}")
        print(f"Reason: {rel.reason}")
        if ans:
            print("\nStage 2 Deep Analysis:")
            print(f"- Sentiment: {ans.sentiment} (Score: {ans.sentiment_score})")
            print(f"- Relevance Score: {ans.relevance_score}/10")
            print(f"- Impacted Sectors: {ans.impacted_sectors}")
            print(f"- Impacted Companies: {ans.impacted_companies}")
            print(f"- Macro Impacts: {ans.macro_impacts}")
            print(f"- Korean Summary: {ans.korean_summary}")
            print(f"- Alert Level: {ans.alert_level}")
        else:
            print("[Stage 2 Deep Analysis Skipped - Not Relevant to South Korea]")
