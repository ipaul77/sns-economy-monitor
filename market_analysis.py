import yfinance as yf
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

import db
import investor

# Static company/ticker mappings
COMPANY_TO_TICKER = {
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
    "유한양행": "000100",
    "KODEX 200 선물인버스2X": "252670",
    "인버스": "252670",
    "인버스2X": "252670"
}

KOSDAQ_TICKERS = {"086520", "247540", "196170", "028300", "066970"}

TICKER_TO_SECTOR = {
    "005930": "반도체/IT",
    "000660": "반도체/IT",
    "042700": "반도체/IT",
    "373220": "이차전지/소재",
    "006400": "이차전지/소재",
    "051910": "이차전지/소재",
    "086520": "이차전지/소재",
    "247540": "이차전지/소재",
    "003670": "이차전지/소재",
    "096770": "이차전지/소재",
    "005380": "자동차/운송",
    "000270": "자동차/운송",
    "003490": "자동차/운송",
    "011200": "자동차/운송",
    "329180": "조선/기계",
    "034020": "조선/기계",
    "035420": "플랫폼/인터넷",
    "035720": "플랫폼/인터넷",
    "068270": "바이오",
    "207940": "바이오",
    "196170": "바이오",
    "028300": "바이오",
    "000100": "바이오",
    "105560": "금융/지주",
    "055550": "금융/지주",
    "086790": "금융/지주",
    "005490": "금융/지주",
    "028260": "금융/지주",
    "252670": "인버스/헤지"
}

def is_kospi_bear_market() -> bool:
    """
    KOSPI 지수가 최근 5일 이동평균선(5-day MA)보다 아래에 있는 하락 약세장 여부를 판별합니다.
    """
    try:
        yt = yf.Ticker("^KS11")
        hist = yt.history(period="10d")
        if not hist.empty and len(hist) >= 5:
            current_kospi = float(hist["Close"].iloc[-1])
            ma_5 = float(hist["Close"].iloc[-5:].mean())
            is_bear = current_kospi < ma_5
            print(f"[Market Analysis] KOSPI Bear Filter: Current = {current_kospi:,.2f} | 5 MA = {ma_5:,.2f} | Bear Market = {is_bear}")
            return is_bear
    except Exception as e:
        print(f"[Market Analysis] [Warning] Failed to fetch KOSPI 5 MA: {e}")
    return False

def get_dynamic_top_7_stocks() -> List[str]:
    """
    최근 24시간 내 수집된 관련성 높은 기사(is_relevant=1)를 바탕으로 가장 많이 언급된 종목 7개를 선정합니다.
    """
    recent_news = db.fetch_recent_relevant(hours=24)
    
    ticker_counts = {}
    for item in recent_news:
        tickers_val = item.get("impacted_tickers")
        if tickers_val:
            try:
                if isinstance(tickers_val, str):
                    tickers_list = json.loads(tickers_val)
                elif isinstance(tickers_val, list):
                    tickers_list = tickers_val
                else:
                    tickers_list = []
                
                if isinstance(tickers_list, list):
                    for t in tickers_list:
                        t = str(t).strip()
                        if len(t) == 6 and t.isdigit():
                            ticker_counts[t] = ticker_counts.get(t, 0) + 1
            except Exception:
                pass
                
        companies_val = item.get("impacted_companies")
        if companies_val:
            try:
                if isinstance(companies_val, str):
                    companies = json.loads(companies_val)
                elif isinstance(companies_val, list):
                    companies = companies_val
                else:
                    companies = []
                
                if isinstance(companies, list):
                    for comp in companies:
                        ticker = COMPANY_TO_TICKER.get(str(comp).strip())
                        if ticker:
                            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
            except Exception:
                pass

    sorted_tickers = [t for t, count in sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)]
    default_tickers = ["005930", "000660", "373220", "005380", "207940", "000270", "068270"]
    
    # Force include Inverse ETF if KOSPI is in downtrend
    try:
        regime = get_market_trend_regime()
        if regime.get("is_downtrend", False):
            default_tickers.insert(0, "252670")
            print("[Market Analysis] Market is in Downtrend. Forcing Inverse ETF (252670) into monitoring universe.")
    except Exception:
        pass

    dynamic_7 = []
    for t in sorted_tickers:
        if t not in dynamic_7 and len(dynamic_7) < 7:
            dynamic_7.append(t)
            
    for t in default_tickers:
        if t not in dynamic_7 and len(dynamic_7) < 7:
            dynamic_7.append(t)
            
    return dynamic_7

