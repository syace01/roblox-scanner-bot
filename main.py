"""
🎯 TRUE OMEGA ULTIMATE - Production-Grade Roblox Scanner Bot
Optimized for Railway.app deployment with PostgreSQL + Redis
"""

import os
import sys
import asyncio
import json
import time
import re
import io
import base64
import warnings
import traceback
import tempfile
import hashlib
import logging
import signal
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote, unquote
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Tuple, Any, Set
from enum import Enum
import functools

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# LOGGING SETUP (Structured for Railway)
# ═══════════════════════════════════════════════════════════
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data)

logger = logging.getLogger("true_omega")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)

# ═══════════════════════════════════════════════════════════
# CONFIGURATION & VALIDATION
# ═══════════════════════════════════════════════════════════
class Config:
    """Environment configuration with validation"""
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')  # Railway PostgreSQL
    REDIS_URL = os.getenv('REDIS_URL', '')  # Railway Redis
    SENTRY_DSN = os.getenv('SENTRY_DSN', '')
    
    # Optional configs
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '52428800'))  # 50MB
    OCR_TIMEOUT = int(os.getenv('OCR_TIMEOUT', '20'))
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT', '10'))
    CACHE_TTL = int(os.getenv('CACHE_TTL', '600'))  # 10 minutes
    
    @classmethod
    def validate(cls):
        """Fail fast if critical config missing"""
        if not cls.TOKEN:
            logger.error("❌ DISCORD_TOKEN not set!")
            sys.exit(1)
        logger.info("✅ Configuration validated")

Config.validate()

# ═══════════════════════════════════════════════════════════
# SENTRY ERROR TRACKING (Optional but recommended)
# ═══════════════════════════════════════════════════════════
if Config.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=Config.SENTRY_DSN,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
        )
        logger.info("✅ Sentry initialized")
    except ImportError:
        logger.warning("⚠️ Sentry DSN provided but sentry-sdk not installed")

# ═══════════════════════════════════════════════════════════
# IMPORTS WITH FALLBACKS
# ═══════════════════════════════════════════════════════════
import aiohttp
import discord
from discord import app_commands
from discord.ui import Button, View, Select

# Database imports (async)
try:
    import asyncpg
    DB_AVAILABLE = True
    logger.info("✅ asyncpg available")
except ImportError:
    DB_AVAILABLE = False
    logger.warning("⚠️ asyncpg not available, using JSON fallback")

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
    logger.info("✅ redis available")
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("⚠️ redis not available, using memory cache")

# OCR imports
try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    TESSERACT_AVAILABLE = True
    logger.info("✅ Tesseract available")
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("⚠️ Tesseract not available")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
    logger.info("✅ EasyOCR available")
except ImportError:
    EASYOCR_AVAILABLE = False

try:
    import numpy as np
    import cv2
    CV2_AVAILABLE = True
    logger.info("✅ OpenCV available")
except ImportError:
    CV2_AVAILABLE = False

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("⚠️ yt-dlp not available")

# ═══════════════════════════════════════════════════════════
# DATA CLASSES & ENUMS
# ═══════════════════════════════════════════════════════════
class ScanStatus(Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    LOW_CONFIDENCE = "low_confidence"

@dataclass
class ScanResult:
    status: ScanStatus
    profile: Optional[Dict] = None
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    alternatives: List[Dict] = field(default_factory=list)
    scan_time: float = 0.0
    ocr_engines_used: List[str] = field(default_factory=list)
    cached: bool = False
    thumbnail_url: Optional[str] = None
    error_message: Optional[str] = None
    suggested_usernames: List[str] = field(default_factory=list)

@dataclass
class UserStats:
    user_id: str
    total_scans: int = 0
    successful_scans: int = 0
    failed_scans: int = 0
    last_scan: Optional[datetime] = None
    favorite_users: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def success_rate(self) -> float:
        if self.total_scans == 0:
            return 0.0
        return (self.successful_scans / self.total_scans) * 100

# ═══════════════════════════════════════════════════════════
# DATABASE MANAGER (PostgreSQL with JSON fallback)
# ═══════════════════════════════════════════════════════════
class DatabaseManager:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.json_file = "bot_data.json"
        self._memory_cache: Dict[str, Any] = {}
        
    async def setup(self):
        if DB_AVAILABLE and Config.DATABASE_URL:
            try:
                self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=2, max_size=10)
                await self._create_tables()
                logger.info("✅ PostgreSQL connected")
            except Exception as e:
                logger.error(f"❌ PostgreSQL connection failed: {e}")
                logger.info("🔄 Falling back to JSON storage")
        else:
            logger.info("📁 Using JSON file storage")
            self._load_json()
    
    async def _create_tables(self):
        """Create tables if they don't exist"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id TEXT PRIMARY KEY,
                    total_scans INTEGER DEFAULT 0,
                    successful_scans INTEGER DEFAULT 0,
                    failed_scans INTEGER DEFAULT 0,
                    last_scan TIMESTAMP,
                    favorite_users JSONB DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id SERIAL PRIMARY KEY,
                    discord_user_id TEXT,
                    roblox_username TEXT,
                    roblox_id BIGINT,
                    confidence FLOAT,
                    success BOOLEAN,
                    scanned_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    user_id TEXT PRIMARY KEY,
                    added_by TEXT,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
    
    def _load_json(self):
        try:
            if os.path.exists(self.json_file):
                with open(self.json_file, 'r') as f:
                    self._memory_cache = json.load(f)
        except:
            self._memory_cache = {"user_stats": {}, "whitelist": [], "scan_history": []}
    
    def _save_json(self):
        try:
            with open(self.json_file, 'w') as f:
                json.dump(self._memory_cache, f, default=str)
        except Exception as e:
            logger.error(f"Failed to save JSON: {e}")
    
    async def get_user_stats(self, user_id: str) -> UserStats:
        if self.pool:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM user_stats WHERE user_id = $1", user_id
                )
                if row:
                    return UserStats(
                        user_id=row['user_id'],
                        total_scans=row['total_scans'],
                        successful_scans=row['successful_scans'],
                        failed_scans=row['failed_scans'],
                        last_scan=row['last_scan'],
                        favorite_users=json.loads(row['favorite_users']) if isinstance(row['favorite_users'], str) else row['favorite_users'],
                        created_at=row['created_at']
                    )
        else:
            data = self._memory_cache.get("user_stats", {}).get(user_id, {})
            if data:
                return UserStats(**data)
        
        return UserStats(user_id=user_id)
    
    async def update_user_stats(self, stats: UserStats):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO user_stats (user_id, total_scans, successful_scans, failed_scans, last_scan, favorite_users)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (user_id) DO UPDATE SET
                        total_scans = EXCLUDED.total_scans,
                        successful_scans = EXCLUDED.successful_scans,
                        failed_scans = EXCLUDED.failed_scans,
                        last_scan = EXCLUDED.last_scan,
                        favorite_users = EXCLUDED.favorite_users
                """, stats.user_id, stats.total_scans, stats.successful_scans, 
                     stats.failed_scans, stats.last_scan, json.dumps(stats.favorite_users))
        else:
            if "user_stats" not in self._memory_cache:
                self._memory_cache["user_stats"] = {}
            self._memory_cache["user_stats"][stats.user_id] = asdict(stats)
            self._save_json()
    
    async def add_scan_history(self, discord_user_id: str, username: str, roblox_id: int, 
                                confidence: float, success: bool):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO scan_history (discord_user_id, roblox_username, roblox_id, confidence, success)
                    VALUES ($1, $2, $3, $4, $5)
                """, discord_user_id, username, roblox_id, confidence, success)
        else:
            if "scan_history" not in self._memory_cache:
                self._memory_cache["scan_history"] = []
            self._memory_cache["scan_history"].append({
                "discord_user_id": discord_user_id,
                "roblox_username": username,
                "roblox_id": roblox_id,
                "confidence": confidence,
                "success": success,
                "scanned_at": datetime.utcnow().isoformat()
            })
            self._save_json()
    
    async def get_whitelist(self) -> Set[str]:
        if self.pool:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id FROM whitelist")
                return {row['user_id'] for row in rows}
        else:
            return set(self._memory_cache.get("whitelist", []))
    
    async def add_to_whitelist(self, user_id: str, added_by: str):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO whitelist (user_id, added_by) VALUES ($1, $2)
                    ON CONFLICT (user_id) DO NOTHING
                """, user_id, added_by)
        else:
            if "whitelist" not in self._memory_cache:
                self._memory_cache["whitelist"] = []
            if user_id not in self._memory_cache["whitelist"]:
                self._memory_cache["whitelist"].append(user_id)
                self._save_json()
    
    async def remove_from_whitelist(self, user_id: str):
        if self.pool:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM whitelist WHERE user_id = $1", user_id)
        else:
            if "whitelist" in self._memory_cache and user_id in self._memory_cache["whitelist"]:
                self._memory_cache["whitelist"].remove(user_id)
                self._save_json()
    
    async def get_recent_scans(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Get recent scan history for a user"""
        if self.pool:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM scan_history 
                    WHERE discord_user_id = $1 
                    ORDER BY scanned_at DESC 
                    LIMIT $2
                """, user_id, limit)
                return [dict(row) for row in rows]
        else:
            history = self._memory_cache.get("scan_history", [])
            user_history = [h for h in history if h.get("discord_user_id") == user_id]
            return sorted(user_history, key=lambda x: x.get("scanned_at", ""), reverse=True)[:limit]

