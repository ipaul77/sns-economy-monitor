import os
import json
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone

def get_kst_now():
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).replace(tzinfo=None)

# Try to import Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "monitor.db")

USE_FIREBASE = False
db_client = None
CACHE_WARMED = False

# Initialize Database connection (Firebase or SQLite)
def init_db():
    global USE_FIREBASE, db_client
    if not FIREBASE_AVAILABLE:
        print("[DB] firebase-admin package is not installed. Falling back to local SQLite.")
        return

    def safe_init(cred):
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(cred)

    # 1. Check Render / Cloud Environment Variable first
    cred_json = os.getenv("FIREBASE_CREDENTIALS")
    if cred_json:
        try:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
            safe_init(cred)
            db_client = firestore.client()
            USE_FIREBASE = True
            print("[DB] Successfully initialized Firebase Firestore via Environment Variable!")
            return
        except Exception as e:
            print(f"[Warning] Failed to initialize Firebase using env var: {str(e)}")

    # 2. Check local JSON file fallback (ignored by Git)
    cred_file_path = "firebase_credentials.json"
    if os.path.exists(cred_file_path):
        try:
            cred = credentials.Certificate(cred_file_path)
            safe_init(cred)
            db_client = firestore.client()
            USE_FIREBASE = True
            print("[DB] Successfully initialized Firebase Firestore via local JSON credentials!")
            return
        except Exception as e:
            print(f"[Warning] Failed to initialize Firebase using local JSON: {str(e)}")

    print("[DB] Firebase credentials not found. Falling back to local SQLite.")

# Execute initialization immediately on module load
init_db()

def get_doc_id(url: str) -> str:
    """
    Generates a safe, unique 64-character document ID from a URL using SHA-256.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()

def get_similarity(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def save_embedding(url: str, embedding: list) -> bool:
    """
    Saves or updates a vector embedding list in SQLite.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        emb_json = json.dumps(embedding)
        cursor.execute("INSERT OR REPLACE INTO news_embeddings (url, embedding) VALUES (?, ?)", (url, emb_json))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] [Error] Failed to save embedding for {url}: {e}")
        return False