def get_active_tickers(portfolio: Dict[str, Any], news_context: List[Dict[str, Any]]) -> List[str]:
    """
    Dynamically constructs the stock ticker pool for the current simulation cycle.
    """
    dynamic_7 = get_dynamic_top_7_stocks()
    active_tickers = set(dynamic_7)
    
    for ticker in portfolio.keys():
        active_tickers.add(ticker)
        
    print(f"[Market Analysis] Dynamic candidate ticker pool generated: {list(active_tickers)}")
    return list(active_tickers)

def get_market_index_change() -> Dict[str, float]:
    """
    Fetches the daily return (%) for KOSPI (^KS11) and KOSDAQ (^KQ11) from yfinance.
    """
    indices = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    results = {"KOSPI": 0.0, "KOSDAQ": 0.0}
    for name, ticker in indices.items():
        try:
            yt = yf.Ticker(ticker)
            hist = yt.history(period="2d")
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                curr_close = float(hist["Close"].iloc[-1])
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                results[name] = round(pct_change, 2)
            else:
                info = yt.fast_info
                change = info.get("regularMarketChangePercent") or info.get("regular_market_change_percent")
                if change is not None:
                    results[name] = round(float(change), 2)
        except Exception as e:
            print(f"[Market Analysis] [Warning] Failed to fetch index {name}: {e}")
    return results

def get_market_trend_regime() -> Dict[str, Any]:
    """
    Fetches the last 20 days of KOSPI historical data and determines trend.
    """
    try:
        yt = yf.Ticker("^KS11")
        hist = yt.history(period="1mo")
        if not hist.empty and len(hist) >= 20:
            close_slice = hist["Close"].iloc[-20:]
            ma_20 = float(close_slice.mean())
            current_price = float(hist["Close"].iloc[-1])
            is_downtrend = current_price < ma_20
            return {
                "status": "success",
                "current_price": round(current_price, 2),
                "ma_20": round(ma_20, 2),
                "is_downtrend": is_downtrend,
                "message": f"KOSPI: {current_price:.2f} | 20 MA: {ma_20:.2f} ({'하락 국면' if is_downtrend else '상승 국면'})"
            }
    except Exception as e:
        print(f"[Market Analysis] [Warning] Failed to fetch market trend regime: {e}")
    return {
        "status": "fallback",
        "current_price": 2650.0,
        "ma_20": 2650.0,
        "is_downtrend": False,
        "message": "시장 국면 분석 실패 (기본값 상승 국면으로 우회)"
    }

def calculate_rsi(prices: list, period: int = 14) -> float:
    """
    Calculates the Relative Strength Index (RSI) for a list of close prices.
    """
    if len(prices) < period + 1:
        return 50.0
        
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    seed = deltas[:period]
    up = sum(d for d in seed if d > 0) / period
    down = sum(-d for d in seed if d < 0) / period
    
    for d in deltas[period:]:
        d_up = d if d > 0 else 0.0
        d_down = -d if d < 0 else 0.0
        up = (up * (period - 1) + d_up) / period
        down = (down * (period - 1) + d_down) / period
        
    if down == 0:
        return 100.0
    rs = up / down
    return 100.0 - (100.0 / (1.0 + rs))

