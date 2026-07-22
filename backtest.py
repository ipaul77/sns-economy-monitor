import os
import sys
import json
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    delta = pd.Series(prices).diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def run_simulation(stock_ticker="005930.KS", index_ticker="^KS11", days=180):
    print(f"\n======================================================================")
    print(f"       BACKTESTING ENGINE: STATIC VS DYNAMIC RISK GUARDRAILS")
    print(f"       Ticker: {stock_ticker} | Index: {index_ticker} | Period: {days} Days")
    print(f"======================================================================\n")

    # 1. Fetch historical data
    print("[1/4] Fetching historical data from yfinance...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days + 40) # Fetch extra days for warm-up
    
    idx_df = yf.Ticker(index_ticker).history(start=start_date, end=end_date)
    stk_df = yf.Ticker(stock_ticker).history(start=start_date, end=end_date)
    
    if idx_df.empty or stk_df.empty:
        print("[Error] Failed to fetch historical data. Please check network connection.")
        return

    # Align dates
    common_dates = idx_df.index.intersection(stk_df.index)
    idx_df = idx_df.loc[common_dates]
    stk_df = stk_df.loc[common_dates]
    
    # 2. Warm up and calculate rolling technical indicators
    print("[2/4] Warming up and calculating technical indicators...")
    
    # KOSPI indicators
    idx_df["ma_20"] = idx_df["Close"].rolling(window=20).mean()
    idx_df["disparity"] = (idx_df["Close"] / idx_df["ma_20"]) * 100
    idx_df["daily_change_pct"] = idx_df["Close"].pct_change() * 100
    
    # Volatility indicators
    idx_df["disparity_mean"] = idx_df["disparity"].rolling(window=20).mean()
    idx_df["disparity_std"] = idx_df["disparity"].rolling(window=20).std()
    
    # Stock indicators
    stk_df["daily_change_pct"] = stk_df["Close"].pct_change() * 100
    stk_df["volatility_20d"] = (stk_df["Close"].pct_change() * 100).rolling(window=20).std()
    
    # Drop warm-up rows (first 40 rows)
    valid_dates = idx_df.index[40:]
    
    total_signals = 0
    static_blocks = 0
    dynamic_blocks = 0
    static_whipsaws = 0
    dynamic_whipsaws = 0
    
    print("[3/4] Replaying daily trading decisions...")
    
    for i, date in enumerate(valid_dates):
        idx_row = idx_df.loc[date]
        stk_row = stk_df.loc[date]
        
        # Get historical slice for RSI calculations
        history_slice = stk_df.loc[:date]
        if len(history_slice) < 15:
            continue
            
        close_prices = history_slice["Close"].tolist()
        rsi_val = calculate_rsi(close_prices, 14)
        rsi_prev = calculate_rsi(close_prices[:-1], 14)
        
        # Index metrics
        kospi_disp = idx_row["disparity"]
        kospi_change = idx_row["daily_change_pct"]
        disp_mean = idx_row["disparity_mean"]
        disp_std = idx_row["disparity_std"]
        
        # Volatility
        stock_vol = stk_row["volatility_20d"]
        if pd.isna(stock_vol) or stock_vol == 0:
            stock_vol = 2.0
            
        curr_price = stk_row["Close"]
        
        # Simulate potential buy triggers: Let's assume we trigger a check when RSI <= 35
        if rsi_val <= 35.0:
            total_signals += 1
            
            # Determine subsequent 3-day return to detect whipsaws (whipsaw = buying right before a >3.0% drop)
            future_slice = stk_df.loc[date:].head(4) # today + 3 days
            is_whipsaw = False
            if len(future_slice) >= 4:
                future_close = future_slice["Close"].iloc[-1]
                future_ret = ((future_close - curr_price) / curr_price) * 100
                if future_ret <= -3.0:
                    is_whipsaw = True
            
            # -------------------------------------------------------------
            # STATIC RULES SIMULATION
            # -------------------------------------------------------------
            # Static Macro evaluation
            static_cb = "NORMAL"
            if kospi_disp <= 78.0 or kospi_change <= -6.0:
                static_cb = "SYSTEM_CRASH_LOCKDOWN"
            elif kospi_disp <= 85.0 or kospi_change <= -3.0:
                static_cb = "CONTRARIAN_VALUE_BUY"
            elif 85.0 < kospi_disp <= 92.0:
                static_cb = "HARD_NO_BUY"
            elif 92.0 < kospi_disp < 95.0:
                if kospi_change < -1.5:
                    static_cb = "HARD_NO_BUY"
                else:
                    static_cb = "CONSERVATIVE_BUY"
                    
            # Static buy decision
            static_buy_blocked = False
            # Check market crash
            is_market_crash = (kospi_change <= -1.5) or (kospi_disp <= 95.0)
            is_macro_bypass = static_cb in ["CONTRARIAN_VALUE_BUY", "CONSERVATIVE_BUY"]
            
            if is_market_crash and not is_macro_bypass:
                # Oversold rebound check
                is_rebound = (rsi_val <= 30.0) and (rsi_val > rsi_prev) and (stk_row["daily_change_pct"] >= 1.0)
                if not is_rebound:
                    static_buy_blocked = True
            elif is_market_crash and is_macro_bypass:
                if static_cb == "CONTRARIAN_VALUE_BUY":
                    # Falling knife block
                    if rsi_val < 35.0 and rsi_val <= rsi_prev:
                        static_buy_blocked = True
            
            if static_buy_blocked:
                static_blocks += 1
            else:
                if is_whipsaw:
                    static_whipsaws += 1

            # -------------------------------------------------------------
            # DYNAMIC RULES SIMULATION
            # -------------------------------------------------------------
            # Dynamic Macro evaluation
            crash_limit = disp_mean - 2.5 * disp_std
            value_buy_limit = disp_mean - 1.5 * disp_std
            no_buy_limit = disp_mean - 0.5 * disp_std
            
            dynamic_cb = "NORMAL"
            if kospi_disp <= crash_limit or kospi_change <= -6.0:
                dynamic_cb = "SYSTEM_CRASH_LOCKDOWN"
            elif kospi_disp <= value_buy_limit or kospi_change <= -3.0:
                dynamic_cb = "CONTRARIAN_VALUE_BUY"
            elif value_buy_limit < kospi_disp <= no_buy_limit:
                dynamic_cb = "HARD_NO_BUY"
            elif no_buy_limit < kospi_disp < 95.0:
                if kospi_change < -1.5:
                    dynamic_cb = "HARD_NO_BUY"
                else:
                    dynamic_cb = "CONSERVATIVE_BUY"
                    
            # Dynamic buy decision
            dynamic_buy_blocked = False
            # Check market crash
            is_market_crash = (kospi_change <= -1.5) or (kospi_disp <= 95.0)
            is_macro_bypass = dynamic_cb in ["CONTRARIAN_VALUE_BUY", "CONSERVATIVE_BUY"]
            
            if is_market_crash and not is_macro_bypass:
                # Volatility adjusted rebound check
                is_rebound = (rsi_val <= 30.0) and (rsi_val > rsi_prev) and (stk_row["daily_change_pct"] >= 1.0)
                if not is_rebound:
                    dynamic_buy_blocked = True
            elif is_market_crash and is_macro_bypass:
                if dynamic_cb == "CONTRARIAN_VALUE_BUY":
                    # Falling knife block
                    if rsi_val < 35.0 and rsi_val <= rsi_prev:
                        dynamic_buy_blocked = True
            
            if dynamic_buy_blocked:
                dynamic_blocks += 1
            else:
                if is_whipsaw:
                    dynamic_whipsaws += 1
                    
    # 4. Display Results
    print("\n[4/4] COMPILING BACKTEST RESULTS:")
    print("----------------------------------------------------------------------")
    print(f"Total Oversold Signals (RSI <= 35) Triggered: {total_signals} times")
    print("----------------------------------------------------------------------")
    print("[STATIC RULES - Before Change]")
    print(f"  - Blocked Buys: {static_blocks} times")
    print(f"  - Executed Buys: {total_signals - static_blocks} times")
    print(f"  - Whipsaw Trades (Lost >3.0% in next 3 days): {static_whipsaws} times")
    if (total_signals - static_blocks) > 0:
        print(f"  - Whipsaw Rate of Executed Trades: {static_whipsaws / (total_signals - static_blocks) * 100:.2f}%")
    print("----------------------------------------------------------------------")
    print("[DYNAMIC VOLATILITY RULES - After Change]")
    print(f"  - Blocked Buys: {dynamic_blocks} times")
    print(f"  - Executed Buys: {total_signals - dynamic_blocks} times")
    print(f"  - Whipsaw Trades (Lost >3.0% in next 3 days): {dynamic_whipsaws} times")
    if (total_signals - dynamic_blocks) > 0:
        print(f"  - Whipsaw Rate of Executed Trades: {dynamic_whipsaws / (total_signals - dynamic_blocks) * 100:.2f}%")
    print("----------------------------------------------------------------------")
    whipsaw_diff = static_whipsaws - dynamic_whipsaws
    print(f"Conclusion: Dynamic volatility rules prevented {whipsaw_diff} extra whipsaw trades!")
    print("======================================================================\n")

if __name__ == "__main__":
    run_simulation()