def get_embedding(url: str) -> Optional[list]:
    """
    Retrieves a cached vector embedding from SQLite.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT embedding FROM news_embeddings WHERE url = ?", (url,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        print(f"[DB] [Error] Failed to get embedding for {url}: {e}")
    return None

def cosine_similarity(v1: list, v2: list) -> float:
    """
    Calculates the cosine similarity between two float vectors.
    """
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(x * y for x, y in zip(v1, v2))
    norm_v1 = sum(x * x for x in v1) ** 0.5
    norm_v2 = sum(x * x for x in v2) ** 0.5
    if norm_v1 * norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

# --- PUBLIC DATABASE INTERFACE METHOD ADAPTERS ---

def setup_db():
    """
    Sets up SQLite tables locally if using SQLite. Does nothing for Firestore.
    """
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            url TEXT PRIMARY KEY,
            title TEXT,
            content TEXT,
            source TEXT,
            published_at TEXT,
            processed_at TEXT,
            is_relevant INTEGER,
            relevance_reason TEXT,
            sentiment TEXT,
            sentiment_score REAL,
            relevance_score INTEGER,
            impacted_sectors TEXT,
            impacted_companies TEXT,
            macro_impacts TEXT,
            korean_summary TEXT,
            alert_level TEXT,
            other_sources TEXT,
            impacted_tickers TEXT
        )
    """)
    conn.commit()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news_embeddings (
            url TEXT PRIMARY KEY,
            embedding TEXT
        )
    """)
    conn.commit()
    
    # Fundamentals cache table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            ticker TEXT PRIMARY KEY,
            roe REAL,
            pe_ratio REAL,
            pb_ratio REAL,
            debt_to_equity REAL,
            free_cash_flow REAL,
            target_price REAL,
            eps REAL,
            bps REAL,
            last_updated TEXT
        )
    """)
    conn.commit()
    
    # Column migration safety for fundamentals table
    try:
        cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN eps REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE stock_fundamentals ADD COLUMN bps REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    # Column migration safety
    try:
        cursor.execute("ALTER TABLE history ADD COLUMN other_sources TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass # Already exists
        
    try:
        cursor.execute("ALTER TABLE history ADD COLUMN impacted_tickers TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass # Already exists
        
    conn.close()
    
    # Warm start SQLite cache from Firestore on startup
    if USE_FIREBASE:
        try:
            _warm_start_cache()
        except Exception as e:
            print(f"[Warning] Failed to warm start SQLite cache: {str(e)}")


def _warm_start_cache():
    """
    Fetches the latest 300 records from Firestore and populates the local SQLite database.
    This acts as a local cache so that we don't have to query Firestore for duplicate checks
    every time the scraper runs.
    """
    global CACHE_WARMED
    if not USE_FIREBASE or db_client is None:
        return
    try:
        print("[DB] Warm-starting local SQLite cache from Firestore...")
        
        # Query Firestore
        docs = db_client.collection("history")\
                        .order_by("processed_at", direction=firestore.Query.DESCENDING)\
                        .limit(300)\
                        .stream()
                        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        count = 0
        for doc in docs:
            r = doc.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO history (
                    url, title, content, source, published_at, processed_at, 
                    is_relevant, relevance_reason, sentiment, sentiment_score, 
                    relevance_score, impacted_sectors, impacted_companies, impacted_tickers,
                    macro_impacts, korean_summary, alert_level, other_sources
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r.get("url"), r.get("title"), r.get("content"), r.get("source"), r.get("published_at"), r.get("processed_at"),
                r.get("is_relevant"), r.get("relevance_reason"), r.get("sentiment"), r.get("sentiment_score"), 
                r.get("relevance_score"), r.get("impacted_sectors"), r.get("impacted_companies"), r.get("impacted_tickers"),
                r.get("macro_impacts"), r.get("korean_summary"), r.get("alert_level"), r.get("other_sources")
            ))
            count += 1
        conn.commit()
        conn.close()
        CACHE_WARMED = True
        print(f"[DB] Successfully loaded {count} recent records from Firestore into local SQLite cache.")
    except Exception as e:
        check_firestore_quota_error(e)
        print(f"[Warning] Firestore warm start failed: {str(e)}")



def check_firestore_quota_error(error_exception):
    """
    Checks if a Firestore exception is due to quota exhaustion (429 Quota Exceeded).
    If so, dynamically switches to local SQLite mode to avoid latency and ensure 100% uptime.
    """
    global USE_FIREBASE
    err_msg = str(error_exception)
    if "429" in err_msg or "quota" in err_msg.lower():
        if USE_FIREBASE:
            print("\n[DB] [CRITICAL WARNING] Google Firestore Quota Exceeded (429)! "
                  "Dynamically switching to local SQLite database (monitor.db) for the rest of this session to ensure 100% uptime.\n")
            USE_FIREBASE = False

def is_already_processed(url: str) -> bool:
    """
    Checks if a URL has already been processed.
    """
    # 1. 1차 로컬 SQLite 사전 판별 (무료 및 초고속 캐시 조회)
    if _sqlite_is_already_processed(url):
        return True

    # 2. 캐시가 워밍업된 상태인 경우, 로컬에 기사가 없다면 Firestore에도 존재하지 않는 신규 기사로 즉시 판단 (Firestore Read 절약)
    if CACHE_WARMED:
        return False

    # 3. 로컬에 없는 경우에만 비상 Fallback으로 Firestore를 조회
    if USE_FIREBASE:
        try:
            doc_id = get_doc_id(url)
            doc_ref = db_client.collection("history").document(doc_id)
            doc = doc_ref.get()
            return doc.exists
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Error] Firestore is_already_processed failed: {str(e)}")
            # Fail-safe SQLite check if Firebase fails mid-flight
            return _sqlite_is_already_processed(url)
    else:
        return _sqlite_is_already_processed(url)

