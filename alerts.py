import requests

def send_telegram_alert(token, chat_id, title, summary, alert_level, sentiment):
    """
    Sends a formatted real-time push alert to a Telegram channel/chat.
    """
    if not token or not chat_id:
        return False
        
    url = f"https://api.telegram.org/bot{token.strip()}/sendMessage"
    
    emoji = "🚨" if alert_level == "HIGH" else "⚠️"
    sent_icon = "📈" if sentiment == "POSITIVE" else ("📉" if sentiment == "NEGATIVE" else "⚖️")
    
    text = (
        f"{emoji} *[K-이코노미 모니터 고위험 경보]*\n\n"
        f"*기사 제목:* {title}\n"
        f"*경보 등급:* {alert_level} | *AI 감성:* {sent_icon} {sentiment}\n\n"
        f"*Gemini 한글 요약 및 거시 영향:*\n{summary}\n\n"
        f"📊 실시간 현황판: http://localhost:5000"
    )
    
    payload = {
        "chat_id": chat_id.strip(),
        "text": text,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=8)
        return response.status_code == 200
    except Exception as e:
        print(f"[Warning] Failed to send Telegram alert: {str(e)}")
        return False

def send_slack_alert(webhook_url, title, summary, alert_level, sentiment):
    """
    Sends a formatted rich-block alert to a Slack incoming webhook.
    """
    if not webhook_url:
        return False
        
    emoji = "🚨" if alert_level == "HIGH" else "⚠️"
    color = "#f43f5e" if alert_level == "HIGH" else "#f97316"
    sent_icon = "📈" if sentiment == "POSITIVE" else ("📉" if sentiment == "NEGATIVE" else "⚖️")
    
    payload = {
        "attachments": [
            {
                "color": color,
                "pretext": f"{emoji} *[한반도 경제 모니터링 고위험 경보]*",
                "title": title,
                "fields": [
                    {
                        "title": "경보 수준",
                        "value": alert_level,
                        "short": True
                    },
                    {
                        "title": "AI 시장 감성",
                        "value": f"{sent_icon} {sentiment}",
                        "short": True
                    },
                    {
                        "title": "Gemini 실시간 종합 브리핑 요약",
                        "value": summary,
                        "short": False
                    }
                ],
                "footer": "한반도 실시간 경제 모니터링 시스템 | http://localhost:5000",
                "ts": None
            }
        ]
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=8)
        return response.status_code == 200
    except Exception as e:
        print(f"[Warning] Failed to send Slack alert: {str(e)}")
        return False

if __name__ == "__main__":
    print("[Alerts] Testing module imports (Silent execution if keys are empty)...")
    # Simple dry test
    result_tg = send_telegram_alert("", "", "테스트 기사", "요약내용", "HIGH", "POSITIVE")
    result_slack = send_slack_alert("", "테스트 기사", "요약내용", "HIGH", "POSITIVE")
    print(f"Telegram mock run success: {result_tg} | Slack mock run success: {result_slack}")
