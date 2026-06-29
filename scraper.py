import os
import json
import random
from datetime import datetime, timedelta, timezone
import email.utils
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import warnings
from bs4 import XMLParsedAsHTMLWarning

# Suppress XML parsed as HTML warnings to keep CLI reports clean and pristine
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def fetch_rss_feeds(feed_list):
    """
    Fetches news from the provided RSS feeds.
    Parses RSS items into a standardized format using xml.etree.ElementTree.
    """
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for feed in feed_list:
        name = feed.get("name", "Unknown Source")
        url = feed.get("url")
        if not url:
            continue
            
        try:
            print(f"[Scraper] Fetching RSS feed: {name} ({url})")
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"[Warning] Failed to fetch feed {name}, status: {response.status_code}")
                continue
                
            # Parse XML standardly using ElementTree
            root = ET.fromstring(response.content)
            
            # Find all <item> tags (supports basic namespace variations using wildcards if needed)
            items = root.findall(".//item")
            if not items:
                # Fallback if channel/item structure is explicit
                items = root.findall("channel/item")
            
            for item in items[:5]:  # Limit to top 5 per feed to minimize API token usage
                title_elem = item.find("title")
                title = title_elem.text if title_elem is not None else "No Title"
                
                link_elem = item.find("link")
                link = link_elem.text if link_elem is not None else ""
                
                # Try standard publication date fields
                pub_date_str = ""
                pub_date_elem = item.find("pubDate")
                if pub_date_elem is not None:
                    pub_date_str = pub_date_elem.text
                else:
                    # check for dc:date or other tags
                    dc_date = item.find("{http://purl.org/dc/elements/1.1/}date")
                    if dc_date is not None:
                        pub_date_str = dc_date.text
                
                # Standardize pub date to KST (UTC + 9)
                kst = timezone(timedelta(hours=9))
                pub_date = datetime.now(kst).replace(tzinfo=None).isoformat()
                if pub_date_str:
                    try:
                        # Attempt to parse standard RFC 2822 format (includes timezone info) and convert to KST
                        dt = email.utils.parsedate_to_datetime(pub_date_str)
                        pub_date = dt.astimezone(kst).replace(tzinfo=None).isoformat()
                    except Exception:
                        try:
                            # Fallback standard strptime parse if email.utils fails (assumed as UTC/GMT)
                            parsed_t = datetime.strptime(pub_date_str[:25].strip(), "%a, %d %b %Y %H:%M:%S")
                            parsed_t = parsed_t.replace(tzinfo=timezone.utc)
                            pub_date = parsed_t.astimezone(kst).replace(tzinfo=None).isoformat()
                        except Exception:
                            pass
                
                description = ""
                desc_elem = item.find("description")
                if desc_elem is not None and desc_elem.text:
                    # Clean up HTML tags if any
                    description = BeautifulSoup(desc_elem.text, "html.parser").get_text()
                
                articles.append({
                    "title": title.strip(),
                    "content": description.strip()[:500],  # Truncate content to avoid huge tokens
                    "source": name,
                    "url": link.strip(),
                    "published_at": pub_date
                })
        except Exception as e:
            print(f"[Error] Failed parsing RSS feed {name}: {str(e)}")
            
    return articles