def _sqlite_is_already_processed(url: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM history WHERE url = ?", (url,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def find_similar(title: str, analyzer = None) -> Optional[dict]:
    """
    Checks if a similar news story is already processed in SQLite.
    If analyzer is passed and API is active, performs vector embedding similarity search.
    Otherwise falls back to character-level difflib sequence matching.
    """
    local_similar = _sqlite_find_similar(title, analyzer)
    if local_similar:
        print(f"[DB] [Cache Hit] Found similar story: '{local_similar['title']}'")
        return local_similar
    return None

def _sqlite_find_similar(title: str, analyzer = None) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM history")
    rows = cursor.fetchall()
    conn.close()
    
    if analyzer and hasattr(analyzer, "get_embedding") and analyzer.api_configured:
        incoming_embedding = analyzer.get_embedding(title)
        if incoming_embedding:
            # Fetch all cached embeddings
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT url, embedding FROM news_embeddings")
            emb_rows = cursor.fetchall()
            conn.close()
            
            emb_map = {}
            for r in emb_rows:
                try:
                    emb_map[r[0]] = json.loads(r[1])
                except:
                    pass
            
            best_match = None
            best_score = 0.0
            
            for row in rows:
                row_dict = dict(row)
                url = row_dict["url"]
                cached_emb = emb_map.get(url)
                if cached_emb:
                    score = cosine_similarity(incoming_embedding, cached_emb)
                    if score > best_score:
                        best_score = score
                        best_match = row_dict
            
            if best_score > 0.82 and best_match:
                print(f"[DB] [Semantic Match] Similarity {best_score:.1%} between incoming and cached: '{best_match['title']}'")
                return best_match
            else:
                if best_score > 0:
                    print(f"[DB] [No Semantic Match] Closest match: {best_score:.1%} - '{best_match['title'] if best_match else 'None'}'")
                
    # Fallback to difflib character matching
    for r in rows:
        row_dict = dict(r)
        if get_similarity(title, row_dict['title']) > 0.75:
            return row_dict
    return None

def update_other_sources(url: str, new_source: str):
    """
    Appends a new reporting source to the co-reporting sources list for a given URL.
    """
    if USE_FIREBASE:
        try:
            doc_id = get_doc_id(url)
            doc_ref = db_client.collection("history").document(doc_id)
            doc = doc_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                other_sources_str = data.get("other_sources", "[]")
                try:
                    current_sources = json.loads(other_sources_str)
                except:
                    current_sources = [x.strip() for x in other_sources_str.split(",") if x.strip()]
                    
                if new_source not in current_sources:
                    current_sources.append(new_source)
                    doc_ref.update({
                        "other_sources": json.dumps(current_sources, ensure_ascii=False)
                    })
                    print(f"[Firestore] Merged source '{new_source}' into existing story.")
                    
                    # Also write to local SQLite as a cache
                    try:
                        _sqlite_update_other_sources(url, new_source)
                    except Exception as sq_err:
                        print(f"[Warning] Failed to update local SQLite cache: {str(sq_err)}")
            return
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Error] Firestore update_other_sources failed: {str(e)}")
            return _sqlite_update_other_sources(url, new_source)
    else:
        _sqlite_update_other_sources(url, new_source)

def _sqlite_update_other_sources(url: str, new_source: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT other_sources FROM history WHERE url = ?", (url,))
    row = cursor.fetchone()
    
    current_sources = []
    if row and row[0]:
        try:
            current_sources = json.loads(row[0])
        except:
            current_sources = [x.strip() for x in row[0].split(",") if x.strip()]
            
    if new_source not in current_sources:
        current_sources.append(new_source)
        cursor.execute("UPDATE history SET other_sources = ? WHERE url = ?", (json.dumps(current_sources, ensure_ascii=False), url))
        conn.commit()
    conn.close()

def save_analysis_result(item: dict, rel_check, analysis, other_sources=None, analyzer=None):
    """
    Saves a newly processed article and its structured AI analysis results.
    """
    now_str = get_kst_now().isoformat()
    is_relevant_int = 1 if rel_check.relevant else 0
    relevance_reason = rel_check.reason
    
    if analysis:
        sentiment = analysis.sentiment
        sentiment_score = analysis.sentiment_score
        relevance_score = analysis.relevance_score
        impacted_sectors = json.dumps(analysis.impacted_sectors, ensure_ascii=False)
        impacted_companies = json.dumps(analysis.impacted_companies, ensure_ascii=False)
        impacted_tickers = json.dumps(getattr(analysis, "impacted_tickers", []), ensure_ascii=False)
        macro_impacts = analysis.macro_impacts
        korean_summary = analysis.korean_summary
        alert_level = analysis.alert_level
    else:
        sentiment = None
        sentiment_score = None
        relevance_score = None
        impacted_sectors = None
        impacted_companies = None
        impacted_tickers = None
        macro_impacts = None
        korean_summary = None
        alert_level = None
        
    other_sources_json = json.dumps(other_sources, ensure_ascii=False) if other_sources else "[]"
    
    # Cache embedding if analyzer is active (0 additional Firestore reads/writes, saved locally)
    if analyzer and hasattr(analyzer, "get_embedding") and analyzer.api_configured:
        embedding = analyzer.get_embedding(item["title"])
        if embedding:
            save_embedding(item["url"], embedding)

    if USE_FIREBASE:
        try:
            doc_id = get_doc_id(item["url"])
            doc_ref = db_client.collection("history").document(doc_id)
            
            doc_data = {
                "url": item["url"],
                "title": item["title"],
                "content": item["content"],
                "source": item["source"],
                "published_at": item["published_at"],
                "processed_at": now_str,
                "is_relevant": is_relevant_int,
                "relevance_reason": relevance_reason,
                "sentiment": sentiment,
                "sentiment_score": sentiment_score,
                "relevance_score": relevance_score,
                "impacted_sectors": impacted_sectors,
                "impacted_companies": impacted_companies,
                "impacted_tickers": impacted_tickers,
                "macro_impacts": macro_impacts,
                "korean_summary": korean_summary,
                "alert_level": alert_level,
                "other_sources": other_sources_json
            }
            
            doc_ref.set(doc_data)
            print(f"[Firestore] Successfully saved record: {item['title']}")
            
            # Also write to local SQLite as a cache
            try:
                _sqlite_save_analysis_result(item, rel_check, analysis, other_sources, now_str, is_relevant_int, relevance_reason, sentiment, sentiment_score, relevance_score, impacted_sectors, impacted_companies, impacted_tickers, macro_impacts, korean_summary, alert_level, other_sources_json)
            except Exception as sq_err:
                print(f"[Warning] Failed to write local SQLite cache: {str(sq_err)}")
                
            return
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Error] Firestore save_analysis_result failed: {str(e)}")
            _sqlite_save_analysis_result(item, rel_check, analysis, other_sources, now_str, is_relevant_int, relevance_reason, sentiment, sentiment_score, relevance_score, impacted_sectors, impacted_companies, impacted_tickers, macro_impacts, korean_summary, alert_level, other_sources_json)
    else:
        _sqlite_save_analysis_result(item, rel_check, analysis, other_sources, now_str, is_relevant_int, relevance_reason, sentiment, sentiment_score, relevance_score, impacted_sectors, impacted_companies, impacted_tickers, macro_impacts, korean_summary, alert_level, other_sources_json)

