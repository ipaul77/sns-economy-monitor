import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
import db

class KISClient:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.app_key = ""
        self.app_secret = ""
        self.is_simulation = False
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.local_token_path = os.path.join("data", "kis_token.json")
        
        # Memory caching to avoid repeating Firestore queries in the same process
        self._memory_token = ""
        self._memory_expires_at = None
        
        self._load_config()
        self._resolve_base_url()

    def _load_config(self):
        """
        Loads API credentials from environment variables first,
        falling back to config.json.
        """
        # Load local .env manually if it exists to support local development
        if os.path.exists(".env"):
            try:
                with open(".env", "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ[k.strip()] = v.strip()
            except Exception as e:
                print(f"[KIS Client] [Warning] Failed to load .env file: {e}")

        # 1. Try Environment Variables (Ideal for Render)
        self.app_key = os.getenv("KIS_APP_KEY", "").strip()
        self.app_secret = os.getenv("KIS_APP_SECRET", "").strip()
        sim_env = os.getenv("KIS_IS_SIMULATION")
        if sim_env is not None:
            self.is_simulation = sim_env.lower() in ("true", "1", "yes")

        # 2. Try config.json if Env Vars are not set
        if not self.app_key or not self.app_secret:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        kis_cfg = cfg.get("kis", {})
                        if kis_cfg:
                            if not self.app_key:
                                self.app_key = kis_cfg.get("app_key", "").strip()
                            if not self.app_secret:
                                self.app_secret = kis_cfg.get("app_secret", "").strip()
                            # Only set if not already set by env var
                            if sim_env is None:
                                self.is_simulation = kis_cfg.get("is_simulation", False)
                except Exception as e:
                    print(f"[KIS Client] Error reading config file: {e}")

    def _resolve_base_url(self):
        """
        Resolves the base URL. If KIS_IS_SIMULATION is explicitly configured, respects it.
        Otherwise, auto-detects based on App Key prefix.
        """
        env_sim = os.getenv("KIS_IS_SIMULATION")
        if env_sim is not None:
            self.is_simulation = env_sim.lower() in ("true", "1", "yes")
        else:
            # Fall back to App Key prefix auto-detection
            if self.app_key.startswith("OPS"):
                self.is_simulation = True
            elif self.app_key.startswith("PS"):
                self.is_simulation = False
            
        if self.is_simulation:
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            print(f"[KIS Client] Running in SIMULATION (Mock) mode. URL: {self.base_url}")
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            print(f"[KIS Client] Running in REAL trading mode. URL: {self.base_url}")

    def _get_now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _get_cached_token(self) -> tuple:
        """
        Retrieves the cached access token and expiration time.
        First tries Firestore, then falls back to local file.
        Returns: (access_token, expires_at_datetime) or (None, None)
        """
        # 1. Try Firestore cache
        if db.USE_FIREBASE and db.db_client is not None:
            try:
                doc_ref = db.db_client.collection("system").document("kis_auth")
                doc = doc_ref.get()
                if doc.exists:
                    data = doc.to_dict()
                    token = data.get("access_token")
                    expires_str = data.get("expires_at")
                    if token and expires_str:
                        expires_at = datetime.fromisoformat(expires_str)
                        return token, expires_at
            except Exception as e:
                print(f"[KIS Client] [Warning] Firestore token read failed: {e}")
                
        # 2. Fallback to Local File Cache
        if os.path.exists(self.local_token_path):
            try:
                with open(self.local_token_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    token = data.get("access_token")
                    expires_str = data.get("expires_at")
                    if token and expires_str:
                        expires_at = datetime.fromisoformat(expires_str)
                        return token, expires_at
            except Exception as e:
                print(f"[KIS Client] [Warning] Local token file read failed: {e}")

        return None, None

    def _save_cached_token(self, token: str, expires_at: datetime):
        """
        Saves the access_token and its expiration date to memory, Firestore, and local fallback.
        """
        # Save to memory cache first
        self._memory_token = token
        self._memory_expires_at = expires_at

        expires_str = expires_at.isoformat()
        payload = {
            "access_token": token,
            "expires_at": expires_str,
            "updated_at": self._get_now_utc().isoformat()
        }

        # 1. Save to Firestore
        if db.USE_FIREBASE and db.db_client is not None:
            try:
                doc_ref = db.db_client.collection("system").document("kis_auth")
                doc_ref.set(payload)
                print("[KIS Client] Access token cached successfully in Firestore.")
            except Exception as e:
                print(f"[KIS Client] [Warning] Firestore token write failed: {e}")

        # 2. Save to Local File Cache (always do this as backup/cache)
        try:
            os.makedirs(os.path.dirname(self.local_token_path), exist_ok=True)
            with open(self.local_token_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print("[KIS Client] Access token cached successfully in local JSON.")
        except Exception as e:
            print(f"[KIS Client] [Warning] Local token file write failed: {e}")

    def get_access_token(self) -> str:
        """
        Returns a valid KIS access token. Checks memory cache first,
        then DB/file cache, and issues a new one if expired or not found.
        """
        if not self.app_key or not self.app_secret:
            raise ValueError("[KIS Client] KIS_APP_KEY and KIS_APP_SECRET are not configured!")

        now = self._get_now_utc()

        # 1. Check Memory Cache (0 reads)
        if self._memory_token and self._memory_expires_at and (self._memory_expires_at - now > timedelta(minutes=10)):
            # Debug log to verify usage
            print(f"[KIS Client] Using MEMORY cached token. (Expires in {(self._memory_expires_at - now).total_seconds() / 3600:.2f} hours)")
            return self._memory_token

        # 2. Check DB/File Cache (Only if memory cache missed/expired)
        token, expires_at = self._get_cached_token()
        
        # If cache exists and expires in more than 10 minutes, save to memory and return it
        if token and expires_at and (expires_at - now > timedelta(minutes=10)):
            print(f"[KIS Client] Using DB/File cached token. Saving to memory. (Expires in {(expires_at - now).total_seconds() / 3600:.2f} hours)")
            self._memory_token = token
            self._memory_expires_at = expires_at
            return token

        # Issue new token
        print("[KIS Client] Cache expired or missing. Fetching new access token from KIS API...")
        path = "oauth2/tokenP"
        url = f"{self.base_url}/{path}"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        try:
            res = requests.post(url, headers=headers, json=body, timeout=10)
            if res.status_code != 200:
                raise Exception(f"HTTP {res.status_code}: {res.text}")
                
            res_data = res.json()
            new_token = res_data.get("access_token")
            if not new_token:
                raise Exception(f"Invalid response format: {res_data}")

            # KIS Token expires in 24 hours. We store local expires_at as 23 hours from now to be safe.
            expires_at = now + timedelta(hours=23)
            self._save_cached_token(new_token, expires_at)
            
            return new_token
        except Exception as e:
            print(f"[KIS Client] [Error] Failed to issue KIS access token: {e}")
            # If token issue failed, try to fallback to expired token as absolute last resort
            if token:
                print("[KIS Client] [Warning] Returning expired token as fallback.")
                return token
            raise e

    def get_current_price(self, ticker: str) -> float:
        """
        Fetches the current market price for a given 6-digit stock ticker code.
        Returns: price (float) if successful, None if it fails.
        """
        ticker = ticker.strip()
        if not ticker or len(ticker) != 6 or not ticker.isdigit():
            print(f"[KIS Client] Invalid ticker ignored: '{ticker}'")
            return None

        try:
            token = self.get_access_token()
        except Exception as e:
            print(f"[KIS Client] Could not acquire access token. Aborting price query. Error: {e}")
            return None

        path = "uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{self.base_url}/{path}"
        
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100",
            "custtype": "P"
        }
        
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": ticker
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code != 200:
                print(f"[KIS Client] [Warning] KIS Price query HTTP {res.status_code}: {res.text}")
                return None
                
            res_data = res.json()
            rt_cd = res_data.get("rt_cd")
            if rt_cd != "0":
                msg = res_data.get("msg1", "Unknown Error")
                print(f"[KIS Client] [Warning] KIS API error code {rt_cd}: {msg}")
                return None
                
            output = res_data.get("output", {})
            price_str = output.get("stck_prpr") # Current stock price
            if price_str:
                price = float(price_str)
                # Keep sanity check
                if price > 0:
                    return price
            
            print(f"[KIS Client] [Warning] Price data missing in response output: {output}")
            return None
        except Exception as e:
            print(f"[KIS Client] [Error] Failed to query current price for {ticker}: {e}")
            return None

# Singleton instance
kis_client = KISClient()