def get_stock_indicators(ticker: str) -> Dict[str, Any]:
    """
    Fetches technical and fundamental indicators for a stock ticker.
    """
    ticker = ticker.strip()
    result = {
        "current_price": 0.0,
        "ma_20": 0.0,
        "disparity": 100.0,
        "rsi": 50.0,
        "rsi_prev": 50.0,
        "daily_volume": 0,
        "avg_volume_5d": 0.0,
        "volume_ratio": 1.0,
        "volume_breakout": False,
        "daily_change_pct": 0.0,
        "market": "KOSPI",
        "roe": None,
        "pe_ratio": None,
        "pb_ratio": None,
        "debt_to_equity": None,
        "free_cash_flow": None,
        "target_price": None,
        "margin_of_safety": None
    }
    if not ticker:
        return result

    resolved_suffix = ".KS"
    if len(ticker) == 6 and ticker.isdigit():
        if ticker in KOSDAQ_TICKERS:
            resolved_suffix = ".KQ"
            result["market"] = "KOSDAQ"
        else:
            resolved_suffix = ".KS"
            result["market"] = "KOSPI"
            
    full_ticker = ticker + resolved_suffix if (len(ticker) == 6 and ticker.isdigit()) else ticker

    try:
        yt = yf.Ticker(full_ticker)
        hist = yt.history(period="1mo")
        if hist.empty and len(ticker) == 6 and ticker.isdigit():
            fallback_suffix = ".KQ" if resolved_suffix == ".KS" else ".KS"
            yt = yf.Ticker(ticker + fallback_suffix)
            hist = yt.history(period="1mo")
            if not hist.empty:
                result["market"] = "KOSDAQ" if fallback_suffix == ".KQ" else "KOSPI"
        if hist.empty:
            price = investor.get_latest_cached_price(ticker)
            if price > 0:
                result["current_price"] = price
                result["ma_20"] = price
                result["disparity"] = 100.0
            return result

        kis_price = None
        try:
            from kis_client import kis_client
            kis_price = kis_client.get_current_price(ticker)
        except Exception as e:
            print(f"[Market Analysis] [Warning] KIS price fetch failed: {e}")

        current_price = kis_price if kis_price is not None else float(hist["Close"].iloc[-1])
        result["current_price"] = current_price
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else current_price
        result["daily_change_pct"] = round(((current_price - prev_close) / prev_close) * 100, 2)

        ma_length = min(len(hist), 20)
        close_slice = hist["Close"].iloc[-ma_length:].tolist()
        if len(close_slice) > 0 and kis_price is not None:
            close_slice[-1] = kis_price
        ma_20 = sum(close_slice) / len(close_slice)
        result["ma_20"] = ma_20

        if ma_20 > 0:
            result["disparity"] = round((current_price / ma_20) * 100, 2)

        close_prices = hist["Close"].tolist()
        if len(close_prices) > 0 and kis_price is not None:
            close_prices[-1] = kis_price
        
        rsi_today = calculate_rsi(close_prices, 14)
        rsi_prev = calculate_rsi(close_prices[:-1], 14) if len(close_prices) > 1 else rsi_today
        result["rsi"] = round(rsi_today, 2)
        result["rsi_prev"] = round(rsi_prev, 2)

        daily_volume = int(hist["Volume"].iloc[-1])
        result["daily_volume"] = daily_volume

        if len(hist) >= 6:
            vol_slice = hist["Volume"].iloc[-6:-1]
            avg_vol_5d = float(vol_slice.mean())
        else:
            avg_vol_5d = float(hist["Volume"].iloc[:-1].mean()) if len(hist) > 1 else float(daily_volume)
        
        result["avg_volume_5d"] = avg_vol_5d

        if avg_vol_5d > 0:
            vol_ratio = daily_volume / avg_vol_5d
            result["volume_ratio"] = round(vol_ratio, 2)
            result["volume_breakout"] = vol_ratio > 2.0
            
    except Exception as e:
        print(f"[Market Analysis] [Warning] Failed to calculate indicators for {ticker}: {e}")
        price = investor.get_latest_cached_price(ticker)
        result["current_price"] = price
        result["ma_20"] = price
        result["disparity"] = 100.0
        result["daily_change_pct"] = 0.0

    try:
        inv_ind = investor.get_investor_indicators(ticker)
        result.update(inv_ind)
    except Exception as ex:
        print(f"[Market Analysis] [Warning] Failed to merge investor indicators: {ex}")
        result.update({
            "frgn_net_5d": 0, "inst_net_5d": 0, "frgn_net_10d": 0, "inst_net_10d": 0,
            "dual_buy_5d_count": 0, "frgn_ratio": 0.0, "frgn_trend_sig": "HOLD", "inst_trend_sig": "HOLD"
        })

    try:
        fund = db.fetch_fundamentals(ticker)
        needs_update = True
        if fund and fund.get("last_updated"):
            try:
                last_up = datetime.fromisoformat(fund["last_updated"])
                now_kst = db.get_kst_now()
                if (now_kst - last_up).total_seconds() < 86400:
                    needs_update = False
            except Exception as dt_err:
                print(f"[Market Analysis] Failed parsing fundamentals timestamp: {dt_err}")
                
        if needs_update:
            print(f"[Market Analysis] Fundamentals cache expired. Scraping yfinance for {ticker}...")
            try:
                suffix = ".KQ" if ticker in KOSDAQ_TICKERS else ".KS"
                full_t = ticker + suffix if (len(ticker) == 6 and ticker.isdigit()) else ticker
                yt = yf.Ticker(full_t)
                info = yt.info
                if info:
                    roe_raw = info.get("returnOnEquity")
                    roe = roe_raw * 100.0 if roe_raw is not None else None
                    debt = info.get("debtToEquity")
                    fcf = info.get("freeCashflow")
                    target = info.get("targetMeanPrice")
                    eps = info.get("trailingEps") or info.get("forwardEps")
                    bps = info.get("bookValue")
                    pe = info.get("trailingPE") or info.get("forwardPE")
                    pb = info.get("priceToBook")
                    
                    fund_data = {
                        "roe": roe, "pe_ratio": pe, "pb_ratio": pb, "debt_to_equity": debt,
                        "free_cash_flow": fcf, "target_price": target, "eps": eps, "bps": bps
                    }
                    db.save_fundamentals(ticker, fund_data)
                    fund = db.fetch_fundamentals(ticker)
            except Exception as yf_err:
                print(f"[Market Analysis] [Warning] Failed to scrape fundamentals: {yf_err}")
                
        if fund:
            result["roe"] = fund.get("roe")
            result["debt_to_equity"] = fund.get("debt_to_equity")
            result["free_cash_flow"] = fund.get("free_cash_flow")
            result["target_price"] = fund.get("target_price")
            
            eps = fund.get("eps")
            if eps and eps > 0 and result["current_price"] > 0:
                result["pe_ratio"] = round(result["current_price"] / eps, 2)
            else:
                result["pe_ratio"] = fund.get("pe_ratio")
                
            bps = fund.get("bps")
            if bps and bps > 0 and result["current_price"] > 0:
                result["pb_ratio"] = round(result["current_price"] / bps, 2)
            else:
                result["pb_ratio"] = fund.get("pb_ratio")
                
            target_p = fund.get("target_price")
            if target_p and target_p > 0 and result["current_price"] > 0:
                safety = ((target_p - result["current_price"]) / result["current_price"]) * 100.0
                result["margin_of_safety"] = round(safety, 2)
            else:
                result["margin_of_safety"] = None
                
    except Exception as fund_err:
        print(f"[Market Analysis] [Warning] Fundamentals pipeline failed: {fund_err}")

    return result

