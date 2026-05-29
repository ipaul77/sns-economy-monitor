import requests

def save_raw(name, url, filename):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        with open(filename, "wb") as f:
            f.write(response.content)
        print(f"Saved {name} raw bytes to {filename}")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    save_raw("Maeil Business Economy", "https://www.mk.co.kr/rss/30100041/", "mk.xml")
    save_raw("Hankyung Finance", "https://www.hankyung.com/feed/finance", "hk.xml")