def _sqlite_save_analysis_result(item, rel_check, analysis, other_sources, now_str, is_relevant_int, relevance_reason, sentiment, sentiment_score, relevance_score, impacted_sectors, impacted_companies, impacted_tickers, macro_impacts, korean_summary, alert_level, other_sources_json):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO history (
                url, title, content, source, published_at, processed_at, 
                is_relevant, relevance_reason, sentiment, sentiment_score, 
                relevance_score, impacted_sectors, impacted_companies, impacted_tickers,
                macro_impacts, korean_summary, alert_level, other_sources
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item["url"], item["title"], item["content"], item["source"], item["published_at"], now_str,
            is_relevant_int, relevance_reason, sentiment, sentiment_score, 
            relevance_score, impacted_sectors, impacted_companies, impacted_tickers,
            macro_impacts, korean_summary, alert_level, other_sources_json
        ))
        conn.commit()
    except Exception as e:
        print(f"[Error] Failed to save record to SQLite DB: {str(e)}")
    finally:
        conn.close()


def fetch_history(limit=100) -> list:
    """
    Fetches the latest database records sorted by processed_at descending.
    """
    if USE_FIREBASE:
        try:
            docs = db_client.collection("history")\
                            .order_by("processed_at", direction=firestore.Query.DESCENDING)\
                            .limit(limit)\
                            .stream()
            results = []
            for doc in docs:
                results.append(doc.to_dict())
            return results
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Error] Firestore fetch_history failed: {str(e)}")
            return _sqlite_fetch_history(limit)
    else:
        return _sqlite_fetch_history(limit)

def _sqlite_fetch_history(limit=100) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM history ORDER BY processed_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fetch_recent_relevant(hours=24) -> list:
    """
    Fetches relevant articles processed within the last N hours.
    Optimized: Always queries local SQLite first to avoid expensive Firestore read streams.
    """
    cutoff = (get_kst_now() - timedelta(hours=hours)).isoformat()
    return _sqlite_fetch_recent_relevant(cutoff)