def get_stock_volatility_multiplier(ticker: str, fallback_vol: float = 0.045) -> float:
    """
    Calculates the standard deviation of daily returns and sets volatility-based stop rate.
    """
    ticker = ticker.strip()
    if not ticker:
        return fallback_vol
        
    full_ticker = ticker
    if len(ticker) == 6 and ticker.isdigit():
        full_ticker = ticker + ".KS"
        
    try:
        yt = yf.Ticker(full_ticker)
        hist = yt.history(period="1mo")
        if (hist.empty or len(hist) < 10) and len(ticker) == 6:
            yt = yf.Ticker(ticker + ".KQ")
            hist = yt.history(period="1mo")
            
        if not hist.empty and len(hist) >= 10:
            close_prices = hist["Close"].tolist()
            returns = []
            for i in range(1, len(close_prices)):
                if close_prices[i-1] > 0:
                    returns.append((close_prices[i] - close_prices[i-1]) / close_prices[i-1])
            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std_dev = math.sqrt(variance)
                std_dev = max(min(std_dev, 0.06), 0.01)
                vol_stop = std_dev * 2.5
                print(f"[Market Analysis] {ticker}: Daily StdDev = {std_dev:.2%}, VolStop = {vol_stop:.2%}")
                return vol_stop
    except Exception as e:
        print(f"[Market Analysis] [Warning] Volatility calculation failed: {e}")
        
    return fallback_vol

def get_stock_price(ticker: str) -> float:
    """
    Fetches the current market price for a given stock ticker code.
    """
    ticker = ticker.strip()
    if not ticker:
        return 0.0

    if len(ticker) == 6 and ticker.isdigit():
        try:
            from kis_client import kis_client
            kis_price = kis_client.get_current_price(ticker)
            if kis_price is not None and kis_price > 0:
                return kis_price
        except Exception as e:
            print(f"[Market Analysis] [Warning] KIS API price query failed: {e}")

        resolved_suffix = ".KQ" if ticker in KOSDAQ_TICKERS else ".KS"
        full_ticker = ticker + resolved_suffix
        try:
            yt = yf.Ticker(full_ticker)
            info = yt.fast_info
            price = info.get("lastPrice") or info.get("last_price")
            if price is not None and price > 0:
                return float(price)
            hist = yt.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            alt_suffix = ".KS" if resolved_suffix == ".KQ" else ".KQ"
            try:
                yt = yf.Ticker(ticker + alt_suffix)
                info = yt.fast_info
                price = info.get("lastPrice") or info.get("last_price")
                if price is not None and price > 0:
                    return float(price)
                hist = yt.history(period="1d")
                if not hist.empty:
                    return float(hist["Close"].iloc[-1])
            except Exception:
                pass
        
        fallback = investor.get_latest_cached_price(ticker)
        if fallback > 0:
            print(f"[Market Analysis] [Warning] yfinance failed. Using SQLite cached fallback price: {fallback:,.0f} KRW.")
            return fallback
    else:
        try:
            yt = yf.Ticker(ticker)
            info = yt.fast_info
            price = info.get("lastPrice") or info.get("last_price")
            if price is not None and price > 0:
                return float(price)
        except Exception:
            pass
    return 0.0
