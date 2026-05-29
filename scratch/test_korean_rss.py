import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import json

def test_feed(name, url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        print(f"\n--- Testing {name} ---")
        response = requests.get(url, headers=headers, timeout=10)
        # Force encoding to utf-8 if requests got it wrong
        response.encoding = 'utf-8'
        
        # Parse XML using ElementTree
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        if not items:
            items = root.findall("channel/item")
            
        results = []
        for item in items[:3]:
            title_elem = item.find("title")
            title = title_elem.text if title_elem is not None else "No Title"
            
            link_elem = item.find("link")
            link = link_elem.text if link_elem is not None else ""
            
            description = ""
            desc_elem = item.find("description")
            if desc_elem is not None and desc_elem.text:
                description = BeautifulSoup(desc_elem.text, "html.parser").get_text()
                
            results.append({
                "title": title.strip(),
                "link": link.strip(),
                "description": description.strip()[:100]
            })
            
        # Write to a test JSON file with utf-8 encoding to see if Korean is saved properly
        filename = f"scratch_test_{name.replace(' ', '_')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        print(f"Successfully saved {len(results)} items to {filename}")
        
        # Print representation to see if characters are correct
        for i, item in enumerate(results):
            print(f"Item {i+1}:")
            print(f"  Title: {repr(item['title'])}")
            print(f"  Description: {repr(item['description'])}")
            
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    test_feed("Maeil Business Economy", "https://www.mk.co.kr/rss/30100041/")
    test_feed("Hankyung Finance", "https://www.hankyung.com/feed/finance")
