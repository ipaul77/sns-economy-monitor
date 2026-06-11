# -*- coding: utf-8 -*-
import os
import sys
import json

# Add workspace root to python path
sys.path.append(os.getcwd())

# Set output to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

import db
import trading_engine

# Force database sync from Firestore
print("Syncing SQLite database with Firestore...")
trading_engine.warm_start_trading_cache()

# 1. Fetch Agent State
state = trading_engine.get_agent_state()
balance = float(state.get('balance', 0.0))
total_asset = float(state.get('total_asset', 0.0))
start_date = state.get('start_date', '')
system_lock = state.get('system_lock', False)

# 2. Fetch Portfolio
portfolio_holdings = trading_engine.get_portfolio_holdings()

# 3. Fetch Transactions
all_txs = trading_engine.get_latest_transactions(limit=100)

# 4. Generate Markdown
md = []
md.append("# 계좌 현황 및 거래 내역 분석 리포트")
md.append(f"\n* **조회 기준 시간**: 2026-06-11 16:49:32 KST")
md.append(f"* **최초 투자 시작일**: {start_date}")
md.append(f"* **시스템 잠금 상태**: {system_lock}")

md.append("\n## 1. 자산 현황 요약")
md.append("| 항목 | 금액 (원) | 비고 |")
md.append("|---|---|---|")
md.append(f"| **예수금 (Cash)** | {balance:,.0f} 원 | 가용 현금 비중: {balance/total_asset*100:.2f}% |")
md.append(f"| **총 평가 자산 (Total Asset)** | {total_asset:,.0f} 원 | 수익률: {(total_asset - 10000000.0)/10000000.0*100:+.2f}% (원금 10,000,000원 기준) |")

md.append("\n## 2. 현재 포트폴리오 보유 종목")
if not portfolio_holdings:
    md.append("\n*현재 보유 중인 주식이 없습니다. (100% 현금 상태)*")
else:
    md.append("\n| 종목명 (코드) | 수량 | 평균 매입 단가 | 현재가 | 평가 금액 | 최고가 대비 등락 | 투자 모드 | 최근 스케일아웃 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for ticker, p in portfolio_holdings.items():
        ticker_names = {
            "005930": "삼성전자",
            "000660": "SK하이닉스",
            "005380": "현대차",
            "000270": "기아",
            "035420": "NAVER",
            "035720": "카카오",
            "055550": "신한지주",
            "105560": "KB금융",
            "086790": "하나금융지주"
        }
        name = ticker_names.get(ticker, ticker)
        current_price = trading_engine.get_stock_price(ticker)
        eval_value = p['quantity'] * current_price
        highest_price = p['highest_price_after_buy']
        
        md.append(f"| {name} ({ticker}) | {p['quantity']} 주 | {p['average_price']:,.0f} 원 | {current_price:,.0f} 원 | {eval_value:,.0f} 원 | 최고가: {highest_price:,.0f} 원 | {p['mode']} | {p['last_scale_out_date'] or '-'} |")

md.append("\n## 3. 거래 내역 리포트 (최근 거래 우선)")

# Group transactions by date
from collections import defaultdict
txs_by_date = defaultdict(list)
for tx in all_txs:
    date_str = tx['timestamp'].split('T')[0]
    txs_by_date[date_str].append(tx)

dates = sorted(list(txs_by_date.keys()), reverse=True)

for date in dates:
    md.append(f"\n### 📅 {date}")
    txs = txs_by_date[date]
    md.append("| 시간 | 종목 | 거래 종류 | 수량 | 거래 단가 | 거래금액 | 체결 후 예수금 |")
    md.append("|---|---|---|---|---|---|---|")
    for tx in txs:
        ticker_names = {
            "005930": "삼성전자",
            "000660": "SK하이닉스",
            "005380": "현대차",
            "000270": "기아",
            "035420": "NAVER",
            "035720": "카카오",
            "055550": "신한지주",
            "105560": "KB금융",
            "086790": "하나금융지주"
        }
        name = ticker_names.get(tx['ticker'], tx['ticker'])
        amt = tx['quantity'] * tx['price']
        snap = tx['snapshot_context']
        post_bal = snap.get('new_balance', 0.0)
        
        md.append(f"| {tx['timestamp'].split('T')[1][:8]} | {name} | **{tx['action']}** | {tx['quantity']} 주 | {tx['price']:,.0f} 원 | {amt:,.0f} 원 | {post_bal:,.0f} 원 |")
        md.append(f"|   | **판단 근거**: | <td colspan='5'>{tx['reasoning']}</td> |")

# Write to file
output_dir = r"C:\Users\shout\.gemini\antigravity\brain\cc94869c-3453-49c1-822f-97a524563c24"
os.makedirs(output_dir, exist_ok=True)
report_path = os.path.join(output_dir, "analysis_results.md")

with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(md))

print(f"Report successfully written to {report_path}")