def generate_mock_sns_posts(personalities):
    """
    Generates realistic economic & business posts from global personalities.
    Includes both general global posts and highly South Korea-relevant posts
    to test the 2-stage filtering/routing analyzer.
    """
    posts = []
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).replace(tzinfo=None)
    
    # Pre-defined mock scenarios
    scenarios = [
        {
            "author": "Elon Musk",
            "title": "Tesla Giga Factory expansion",
            "content": "Looking into next locations for Giga factories. Asia is highly competitive. Korea has incredibly advanced battery supply chains and amazing engineering talent. Under high consideration.",
            "url_slug": "musk-tesla-giga-korea",
            "korean_relevant": True
        },
        {
            "author": "Elon Musk",
            "title": "Tesla Full Self-Driving progress",
            "content": "FSD Beta version 12 is mind-blowing. Truly end-to-end neural nets driving the car. Releases soon in North America, Europe and other regions later this year.",
            "url_slug": "musk-fsd-progress",
            "korean_relevant": False
        },
        {
            "author": "Jensen Huang",
            "title": "NVIDIA Blackwell chips shipping",
            "content": "Blackwell production is in full swing. The demand for AI hardware is surging exponentially. We are working closely with our key HBM3e suppliers like Samsung Electronics and SK Hynix in South Korea to secure next-gen memory components.",
            "url_slug": "huang-nvidia-blackwell-hbm",
            "korean_relevant": True
        },
        {
            "author": "Jensen Huang",
            "title": "NVIDIA AI summits globally",
            "content": "Excited for the next set of AI summits in London and Tokyo. Generative AI is reshaping every business workflow and industry globally. The intelligence revolution is just starting.",
            "url_slug": "huang-nvidia-ai-summits",
            "korean_relevant": False
        },
        {
            "author": "Sam Altman",
            "title": "OpenAI sovereign infrastructure",
            "content": "Met with global technology leaders to discuss GPU infrastructure and energy grids. South Korea's chip dominance makes it a core partner for the upcoming global AI infrastructure alliance.",
            "url_slug": "altman-ai-infrastructure",
            "korean_relevant": True
        },
        {
            "author": "Sam Altman",
            "title": "GPT-5 release preparations",
            "content": "Our teams are focused on aligning and safety-testing our next frontier model. The leap in reasoning capabilities will surprise people. Super excited for what is to come.",
            "url_slug": "altman-gpt5-prep",
            "korean_relevant": False
        },
        {
            "author": "Jerome Powell",
            "title": "FED interest rate policy briefing",
            "content": "Inflation is moderating but remains slightly above our 2% target. We will keep interest rates steady until we see clear evidence of soft landing. Strong dollar policies remain.",
            "url_slug": "powell-interest-rate-update",
            "korean_relevant": True  # Interest rate changes affect KRW exchange rate and KOSPI significantly
        },
        {
            "author": "Tim Cook",
            "title": "Apple Vision Pro sales expansion",
            "content": "Apple Vision Pro is now expanding to more global markets. Spatial computing is officially here, and developers are creating incredible applications that redefine work and play.",
            "url_slug": "cook-vision-pro",
            "korean_relevant": False
        }
    ]
    
    # Filter by user's target personalities in config
    active_scenarios = [s for s in scenarios if s["author"] in personalities]
    if not active_scenarios:
        active_scenarios = scenarios
        
    # Pick a few random posts to return to simulate dynamic real-time posts
    selected = random.sample(active_scenarios, k=min(4, len(active_scenarios)))
    
    for i, s in enumerate(selected):
        # Slightly jitter the timestamp
        time_jitter = now - timedelta(minutes=random.randint(1, 30))
        posts.append({
            "title": f"@{s['author']} post: {s['title']}",
            "content": s["content"],
            "source": f"SNS ({s['author']})",
            "url": f"https://x.com/{s['author'].replace(' ', '').lower()}/status/{s['url_slug']}-{int(time_jitter.timestamp())}",
            "published_at": time_jitter.isoformat()
        })
        
    return posts

def fetch_all_sources(config):
    """
    Orchestrates all scrapers (RSS & SNS Mock) and merges contents cleanly.
    """
    rss_feeds = config.get("rss_feeds", [])
    personalities = config.get("target_personalities", [])
    
    # Fetch live news from RSS
    news_articles = fetch_rss_feeds(rss_feeds)
    
    # Fetch mock celebrity posts
    sns_posts = generate_mock_sns_posts(personalities)
    
    # Merge and return
    total_data = news_articles + sns_posts
    print(f"[Scraper] Successfully collected {len(total_data)} raw contents ({len(news_articles)} RSS, {len(sns_posts)} SNS Mock).")
    return total_data

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run scraper in test mode")
    args = parser.parse_args()
    
    if args.test:
        print("[Scraper] Running in TEST mode...")
        # Define inline minimal config
        test_config = {
            "rss_feeds": [
                {
                    "name": "Yahoo Finance",
                    "url": "https://finance.yahoo.com/news/rssindex"
                }
            ],
            "target_personalities": ["Elon Musk", "Jensen Huang", "Sam Altman"]
        }
        results = fetch_all_sources(test_config)
        print("\n--- SAMPLE SCAPE RESULTS ---")
        for item in results[:5]:
            print(f"\nSource: {item['source']}")
            print(f"Title: {item['title']}")
            print(f"URL: {item['url']}")
            print(f"Published: {item['published_at']}")
            print(f"Content: {item['content'][:150]}...")
            print("-" * 30)