# ═══════════════════════════════════════════════════════════
# REDIS CACHE MANAGER
# ═══════════════════════════════════════════════════════════
class CacheManager:
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self._local_cache: Dict[str, Tuple[Any, float]] = {}
        
    async def setup(self):
        if REDIS_AVAILABLE and Config.REDIS_URL:
            try:
                self.redis = redis.from_url(Config.REDIS_URL, decode_responses=True)
                await self.redis.ping()
                logger.info("✅ Redis connected")
            except Exception as e:
                logger.error(f"❌ Redis connection failed: {e}")
                logger.info("🔄 Using in-memory cache")
        else:
            logger.info("📁 Using in-memory cache")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get from cache (Redis or memory)"""
        if self.redis:
            try:
                data = await self.redis.get(key)
                if data:
                    return json.loads(data)
            except:
                pass
        
        # Fallback to memory
        if key in self._local_cache:
            value, expiry = self._local_cache[key]
            if time.time() < expiry:
                return value
            del self._local_cache[key]
        return None
    
    async def set(self, key: str, value: Any, ttl: int = None):
        """Set cache with TTL"""
        ttl = ttl or Config.CACHE_TTL
        if self.redis:
            try:
                await self.redis.setex(key, ttl, json.dumps(value, default=str))
                return
            except:
                pass
        
        # Fallback to memory
        self._local_cache[key] = (value, time.time() + ttl)
    
    async def delete(self, key: str):
        if self.redis:
            try:
                await self.redis.delete(key)
            except:
                pass
        if key in self._local_cache:
            del self._local_cache[key]

# ═══════════════════════════════════════════════════════════
# ADVANCED OCR ENGINE
# ═══════════════════════════════════════════════════════════
class OCRProcessor:
    """Multi-engine OCR with preprocessing pipeline"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.easyocr_reader = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        if EASYOCR_AVAILABLE:
            try:
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                logger.info("✅ EasyOCR initialized")
            except Exception as e:
                logger.error(f"⚠️ EasyOCR init failed: {e}")
    
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "TrueOmegaBot/2.0"}
        )
    
    def preprocess_image(self, image_data: bytes, method: str = "default") -> bytes:
        """Advanced image preprocessing"""
        if not PIL_AVAILABLE:
            return image_data
        
        try:
            img = Image.open(io.BytesIO(image_data))
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize for better OCR (but not too large)
            w, h = img.size
            if w < 400 or h < 200:
                scale = 3
            elif w < 800 or h < 400:
                scale = 2
            else:
                scale = 1
            
            if scale > 1:
                img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
            
            # Apply preprocessing based on method
            if method == "contrast":
                img = ImageEnhance.Contrast(img).enhance(2.5)
                img = ImageEnhance.Sharpness(img).enhance(2.0)
            elif method == "bw":
                img = ImageOps.grayscale(img)
                img = img.point(lambda x: 0 if x < 128 else 255, '1').convert('RGB')
            elif method == "sharp":
                img = img.filter(ImageFilter.SHARPEN)
                img = ImageEnhance.Contrast(img).enhance(2.0)
            elif method == "invert":
                img = ImageOps.invert(img)
                img = ImageEnhance.Contrast(img).enhance(2.0)
            elif method == "denoise":
                img = img.filter(ImageFilter.MedianFilter(size=3))
                img = ImageEnhance.Contrast(img).enhance(1.5)
            elif method == "default":
                # Smart default: enhance contrast and sharpness
                img = ImageEnhance.Contrast(img).enhance(1.8)
                img = ImageEnhance.Sharpness(img).enhance(1.5)
            
            # Save to bytes
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            return buf.getvalue()
            
        except Exception as e:
            logger.error(f"Preprocessing error: {e}")
            return image_data
    
    async def ocr_tesseract(self, image_data: bytes) -> Tuple[str, float]:
        """Tesseract OCR (local, fast)"""
        if not TESSERACT_AVAILABLE:
            return "", 0.0
        
        try:
            def run_tesseract():
                img = Image.open(io.BytesIO(image_data))
                text = pytesseract.image_to_string(img, config='--psm 6')
                # Get confidence
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                confidences = [int(c) for c in data['conf'] if int(c) > 0]
                avg_conf = sum(confidences) / len(confidences) if confidences else 50
                return text, avg_conf / 100
            
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, run_tesseract),
                timeout=Config.OCR_TIMEOUT
            )
        except Exception as e:
            logger.error(f"Tesseract error: {e}")
            return "", 0.0
    
    async def ocr_easyocr(self, image_data: bytes) -> Tuple[str, float]:
        """EasyOCR (good for stylized text)"""
        if not self.easyocr_reader or not CV2_AVAILABLE:
            return "", 0.0
        
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            def run_easyocr():
                results = self.easyocr_reader.readtext(img)
                texts = []
                confidences = []
                for (bbox, text, conf) in results:
                    texts.append(text)
                    confidences.append(conf)
                avg_conf = sum(confidences) / len(confidences) if confidences else 0
                return '\n'.join(texts), avg_conf
            
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, run_easyocr),
                timeout=Config.OCR_TIMEOUT
            )
        except Exception as e:
            logger.error(f"EasyOCR error: {e}")
            return "", 0.0
    
    async def ocr_ocrspace(self, image_data: bytes) -> Tuple[str, float]:
        """OCR.space API (cloud-based)"""
        if not Config.OCR_SPACE_KEY:
            return "", 0.0
        
        try:
            b64 = base64.b64encode(image_data).decode()
            data = {
                'apikey': Config.OCR_SPACE_KEY,
                'base64Image': f'data:image/png;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true',
                'detectOrientation': 'true',
            }
            
            async with self.session.post(
                'https://api.ocr.space/parse/image',
                data=data,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                
                if result.get('OCRExitCode') != 1:
                    return "", 0.0
                
                parsed = result.get('ParsedResults', [{}])[0]
                text = parsed.get('ParsedText', '')
                # OCR.space doesn't give per-word confidence, estimate from exit code
                confidence = 0.85 if result.get('OCRExitCode') == 1 else 0.5
                return text, confidence
                
        except Exception as e:
            logger.error(f"OCR.space error: {e}")
            return "", 0.0
    
    async def scan(self, image_data: bytes, hint: Optional[str] = None) -> Tuple[str, List[str], float]:
        """
        Run multiple OCR engines in parallel and merge results
        Returns: (merged_text, engines_used, avg_confidence)
        """
        start_time = time.time()
        
        # Preprocess image with multiple methods
        preprocessed = await asyncio.gather(*[
            asyncio.get_event_loop().run_in_executor(
                self.executor, self.preprocess_image, image_data, method
            )
            for method in ["default", "contrast", "sharp"]
        ])
        
        # Run OCR engines in parallel on different preprocessed versions
        tasks = []
        
        # Tesseract on default
        if TESSERACT_AVAILABLE:
            tasks.append(self.ocr_tesseract(preprocessed[0]))
        
        # EasyOCR on contrast-enhanced
        if EASYOCR_AVAILABLE:
            tasks.append(self.ocr_easyocr(preprocessed[1]))
        
        # OCR.space on sharp
        if Config.OCR_SPACE_KEY:
            tasks.append(self.ocr_ocrspace(preprocessed[2]))
        
        # Also try raw image with Tesseract as fallback
        if TESSERACT_AVAILABLE:
            tasks.append(self.ocr_tesseract(image_data))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Merge results
        all_texts = []
        engines_used = []
        confidences = []
        
        engine_names = ['tesseract', 'easyocr', 'ocrspace', 'tesseract_raw']
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue
            text, conf = result
            if text and len(text.strip()) > 3:
                all_texts.append(text)
                engines_used.append(engine_names[i] if i < len(engine_names) else f"engine_{i}")
                confidences.append(conf)
        
        # Merge texts intelligently
        merged_text = self._merge_texts(all_texts)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        logger.info(f"OCR completed in {time.time() - start_time:.2f}s using {len(engines_used)} engines")
        
        return merged_text, engines_used, avg_confidence
    
    def _merge_texts(self, texts: List[str]) -> str:
        """Intelligently merge texts from multiple engines, removing duplicates"""
        seen_lines = set()
        merged = []
        
        for text in texts:
            for line in text.split('\n'):
                clean = line.strip()
                if len(clean) < 2:
                    continue
                # Normalize for comparison
                normalized = re.sub(r'[^\w@]', '', clean).lower()
                if normalized and normalized not in seen_lines:
                    seen_lines.add(normalized)
                    merged.append(clean)
        
        return '\n'.join(merged)

# ═══════════════════════════════════════════════════════════
# ROBLOX API MANAGER
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    """Roblox API wrapper with caching and rate limiting"""
    
    def __init__(self, cache: CacheManager):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = cache
        self.rate_limit_remaining = 100
        self.rate_limit_reset = time.time()
        self._circuit_open = False
        self._circuit_failures = 0
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
        )
    
    async def _check_circuit_breaker(self):
        """Simple circuit breaker pattern"""
        if self._circuit_open:
            if time.time() - self._circuit_failures > 60:  # Reset after 60s
                self._circuit_open = False
                self._circuit_failures = 0
            else:
                raise Exception("Circuit breaker open - too many failures")
    
    async def _make_request(self, method: str, url: str, **kwargs) -> Dict:
        """Make request with rate limit handling"""
        await self._check_circuit_breaker()
        
        try:
            async with self.session.request(method, url, **kwargs) as resp:
                # Update rate limit tracking
                self.rate_limit_remaining = int(resp.headers.get('X-RateLimit-Remaining', 100))
                
                if resp.status == 429:
                    retry_after = int(resp.headers.get('Retry-After', 10))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    raise Exception("Rate limited")
                
                if resp.status == 200:
                    self._circuit_failures = max(0, self._circuit_failures - 1)
                    return await resp.json()
                elif resp.status == 404:
                    return None
                else:
                    raise Exception(f"HTTP {resp.status}")
                    
        except Exception as e:
            self._circuit_failures += 1
            if self._circuit_failures > 5:
                self._circuit_open = True
            raise
    
    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by exact username"""
        cache_key = f"roblox:user:{username.lower()}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        try:
            result = await self._make_request(
                'POST',
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [username], "excludeBannedUsers": False}
            )
            
            if result and result.get('data'):
                user_info = result['data'][0]
                # Get full profile
                profile = await self.get_user_by_id(user_info['id'])
                if profile:
                    await self.cache.set(cache_key, profile, ttl=600)
                    return profile
            return None
            
        except Exception as e:
            logger.error(f"Error fetching user {username}: {e}")
            return None
    
    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        cache_key = f"roblox:id:{user_id}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        
        try:
            profile = await self._make_request(
                'GET',
                f'https://users.roblox.com/v1/users/{user_id}'
            )
            if profile:
                # Get additional info
                try:
                    # Get avatar thumbnail
                    thumb_resp = await self._make_request(
                        'GET',
                        f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png'
                    )
                    if thumb_resp and thumb_resp.get('data'):
                        profile['thumbnailUrl'] = thumb_resp['data'][0].get('imageUrl')
                except:
                    pass
                
                await self.cache.set(cache_key, profile, ttl=600)
                return profile
            return None
            
        except Exception as e:
            logger.error(f"Error fetching user ID {user_id}: {e}")
            return None
    
    async def search_users(self, keyword: str, limit: int = 5) -> List[Dict]:
        """Search users by keyword"""
        try:
            result = await self._make_request(
                'GET',
                f'https://users.roblox.com/v1/users/search?keyword={quote(keyword)}&limit={limit}'
            )
            return result.get('data', []) if result else []
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []
    
    async def get_user_groups(self, user_id: int) -> List[Dict]:
        """Get user's groups"""
        try:
            result = await self._make_request(
                'GET',
                f'https://groups.roblox.com/v1/users/{user_id}/groups/roles'
            )
            return result.get('data', []) if result else []
        except:
            return []

