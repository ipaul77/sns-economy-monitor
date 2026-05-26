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
        flash_model_name = self.config.get("models", {}).get("flash_model", "gemini-1.5-flash")
        
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
            
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=RelevanceCheck
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
        pro_model_name = self.config.get("models", {}).get("pro_model", "gemini-1.5-pro")
        
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
            
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=DeepAnalysis
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
        """
        title = item.get("title", "") or ""
        content = item.get("content", "") or ""
        text = (title + " " + content).lower()
        
        keywords = self.config.get("target_keywords", [])
        if not keywords:
            # If no keywords are defined, default to True (don't filter anything locally)
            return True
            
        for kw in keywords:
            if kw.strip() and kw.lower() in text:
                return True
        return False

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
        
        if "nvidia" in text or "hbm" in text or "semiconductor" in text or "황창규" in text or "jensen huang" in text:
            sentiment = "POSITIVE"
            sentiment_score = 0.8
            relevance_score = 9
            sectors = ["반도체", "IT H/W"]
            companies = ["삼성전자", "SK하이닉스"]
            macro_impacts = "NVIDIA의 신규 칩 수요 증가로 인한 국내 메모리 반도체 동반 수출 확대 기대로 KOSPI 반등 및 IT 수출 호조세 유입 예상."
            korean_summary = "엔비디아가 HBM3e 공급을 다각화하고 차세대 칩 Blackwell의 대량 생산에 돌입함에 따라, 주요 메모리 공급업체인 삼성전자와 SK하이닉스의 수혜가 강력하게 예상됩니다. 반도체 수출 사이클 개선 신호입니다."
            alert_level = "HIGH"
        elif "tesla" in text or "giga" in text or "battery" in text or "musk" in text:
            sentiment = "POSITIVE"
            sentiment_score = 0.5
            relevance_score = 7
            sectors = ["이차전지", "자동차"]
            companies = ["LG에너지솔루션", "현대자동차"]
            macro_impacts = "기가팩토리 아시아 확장 및 배터리 공급망 수요 자극으로 2차전지 밸류체인 전반의 자금 수급 개선 효과 기대."
            korean_summary = "일론 머스크의 아시아 기가팩토리 추가 확장 언급에 따라 배터리 강국인 대한민국의 강력한 배터리 공급망 인프라가 재조명받고 있습니다. LG엔솔, 삼성SDI 등 국내 배터리 셀 3사와의 협력 확장 가능성이 존재합니다."
            alert_level = "MEDIUM"
        elif "powell" in text or "interest rate" in text or "fed" in text:
            sentiment = "NEGATIVE"
            sentiment_score = -0.3
            relevance_score = 8
            sectors = ["거시경제", "금융"]
            companies = ["금융지주회사"]
            macro_impacts = "미국 연준의 고금리 장기화 기조에 따른 원/달러 환율 상방 압력 가중 및 외인 자금 이탈 가능성 가중 (KOSPI 횡보)."
            korean_summary = "파월 연준 의장이 인플레이션 극복을 위해 고금리 기조를 유지하겠다는 신호를 보이면서 한미 금리 격차에 따른 원화 약세 압력이 고조되고 있습니다. 국내 증시 수급 부담 요소로 작용할 가능성이 큽니다."
            alert_level = "HIGH"
        else:
            sentiment = "NEUTRAL"
            sentiment_score = 0.1
            relevance_score = 4
            sectors = ["글로벌 기술 IT"]
            companies = ["삼성전자"]
            macro_impacts = "글로벌 IT 인프라 투자 모멘텀 유지로 인한 국내 테크 업종에 대한 간접적 센티먼트 개선 지원."
            korean_summary = "소버린 AI 인프라 투자와 핵심 모델 개발 촉진 등 글로벌 기술 트렌드의 강화 흐름은 한국 반도체 및 하드웨어 공급업체에 중장기적으로 긍정적인 산업 센티먼트를 유도합니다."
            alert_level = "LOW"
            
        return DeepAnalysis(
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            relevance_score=relevance_score,
            impacted_sectors=sectors,
            impacted_companies=companies,
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