def _sqlite_fetch_recent_relevant(cutoff: str) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM history 
        WHERE is_relevant = 1 AND processed_at >= ?
        ORDER BY processed_at DESC
    """, (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fetch_total_count() -> int:
    """
    Retrieves the total count of processed items.
    """
    if USE_FIREBASE:
        try:
            # Firestore count query is extremely lightweight and cheap
            count_query = db_client.collection("history").count()
            results = count_query.get()
            return results[0][0].value
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Error] Firestore fetch_total_count failed: {str(e)}")
            return _sqlite_fetch_total_count()
    else:
        return _sqlite_fetch_total_count()

def _sqlite_fetch_total_count() -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM history")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

def purge_old_records(retention_days=14) -> int:
    """
    Cleans up old analysis history documents that are older than the retention threshold.
    Crucial for keeping Firestore database size forever free!
    """
    cutoff = (get_kst_now() - timedelta(days=retention_days)).isoformat()
    deleted_count = 0
    
    if USE_FIREBASE:
        try:
            docs = db_client.collection("history")\
                            .where("processed_at", "<", cutoff)\
                            .stream()
            # Batch deletions to keep operations atomic and highly optimized
            batch = db_client.batch()
            for doc in docs:
                batch.delete(doc.reference)
                deleted_count += 1
                
            if deleted_count > 0:
                batch.commit()
                print(f"[Firestore Purge] Successfully deleted {deleted_count} records older than {retention_days} days.")
            return deleted_count
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Error] Firestore purge_old_records failed: {str(e)}")
            return _sqlite_purge_old_records(cutoff)
    else:
        return _sqlite_purge_old_records(cutoff)

def _sqlite_purge_old_records(cutoff: str) -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history WHERE processed_at < ?", (cutoff,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted_count > 0:
            print(f"[SQLite Purge] Successfully deleted {deleted_count} records older than configured threshold.")
        return deleted_count
    except Exception as e:
        print(f"[Error] SQLite database purge failed: {str(e)}")
        return 0

def save_fundamentals(ticker: str, data: dict):
    """
    Saves or updates the fundamental financial data for a stock ticker.
    Writes to both Firestore (if available) and local SQLite.
    """
    now_str = get_kst_now().isoformat()
    # Sanitize inputs (ensure no NaNs or invalid values before database writing)
    def safe_float(val):
        if val is None:
            return None
        try:
            f_val = float(val)
            import math
            if math.isnan(f_val) or math.isinf(f_val):
                return None
            return f_val
        except:
            return None

    cleaned = {
        "ticker": ticker.strip(),
        "roe": safe_float(data.get("roe")),
        "pe_ratio": safe_float(data.get("pe_ratio")),
        "pb_ratio": safe_float(data.get("pb_ratio")),
        "debt_to_equity": safe_float(data.get("debt_to_equity")),
        "free_cash_flow": safe_float(data.get("free_cash_flow")),
        "target_price": safe_float(data.get("target_price")),
        "eps": safe_float(data.get("eps")),
        "bps": safe_float(data.get("bps")),
        "last_updated": now_str
    }
    
    # 1. Firestore Write
    if USE_FIREBASE and db_client is not None:
        try:
            doc_ref = db_client.collection("stock_fundamentals").document(ticker)
            doc_ref.set(cleaned)
            print(f"[Firestore] Successfully saved fundamentals for {ticker}")
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Warning] Firestore save_fundamentals failed: {e}")
            
    # 2. SQLite Write
    _sqlite_save_fundamentals(cleaned)

def _sqlite_save_fundamentals(data: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO stock_fundamentals (
                ticker, roe, pe_ratio, pb_ratio, debt_to_equity, free_cash_flow, target_price, eps, bps, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["ticker"], data["roe"], data["pe_ratio"], data["pb_ratio"], 
            data["debt_to_equity"], data["free_cash_flow"], data["target_price"],
            data["eps"], data["bps"], data["last_updated"]
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Error] SQLite save_fundamentals failed: {e}")

def fetch_fundamentals(ticker: str) -> dict:
    """
    Retrieves fundamental financial data for a stock ticker.
    Checks SQLite first. If SQLite has no record, falls back to querying Firestore to restore the cache.
    Returns: Dict or None
    """
    ticker = ticker.strip()
    # 1. Query SQLite Cache first
    local_data = _sqlite_fetch_fundamentals(ticker)
    if local_data:
        return local_data
        
    # 2. SQLite cache miss (e.g. Render spin down/reset), try Firestore fallback
    if USE_FIREBASE and db_client is not None:
        try:
            doc_ref = db_client.collection("stock_fundamentals").document(ticker)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                # Restore SQLite local cache
                _sqlite_save_fundamentals(data)
                print(f"[DB] Restored fundamental cache for {ticker} from Firestore.")
                return data
        except Exception as e:
            check_firestore_quota_error(e)
            print(f"[Warning] Firestore fetch_fundamentals failed: {e}")
            
    return None

def _sqlite_fetch_fundamentals(ticker: str) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stock_fundamentals WHERE ticker = ?", (ticker,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[Error] SQLite fetch_fundamentals failed: {e}")
        return None