# ═══════════════════════════════════════════════════════════
# USERNAME EXTRACTOR
# ═══════════════════════════════════════════════════════════
class UsernameExtractor:
    """Extract Roblox usernames from OCR text"""
    
    # Common false positives to exclude
    EXCLUDE_WORDS = {
        'roblox', 'profile', 'home', 'games', 'friends', 'inventory', 
        'avatar', 'shop', 'create', 'about', 'chat', 'trade', 'premium',
        'settings', 'search', 'menu', 'play', 'join', 'exit', 'back',
        'online', 'offline', 'studio', 'catalog', 'develop', 'groups',
        'messages', 'notifications', 'the', 'and', 'for', 'you', 'are',
        'connection', 'match', 'confidence', 'verification', 'status',
        'created', 'user', 'id', 'about', 'other', 'matches', 'banned',
        'active', 'today', 'font', 'proof', 'scanning', 'omega', 'true',
        'display', 'username', 'scan', 'click', 'add', 'remove', 'cancel',
        'confirm', 'save', 'edit', 'delete', 'report', 'block', 'follow',
        'following', 'followers', 'friends', 'friend', 'unfriend',
        'accept', 'decline', 'pending', 'request', 'sent', 'received',
        'all', 'new', 'old', 'recent', 'popular', 'trending', 'recommended',
        'sponsored', 'advertisement', 'ad', 'promoted', 'featured'
    }
    
    # Roblox username pattern: 3-20 chars, letters, numbers, underscores
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,20}$')
    
    # @username patterns with Unicode variants
    AT_PATTERNS = [
        re.compile(r'[@＠﹫]([a-zA-Z0-9_]{3,20})\b'),  # Standard @
        re.compile(r'\bat\s+([a-zA-Z0-9_]{3,20})\b', re.I),  # "at username"
    ]
    
    # URL patterns
    URL_PATTERNS = [
        re.compile(r'roblox\.com/users/(\d+)', re.I),
        re.compile(r'roblox\.com/user\.aspx\?id=(\d+)', re.I),
    ]
    
    def extract(self, text: str, hint: Optional[str] = None) -> List[Dict]:
        """
        Extract potential usernames from text
        Returns list of dicts with username, display_name, confidence, source
        """
        candidates = []
        lines = text.split('\n')
        text_lower = text.lower()
        
        # 1. Find @username patterns
        for i, line in enumerate(lines):
            for pattern in self.AT_PATTERNS:
                for match in pattern.finditer(line):
                    username = match.group(1)
                    if self._is_valid_username(username):
                        # Look for display name (text before @)
                        display_name = None
                        confidence = 0.85
                        
                        before = line[:match.start()].strip()
                        before_clean = re.sub(r'[^\w\s]', '', before).strip()
                        if before_clean and len(before_clean) < 25:
                            display_name = before_clean
                            confidence = 0.95
                        
                        # Also check previous line
                        if not display_name and i > 0:
                            prev = re.sub(r'[^\w\s]', '', lines[i-1]).strip()
                            if prev and len(prev) < 25:
                                display_name = prev
                                confidence = 0.9
                        
                        candidates.append({
                            'username': username,
                            'display_name': display_name,
                            'confidence': confidence,
                            'source': '@mention',
                            'line': i
                        })
        
        # 2. Find user IDs in URLs
        for pattern in self.URL_PATTERNS:
            for match in pattern.finditer(text):
                user_id = match.group(1)
                candidates.insert(0, {
                    'username': f'ID:{user_id}',
                    'user_id': int(user_id),
                    'confidence': 0.98,
                    'source': 'url'
                })
        
        # 3. Find "Display @ Username" pairs
        for line in lines:
            # Pattern: "DisplayName @Username" or "DisplayName @ Username"
            match = re.search(r'^([A-Z][a-zA-Z\s]{1,20})\s*[@\s]\s*([a-z][a-z0-9_]{2,19})\b', line)
            if match:
                display, username = match.groups()
                if self._is_valid_username(username):
                    # Update existing or add new
                    existing = next((c for c in candidates if c['username'].lower() == username.lower()), None)
                    if existing:
                        existing['display_name'] = display
                        existing['confidence'] = 0.98
                        existing['source'] = 'display_pair'
                    else:
                        candidates.append({
                            'username': username,
                            'display_name': display,
                            'confidence': 0.98,
                            'source': 'display_pair'
                        })
        
        # 4. Find standalone usernames that look like Roblox names
        words = set(re.findall(r'\b([a-z][a-z0-9_]{2,19})\b', text_lower))
        for word in words:
            if self._is_valid_username(word) and not any(c['username'].lower() == word for c in candidates):
                # Check if near an @ symbol
                near_at = any(f'@{word}' in text_lower or f'@ {word}' in text_lower for _ in [1])
                confidence = 0.65 if near_at else 0.45
                candidates.append({
                    'username': word,
                    'display_name': None,
                    'confidence': confidence,
                    'source': 'pattern'
                })
        
        # 5. Hint boost
        if hint:
            hint_clean = hint.strip().lower().replace('@', '')
            if self._is_valid_username(hint_clean):
                existing = next((c for c in candidates if c['username'].lower() == hint_clean), None)
                if existing:
                    existing['confidence'] = 1.0
                    existing['source'] = 'hint'
                else:
                    candidates.insert(0, {
                        'username': hint_clean,
                        'display_name': None,
                        'confidence': 1.0,
                        'source': 'hint'
                    })
        
        # Remove duplicates and sort by confidence
        seen = set()
        unique = []
        for c in sorted(candidates, key=lambda x: x['confidence'], reverse=True):
            key = c['username'].lower()
            if key not in seen:
                seen.add(key)
                unique.append(c)
        
        return unique
    
    def _is_valid_username(self, username: str) -> bool:
        """Check if string is a valid Roblox username"""
        if not username:
            return False
        if username.lower() in self.EXCLUDE_WORDS:
            return False
        if not self.USERNAME_PATTERN.match(username):
            return False
        return True
    
    def find_similar_usernames(self, username: str, candidates: List[str]) -> List[str]:
        """Find similar usernames using fuzzy matching"""
        try:
            import difflib
            matches = difflib.get_close_matches(username.lower(), 
                                                 [c.lower() for c in candidates], 
                                                 n=3, cutoff=0.7)
            return matches
        except:
            return []

