import requests

def get_market_indicators():
    """
    Fetches real-time prices and daily change percentages for:
    - KOSPI Index (^KS11)
    - USD/KRW Exchange Rate (USDKRW=X)
    - Samsung Electronics (005930.KS)
    - SK Hynix (000660.KS)
    
    Uses keyless public Yahoo Finance chart API endpoints.
    Returns a dictionary of indicators or fallbacks if the network is down.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    symbols = {
        "KOSPI": "^KS11",
        "USD_KRW": "USDKRW=X",
        "SAMSUNG": "005930.KS",
        "HYNIX": "000660.KS"
    }
    
    results = {}
    
    for label, sym in symbols.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                meta = data["chart"]["result"][0]["meta"]
                
                # Fetch price and previous close
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("chartPreviousClose")
                
                if price is not None and prev_close:
                    change_val = price - prev_close
                    change_percent = (change_val / prev_close) * 100
                    
                    results[label] = {
                        "symbol": sym,
                        "price": round(price, 2) if label not in ["SAMSUNG", "HYNIX"] else int(price),
                        "change": round(change_val, 2) if label not in ["SAMSUNG", "HYNIX"] else int(change_val),
                        "percent": round(change_percent, 2),
                        "status": "success"
                    }
                    continue
        except Exception:
            pass
            
        # Heuristic fallback if network fails
        results[label] = get_fallback_value(label)
        
    return results

def get_fallback_value(label):
    """
    Returns realistic mock values in case Yahoo Finance API is rate-limited or blocked.
    """
    fallbacks = {
        "KOSPI": {"symbol": "^KS11", "price": 2650.45, "change": 12.30, "percent": 0.47, "status": "fallback"},
        "USD_KRW": {"symbol": "USDKRW=X", "price": 1365.50, "change": -2.80, "percent": -0.20, "status": "fallback"},
        "SAMSUNG": {"symbol": "005930.KS", "price": 78200, "change": 1100, "percent": 1.43, "status": "fallback"},
        "HYNIX": {"symbol": "000660.KS", "price": 195400, "change": -1800, "percent": -0.91, "status": "fallback"}
    }
    return fallbacks.get(label)

if __name__ == "__main__":
    print("[Market] Testing Yahoo Finance chart endpoints...")
    data = get_market_indicators()
    for k, v in data.items():
        sign = "+" if v["change"] > 0 else ""
        unit = "원" if k in ["SAMSUNG", "HYNIX"] else ("$" if k == "USD_KRW" else "pt")
        print(f"{k} ({v['symbol']}): {v['price']}{unit} | {sign}{v['change']} ({sign}{v['percent']}%) [{v['status']}]")