# ═══════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════
class RateLimiter:
    """Rate limiter per user"""
    
    def __init__(self):
        self._requests: Dict[str, List[float]] = {}
        self.limit = Config.RATE_LIMIT_PER_MINUTE
        self.window = 60  # 1 minute
    
    def is_allowed(self, user_id: str) -> Tuple[bool, int]:
        """Check if user is allowed to make request. Returns (allowed, retry_after)"""
        now = time.time()
        
        if user_id not in self._requests:
            self._requests[user_id] = []
        
        # Remove old requests outside window
        self._requests[user_id] = [t for t in self._requests[user_id] if now - t < self.window]
        
        if len(self._requests[user_id]) >= self.limit:
            retry_after = int(self.window - (now - self._requests[user_id][0]))
            return False, retry_after
        
        self._requests[user_id].append(now)
        return True, 0
    
    def get_remaining(self, user_id: str) -> int:
        """Get remaining requests for user"""
        if user_id not in self._requests:
            return self.limit
        now = time.time()
        valid = [t for t in self._requests[user_id] if now - t < self.window]
        return max(0, self.limit - len(valid))

# ═══════════════════════════════════════════════════════════
# WEBHOOK LOGGER
# ═══════════════════════════════════════════════════════════
class WebhookLogger:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.queue: List[Dict] = []
        self._flush_task: Optional[asyncio.Task] = None
    
    async def setup(self):
        if Config.WEBHOOK_URL:
            self.session = aiohttp.ClientSession()
            self._flush_task = asyncio.create_task(self._flush_loop())
            logger.info("✅ Webhook logger initialized")
    
    async def _flush_loop(self):
        while True:
            await asyncio.sleep(5)
            if self.queue:
                await self._send_batch()
    
    async def _send_batch(self):
        if not self.queue or not self.session:
            return
        
        batch = self.queue[:10]
        self.queue = self.queue[10:]
        
        for item in batch:
            try:
                async with self.session.post(Config.WEBHOOK_URL, json=item) as resp:
                    if resp.status not in [200, 204]:
                        logger.warning(f"Webhook failed: {resp.status}")
            except Exception as e:
                logger.error(f"Webhook error: {e}")
    
    async def log_scan(self, user: discord.User, profile: Dict, confidence: float, 
                       guild_name: str, scan_time: float):
        if not Config.WEBHOOK_URL:
            return
        
        embed = {
            "title": f"🔍 Scan: @{profile['name']}",
            "description": f"**User:** {user.name} (`{user.id}`)\n**Location:** {guild_name}\n**Confidence:** `{confidence:.0%}`\n**Time:** `{scan_time:.1f}s`",
            "color": 0x00D4AA if confidence > 0.8 else 0xFFA500,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": "🆔 Roblox ID", "value": f"`{profile['id']}`", "inline": True},
                {"name": "📛 Display", "value": profile.get('displayName', 'N/A'), "inline": True}
            ]
        }
        
        self.queue.append({
            "username": "TRUE OMEGA",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
            "embeds": [embed]
        })
        
        if len(self.queue) >= 5:
            await self._send_batch()
    
    async def log_error(self, error: str, context: Dict = None):
        if not Config.WEBHOOK_URL:
            return
        
        self.queue.append({
            "username": "TRUE OMEGA - Errors",
            "content": f"❌ **Error:** {error}\n```json\n{json.dumps(context or {}, default=str, indent=2)[:1500]}\n```"
        })

# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    def __init__(self):
        self.path = tempfile.mkdtemp()
    
    async def download(self, url: str, user_id: str) -> Dict:
        if not YTDLP_AVAILABLE:
            return {"success": False, "error": "yt-dlp not installed"}
        
        dl_id = f"{user_id}_{int(time.time())}"
        output = os.path.join(self.path, f"{dl_id}.%(ext)s")
        
        try:
            loop = asyncio.get_event_loop()
            
            def dl():
                opts = {
                    'format': 'best[filesize<25M]/bestvideo[filesize<25M]+bestaudio/best',
                    'outtmpl': output,
                    'quiet': True,
                    'max_filesize': 25 * 1024 * 1024,
                    'merge_output_format': 'mp4',
                    'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    files = [f for f in os.listdir(self.path) if f.startswith(dl_id)]
                    if not files:
                        return {"success": False, "error": "No file downloaded"}
                    fpath = os.path.join(self.path, files[0])
                    return {
                        "success": True,
                        "file_path": fpath,
                        "title": info.get('title', 'video'),
                        "size": os.path.getsize(fpath),
                        "duration": info.get('duration'),
                        "uploader": info.get('uploader')
                    }
            
            return await asyncio.wait_for(loop.run_in_executor(None, dl), timeout=120)
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {"success": False, "error": str(e)[:200]}
    
    def cleanup(self, path: str):
        try:
            if os.path.exists(path):
                os.remove(path)
        except:
            pass

# ═══════════════════════════════════════════════════════════
# DISCORD UI COMPONENTS
# ═══════════════════════════════════════════════════════════
class ProfileView(View):
    """Interactive view for profile results"""
    
    def __init__(self, profile: Dict, bot: 'TrueOmegaBot', user_id: str):
        super().__init__(timeout=180)
        self.profile = profile
        self.bot = bot
        self.user_id = user_id
    
    @discord.ui.button(label="View Profile", style=discord.ButtonStyle.link, emoji="🔗")
    async def view_profile(self, interaction: discord.Interaction, button: Button):
        # This is a link button, handled automatically
        pass
    
    @discord.ui.button(label="Search Groups", style=discord.ButtonStyle.secondary, emoji="👥")
    async def search_groups(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        
        groups = await self.bot.roblox_api.get_user_groups(self.profile['id'])
        
        if not groups:
            await interaction.followup.send("No groups found or user has private groups.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"👥 {self.profile.get('displayName', self.profile['name'])}'s Groups",
            color=0x00D4AA
        )
        
        for group in groups[:10]:
            g = group.get('group', {})
            role = group.get('role', {}).get('name', 'Member')
            embed.add_field(
                name=g.get('name', 'Unknown'),
                value=f"Role: {role}\n[View Group](https://roblox.com/groups/{g.get('id')})",
                inline=True
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Save to Favorites", style=discord.ButtonStyle.success, emoji="⭐")
    async def save_favorite(self, interaction: discord.Interaction, button: Button):
        stats = await self.bot.db.get_user_stats(self.user_id)
        
        if self.profile['name'] in stats.favorite_users:
            await interaction.response.send_message("Already in favorites!", ephemeral=True)
            return
        
        stats.favorite_users.insert(0, self.profile['name'])
        stats.favorite_users = stats.favorite_users[:10]
        await self.bot.db.update_user_stats(stats)
        
        await interaction.response.send_message(f"Added @{self.profile['name']} to favorites!", ephemeral=True)

class AlternativeSelect(Select):
    """Dropdown for alternative matches"""
    
    def __init__(self, alternatives: List[Dict], bot: 'TrueOmegaBot'):
        self.bot = bot
        options = []
        
        for alt in alternatives[:5]:
            p = alt['profile']
            label = f"@{p['name']}"
            description = f"Confidence: {alt['score']:.0%}"
            if p.get('displayName'):
                label = f"{p['displayName']} (@{p['name']})"
            options.append(discord.SelectOption(
                label=label[:100],
                description=description[:100],
                value=p['name']
            ))
        
        super().__init__(
            placeholder="Select an alternative match...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        username = self.values[0]
        profile = await self.bot.roblox_api.get_user_by_username(username)
        
        if profile:
            embed = self.bot._create_profile_embed(profile, 0.85, ["Manual selection"])
            view = ProfileView(profile, self.bot, str(interaction.user.id))
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.followup.send("Failed to load profile.", ephemeral=True)

# ═══════════════════════════════════════════════════════════
# MAIN BOT CLASS
# ═══════════════════════════════════════════════════════════
class TrueOmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Roblox | /scan"
            )
        )
        self.tree = app_commands.CommandTree(self)
        
        # Components
        self.db = DatabaseManager()
        self.cache = CacheManager()
        self.ocr = OCRProcessor()
        self.roblox_api = RobloxAPI(self.cache)
        self.extractor = UsernameExtractor()
        self.rate_limiter = RateLimiter()
        self.webhook = WebhookLogger()
        self.downloader = VideoDownloader()
        
        # State
        self.whitelist: Set[str] = set()
        self.start_time = time.time()
        self._shutting_down = False
        
    async def setup_hook(self):
        """Setup bot components"""
        logger.info("🔧 Setting up bot components...")
        
        # Initialize all components
        await self.db.setup()
        await self.cache.setup()
        await self.ocr.setup()
        await self.roblox_api.setup()
        await self.webhook.setup()
        
        # Load whitelist
        self.whitelist = await self.db.get_whitelist()
        self.whitelist.add(str(Config.OWNER_ID))
        logger.info(f"✅ Loaded {len(self.whitelist)} whitelisted users")
        
        # Register commands
        self._register_commands()
        
        # Sync commands
        await self._sync_commands()
        
        logger.info("✅ Bot setup complete!")
    
    def _register_commands(self):
        """Register all slash commands"""
        
        @self.tree.command(name="scan", description="🔍 Scan Roblox username from image")
        @app_commands.default_permissions()
        @app_commands.describe(
            image="Screenshot to scan",
            hint="Optional username hint (improves accuracy)"
        )
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="search", description="🔎 Search Roblox user by username")
        @app_commands.default_permissions()
        @app_commands.describe(username="Roblox username to search")
        async def search_cmd(interaction: discord.Interaction, username: str):
            await self.cmd_search(interaction, username)
        
        @self.tree.command(name="download", description="📥 Download video to MP4")
        @app_commands.default_permissions()
        @app_commands.describe(url="Video URL (YouTube, TikTok, etc.)")
        async def download_cmd(interaction: discord.Interaction, url: str):
            await self.cmd_download(interaction, url)
        
        @self.tree.command(name="stats", description="📊 View your scan statistics")
        @app_commands.default_permissions()
        async def stats_cmd(interaction: discord.Interaction):
            await self.cmd_stats(interaction)
        
        @self.tree.command(name="history", description="📜 View your recent scans")
        @app_commands.default_permissions()
        async def history_cmd(interaction: discord.Interaction):
            await self.cmd_history(interaction)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (Owner only)")
        @app_commands.default_permissions()
        @app_commands.describe(user="User to add/remove (ID or mention)")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self.cmd_whitelist(interaction, user)
        
        @self.tree.command(name="help", description="❓ Show bot help and commands")
        @app_commands.default_permissions()
        async def help_cmd(interaction: discord.Interaction):
            await self.cmd_help(interaction)
        
        @self.tree.command(name="ping", description="🏓 Check bot latency")
        @app_commands.default_permissions()
        async def ping_cmd(interaction: discord.Interaction):
            await self.cmd_ping(interaction)
    
    async def _sync_commands(self):
        """Sync commands to Discord"""
        logger.info("🔄 Syncing commands...")
        
        for attempt in range(5):
            try:
                # DON'T clear commands - this causes them to disappear
                # self.tree.clear_commands(guild=None)
                
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} commands")
                
                for cmd in synced:
                    logger.info(f"  - /{cmd.name}")
                break
                
            except discord.HTTPException as e:
                if e.status == 429:
                    retry = getattr(e, 'retry_after', 5)
                    logger.warning(f"Rate limited, retrying in {retry}s...")
                    await asyncio.sleep(retry)
                else:
                    logger.error(f"Command sync failed: {e}")
                    await asyncio.sleep(2)
    
    # ═══════════════════════════════════════════════════════
    # COMMAND HANDLERS
    # ═══════════════════════════════════════════════════════
    
    async def cmd_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: Optional[str]):
        """Main scan command"""
        user_id = str(interaction.user.id)
        
        # Check whitelist
        if user_id not in self.whitelist:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⛔ Access Denied",
                    description="You're not whitelisted. Contact the bot owner.",
                    color=0xFF0000
                ),
                ephemeral=True
            )
            return
        
        # Check rate limit
        allowed, retry_after = self.rate_limiter.is_allowed(user_id)
        if not allowed:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏰ Rate Limited",
                    description=f"Please wait {retry_after}s before scanning again.",
                    color=0xFFA500
                ),
                ephemeral=True
            )
            return
        
        # Check file size
        if image.size and image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ File Too Large",
                    description=f"Max size: {Config.MAX_FILE_SIZE / 1024 / 1024:.0f}MB",
                    color=0xFF0000
                ),
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        # Progress message
        progress_embed = discord.Embed(
            title="🔍 Scanning Image...",
            description="```\n[░░░░░░░░░░] 0%\n```\n📥 Downloading image...",
            color=0xFFA500
        )
        progress_embed.set_footer(text=f"Rate limit: {self.rate_limiter.get_remaining(user_id)} left")
        await interaction.followup.send(embed=progress_embed)
        
        try:
            start_time = time.time()
            
            # Download image
            async with self.ocr.session.get(image.url, timeout=15) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to download image: {resp.status}")
                img_data = await resp.read()
            
            # Update progress
            progress_embed.description = "```\n[██░░░░░░░░] 20%\n```\n🔤 Running OCR analysis..."
            await interaction.edit_original_response(embed=progress_embed)
            
            # Run OCR
            ocr_text, engines_used, ocr_confidence = await self.ocr.scan(img_data, hint)
            
            if not ocr_text:
                raise Exception("No text detected in image")
            
            # Update progress
            progress_embed.description = "```\n[████░░░░░░] 40%\n```\n🔍 Extracting usernames..."
            await interaction.edit_original_response(embed=progress_embed)
            
            # Extract usernames
            candidates = self.extractor.extract(ocr_text, hint)
            
            if not candidates:
                # No candidates found - show helpful error
                fail_embed = discord.Embed(
                    title="❌ No Username Found",
                    description="Couldn't detect a valid Roblox username in this image.",
                    color=0xFF0000
                )
                fail_embed.add_field(
                    name="💡 Tips",
                    value="• Make sure the @username is clearly visible\n"
                          "• Try a higher resolution screenshot\n"
                          "• Use the `hint` option with the username",
                    inline=False
                )
                fail_embed.add_field(
                    name="📝 Detected Text (preview)",
                    value=f"```{ocr_text[:500]}...```" if len(ocr_text) > 500 else f"```{ocr_text}```",
                    inline=False
                )
                fail_embed.set_footer(text=f"OCR engines: {', '.join(engines_used)} | Time: {time.time()-start_time:.1f}s")
                await interaction.edit_original_response(embed=fail_embed)
                
                # Update stats
                stats = await self.db.get_user_stats(user_id)
                stats.total_scans += 1
                stats.failed_scans += 1
                stats.last_scan = datetime.utcnow()
                await self.db.update_user_stats(stats)
                return
            
            # Update progress
            progress_embed.description = "```\n[██████░░░░] 60%\n```\n✅ Verifying with Roblox API..."
            await interaction.edit_original_response(embed=progress_embed)
            
            # Verify candidates with Roblox API
            verified_profiles = []
            for candidate in candidates[:5]:  # Check top 5
                if candidate['username'].startswith('ID:'):
                    # Direct ID lookup
                    user_id_num = int(candidate['username'].replace('ID:', ''))
                    profile = await self.roblox_api.get_user_by_id(user_id_num)
                else:
                    profile = await self.roblox_api.get_user_by_username(candidate['username'])
                
                if profile:
                    # Calculate final confidence score
                    score = candidate['confidence']
                    reasons = [f"{candidate['source']} ({candidate['confidence']:.0%})"]
                    
                    # Boost if display name matches
                    if candidate.get('display_name') and profile.get('displayName'):
                        if candidate['display_name'].lower() in profile['displayName'].lower():
                            score = min(score + 0.1, 1.0)
                            reasons.append("display match")
                    
                    verified_profiles.append({
                        'profile': profile,
                        'score': score,
                        'reasons': reasons,
                        'cached': False
                    })
                    
                    # Early exit if very confident
                    if score >= 0.95:
                        break
            
            if not verified_profiles:
                # Try fuzzy search with first candidate
                if candidates:
                    similar = await self.roblox_api.search_users(candidates[0]['username'], limit=3)
                    if similar:
                        suggested = [s['name'] for s in similar]
                        
                        fail_embed = discord.Embed(
                            title="❌ User Not Found",
                            description=f"Username `@{candidates[0]['username']}` doesn't exist.",
                            color=0xFF0000
                        )
                        fail_embed.add_field(
                            name="🔍 Did you mean?",
                            value="\n".join(f"• @{s}" for s in suggested[:3]),
                            inline=False
                        )
                        await interaction.edit_original_response(embed=fail_embed)
                        
                        # Update stats
                        stats = await self.db.get_user_stats(user_id)
                        stats.total_scans += 1
                        stats.failed_scans += 1
                        await self.db.update_user_stats(stats)
                        return
            
            # Success! Show best match
            best = verified_profiles[0]
            profile = best['profile']
            score = best['score']
            
            # Update progress to complete
            progress_embed.description = "```\n[██████████] 100%\n```\n✅ Scan complete!"
            await interaction.edit_original_response(embed=progress_embed)
            
            # Create result embed
            embed = self._create_profile_embed(profile, score, best['reasons'])
            embed.set_image(url=image.url)
            
            # Create view with buttons
            view = ProfileView(profile, self, user_id)
            
            # Add alternatives if available
            if len(verified_profiles) > 1:
                alt_select = AlternativeSelect(verified_profiles[1:], self)
                view.add_item(alt_select)
            
            await interaction.edit_original_response(embed=embed, view=view)
            
            # Update stats
            stats = await self.db.get_user_stats(user_id)
            stats.total_scans += 1
            stats.successful_scans += 1
            if profile['name'] not in stats.favorite_users:
                stats.favorite_users.insert(0, profile['name'])
                stats.favorite_users = stats.favorite_users[:10]
            stats.last_scan = datetime.utcnow()
            await self.db.update_user_stats(stats)
            
            # Add to scan history
            await self.db.add_scan_history(user_id, profile['name'], profile['id'], score, True)
            
            # Log to webhook
            guild_name = interaction.guild.name if interaction.guild else "DM"
            await self.webhook.log_scan(interaction.user, profile, score, guild_name, time.time() - start_time)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            traceback.print_exc()
            
            error_embed = discord.Embed(
                title="❌ Scan Failed",
                description=f"An error occurred: `{str(e)[:200]}`\n\nPlease try again.",
                color=0xFF0000
            )
            await interaction.edit_original_response(embed=error_embed)
            
            # Update failed stats
            try:
                stats = await self.db.get_user_stats(user_id)
                stats.total_scans += 1
                stats.failed_scans += 1
                await self.db.update_user_stats(stats)
            except:
                pass
    
    def _create_profile_embed(self, profile: Dict, score: float, reasons: List[str]) -> discord.Embed:
        """Create a nice embed for a Roblox profile"""
        
        # Determine color based on confidence
        if profile.get('isBanned'):
            color, status = 0x8B0000, "🔴 BANNED"
        elif score >= 0.9:
            color, status = 0x00FF00, "✅ Verified"
        elif score >= 0.7:
            color, status = 0xFFA500, "⚠️ Likely"
        else:
            color, status = 0xFFFF00, "❓ Uncertain"
        
        embed = discord.Embed(
            title=f"{profile.get('displayName', profile['name'])}",
            url=f"https://roblox.com/users/{profile['id']}/profile",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.description = f"**@{profile['name']}**\n`Match Confidence: {score:.0%}`"
        
        # Add thumbnail if available
        if profile.get('thumbnailUrl'):
            embed.set_thumbnail(url=profile['thumbnailUrl'])
        
        # Verification details
        embed.add_field(
            name="✅ Verification",
            value="\n".join(f"• {r}" for r in reasons[:4]),
            inline=False
        )
        
        # Stats row
        created = str(profile.get('created', 'Unknown'))[:10]
        embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
        embed.add_field(name="📅 Created", value=created, inline=True)
        embed.add_field(name="⚡ Status", value=status, inline=True)
        
        # Description
        if profile.get('description'):
            desc = profile['description'][:200]
            if len(profile['description']) > 200:
                desc += "..."
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        return embed
    
    async def cmd_search(self, interaction: discord.Interaction, username: str):
        """Direct username search"""
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist:
            await interaction.response.send_message("⛔ Not whitelisted!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        embed = discord.Embed(
            title="🔎 Searching...",
            description=f"Looking for `@{username}`...",
            color=0xFFA500
        )
        await interaction.followup.send(embed=embed)
        
        try:
            # Try exact match first
            profile = await self.roblox_api.get_user_by_username(username.strip())
            
            if profile:
                result_embed = self._create_profile_embed(
                    profile, 
                    1.0, 
                    ["Direct search"]
                )
                view = ProfileView(profile, self, user_id)
                await interaction.edit_original_response(embed=result_embed, view=view)
                return
            
            # Try search
            results = await self.roblox_api.search_users(username.strip(), limit=5)
            
            if results:
                search_embed = discord.Embed(
                    title=f"🔎 Search Results for '{username}'",
                    description="Found these users:",
                    color=0x00D4AA
                )
                
                for r in results[:5]:
                    name = f"{r.get('displayName', r['name'])} (@{r['name']})"
                    search_embed.add_field(
                        name=name,
                        value=f"[View Profile](https://roblox.com/users/{r['id']}/profile)",
                        inline=False
                    )
                
                await interaction.edit_original_response(embed=search_embed)
            else:
                await interaction.edit_original_response(embed=discord.Embed(
                    title="❌ Not Found",
                    description=f"No user found matching `@{username}`",
                    color=0xFF0000
                ))
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Error",
                description=str(e)[:200],
                color=0xFF0000
            ))
    
    async def cmd_download(self, interaction: discord.Interaction, url: str):
        """Video download command"""
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist:
            await interaction.response.send_message("⛔ Not whitelisted!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Invalid URL", color=0xFF0000),
                ephemeral=True
            )
            return
        
        progress = discord.Embed(
            title="📥 Downloading...",
            description="Fetching video info...",
            color=0xFFA500
        )
        await interaction.followup.send(embed=progress)
        
        result = await self.downloader.download(url, user_id)
        
        if not result['success']:
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Download Failed",
                description=f"```{result['error'][:500]}```",
                color=0xFF0000
            ))
            return
        
        # Check file size (Discord limit is 25MB for non-nitro)
        size_mb = result['size'] / (1024 * 1024)
        if result['size'] > 25 * 1024 * 1024:
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ File Too Large",
                description=f"{size_mb:.1f}MB exceeds Discord's 25MB limit\n"
                           f"Try a shorter video or lower quality.",
                color=0xFF0000
            ))
            self.downloader.cleanup(result['file_path'])
            return
        
        # Send file
        safe_title = re.sub(r'[^\w\-_.]', '_', result['title'][:50])
        file = discord.File(result['file_path'], filename=f"{safe_title}.mp4")
        
        success_embed = discord.Embed(title="✅ Download Complete", color=0x00FF00)
        success_embed.add_field(name="📹 Title", value=result['title'][:100], inline=False)
        success_embed.add_field(name="📦 Size", value=f"{size_mb:.1f} MB", inline=True)
        if result.get('duration'):
            success_embed.add_field(name="⏱️ Duration", value=f"{result['duration']}s", inline=True)
        if result.get('uploader'):
            success_embed.add_field(name="👤 Uploader", value=result['uploader'][:50], inline=True)
        
        await interaction.edit_original_response(embed=success_embed, attachments=[file])
        self.downloader.cleanup(result['file_path'])
    
    async def cmd_stats(self, interaction: discord.Interaction):
        """User statistics command"""
        await interaction.response.defer(ephemeral=True)
        
        stats = await self.db.get_user_stats(str(interaction.user.id))
        
        embed = discord.Embed(
            title=f"📊 {interaction.user.name}'s Statistics",
            color=0x00D4AA,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="🔍 Total Scans", value=str(stats.total_scans), inline=True)
        embed.add_field(name="✅ Successful", value=str(stats.successful_scans), inline=True)
        embed.add_field(name="❌ Failed", value=str(stats.failed_scans), inline=True)
        embed.add_field(name="📈 Success Rate", value=f"{stats.success_rate:.1f}%", inline=True)
        
        if stats.last_scan:
            embed.add_field(
                name="🕐 Last Scan",
                value=stats.last_scan.strftime("%Y-%m-%d %H:%M UTC"),
                inline=True
            )
        
        if stats.favorite_users:
            embed.add_field(
                name="⭐ Recent Finds",
                value="\n".join(f"• @{u}" for u in stats.favorite_users[:5]),
                inline=False
            )
        
        embed.set_footer(text="TRUE OMEGA | Ultimate Roblox Scanner")
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def cmd_history(self, interaction: discord.Interaction):
        """View scan history"""
        await interaction.response.defer(ephemeral=True)
        
        history = await self.db.get_recent_scans(str(interaction.user.id), limit=10)
        
        if not history:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📜 Scan History",
                    description="No scans yet! Use `/scan` to find Roblox users.",
                    color=0xFFA500
                ),
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="📜 Your Recent Scans",
            color=0x00D4AA
        )
        
        for h in history:
            name = f"@{h.get('roblox_username', 'Unknown')}"
            conf = h.get('confidence', 0)
            status = "✅" if h.get('success') else "❌"
            time_str = h.get('scanned_at', 'Unknown')
            if isinstance(time_str, str):
                time_str = time_str[:16]
            embed.add_field(
                name=f"{status} {name}",
                value=f"Confidence: {conf:.0%} | {time_str}",
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def cmd_whitelist(self, interaction: discord.Interaction, user: str):
        """Whitelist management (owner only)"""
        if str(interaction.user.id) != str(Config.OWNER_ID):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Owner Only", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Parse user ID
        target = re.sub(r'[<@!>]', '', user).strip()
        if not target.isdigit():
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Invalid User ID", color=0xFF0000),
                ephemeral=True
            )
            return
        
        # Try to fetch user info
        try:
            user_obj = await self.fetch_user(int(target))
            name = f"@{user_obj.name}" if user_obj else target
        except:
            name = target
        
        if target in self.whitelist:
            if target == str(Config.OWNER_ID):
                await interaction.followup.send(
                    embed=discord.Embed(title="⛔ Cannot remove owner!", color=0xFF0000),
                    ephemeral=True
                )
                return
            
            await self.db.remove_from_whitelist(target)
            self.whitelist.remove(target)
            await self.webhook.log(f"❌ Removed **{name}** from whitelist")
            await interaction.followup.send(
                embed=discord.Embed(title=f"❌ Removed {name}", color=0xFF0000),
                ephemeral=True
            )
        else:
            await self.db.add_to_whitelist(target, str(interaction.user.id))
            self.whitelist.add(target)
            await self.webhook.log(f"✅ Added **{name}** to whitelist")
            await interaction.followup.send(
                embed=discord.Embed(title=f"✅ Added {name}", color=0x00FF00),
                ephemeral=True
            )
    
    async def cmd_help(self, interaction: discord.Interaction):
        """Help command"""
        embed = discord.Embed(
            title="🎯 TRUE OMEGA ULTIMATE - Help",
            description="The most advanced Roblox scanner bot with multi-engine OCR.",
            color=0x00D4AA
        )
        
        commands = [
            ("🔍 /scan", "Scan a screenshot to find Roblox users\n`image`: Screenshot to analyze\n`hint`: Optional username hint"),
            ("🔎 /search", "Search for a Roblox user by username\n`username`: Exact username to search"),
            ("📥 /download", "Download videos to MP4\n`url`: Video URL (YouTube, TikTok, etc.)"),
            ("📊 /stats", "View your personal scan statistics"),
            ("📜 /history", "View your recent scan history"),
            ("🏓 /ping", "Check bot latency and status"),
        ]
        
        for name, desc in commands:
            embed.add_field(name=name, value=desc, inline=False)
        
        embed.add_field(
            name="💡 Pro Tips",
            value="• Use the `hint` option when OCR struggles with stylized fonts\n"
                  "• Higher resolution screenshots give better results\n"
                  "• The bot uses Tesseract + EasyOCR + OCR.space for maximum accuracy",
            inline=False
        )
        
        embed.set_footer(text="TRUE OMEGA ULTIMATE | Railway-Optimized | v2.0")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        """Ping command"""
        latency = round(self.latency * 1000)
        uptime = timedelta(seconds=int(time.time() - self.start_time))
        
        embed = discord.Embed(title="🏓 Pong!", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
        embed.add_field(name="Uptime", value=str(uptime), inline=True)
        embed.add_field(name="Servers", value=str(len(self.guilds)), inline=True)
        
        # Check services
        services = []
        if self.db.pool:
            services.append("🟢 PostgreSQL")
        else:
            services.append("🟡 JSON Fallback")
        
        if self.cache.redis:
            services.append("🟢 Redis")
        else:
            services.append("🟡 Memory Cache")
        
        services.append("🟢 OCR Engines" if TESSERACT_AVAILABLE or EASYOCR_AVAILABLE else "🔴 No OCR")
        
        embed.add_field(name="Services", value="\n".join(services), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # ═══════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════════════════
    
    async def on_ready(self):
        """Called when bot is ready"""
        logger.info("=" * 50)
        logger.info(f"✅ BOT ONLINE: {self.user}")
        logger.info(f"   Servers: {len(self.guilds)}")
        logger.info(f"   Whitelisted: {len(self.whitelist)} users")
        logger.info("=" * 50)
    
    async def on_error(self, event_method: str, *args, **kwargs):
        """Global error handler"""
        logger.error(f"Error in {event_method}: {traceback.format_exc()}")
        await self.webhook.log_error(f"Error in {event_method}", {"args": str(args)})
    
    async def close(self):
        """Graceful shutdown"""
        logger.info("🛑 Shutting down gracefully...")
        self._shutting_down = True
        
        # Close sessions
        if self.ocr.session:
            await self.ocr.session.close()
        if self.roblox_api.session:
            await self.roblox_api.session.close()
        
        # Close DB pool
        if self.db.pool:
            await self.db.pool.close()
        
        # Close Redis
        if self.cache.redis:
            await self.cache.redis.close()
        
        await super().close()
        logger.info("✅ Shutdown complete")

# ═══════════════════════════════════════════════════════════
# HEALTH CHECK SERVER (for Railway)
# ═══════════════════════════════════════════════════════════
async def health_check_server():
    """Simple HTTP server for Railway health checks"""
    from aiohttp import web
    
    async def health(request):
        return web.Response(text='OK', status=200)
    
    app = web.Application()
    app.router.add_get('/health', health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    logger.info("✅ Health check server started on port 8080")

# ═══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════
async def main():
    """Main entry point"""
    # Start health check server in background
    health_task = asyncio.create_task(health_check_server())
    
    # Create and start bot
    bot = TrueOmegaBot()
    
    try:
        await bot.start(Config.TOKEN)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        await bot.close()
        health_task.cancel()

def run():
    """Run with auto-restart"""
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            logger.error(traceback.format_exc())
            logger.info("Restarting in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    run()
