"""
🚀 TRUE OMEGA v4.1 - FIXED & OPTIMIZED ROBLOX SCANNER
Fixed friends display, improved OCR speed, cleaner UI
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
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
import logging

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("true_omega_v4")

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # Performance - AGGRESSIVE TIMEOUTS FOR SPEED
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '52428800'))
    OVERALL_TIMEOUT = 15  # Reduced from 20
    DOWNLOAD_TIMEOUT = 5  # Reduced from 8
    OCR_TIMEOUT = 4       # Reduced from 6
    API_TIMEOUT = 4       # Reduced from 5
    FRIENDS_TIMEOUT = 8   # Reduced from 10
    
    # Concurrency
    MAX_CONCURRENT_SCANS = int(os.getenv('MAX_CONCURRENT_SCANS', '100'))
    MAX_CONCURRENT_OCR = int(os.getenv('MAX_CONCURRENT_OCR', '3'))
    
    # Caching
    CACHE_TTL_USER = 600
    CACHE_TTL_FRIENDS = 300
    CACHE_TTL_THUMBNAIL = 1800
    CACHE_MAXSIZE = 10000
    
    # OCR
    OCR_CONFIDENCE_THRESHOLD = 0.35  # Lowered for better detection
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT', '15'))
    
    @classmethod
    def validate(cls):
        if not cls.TOKEN:
            logger.error("❌ DISCORD_TOKEN not set!")
            sys.exit(1)
        logger.info(f"✅ Config loaded | Owner: {cls.OWNER_ID}")

Config.validate()

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════
try:
    import orjson
    JSON_AVAILABLE = True
    json_loads = orjson.loads
    json_dumps = lambda x: orjson.dumps(x).decode('utf-8')
except ImportError:
    import json as stdjson
    JSON_AVAILABLE = False
    json_loads = stdjson.loads
    json_dumps = stdjson.dumps

import aiohttp
from aiohttp import TCPConnector
import discord
from discord import app_commands
from discord.ui import Button, View

try:
    import asyncpg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logger.info("✅ Using uvloop")
except ImportError:
    pass

logger.info(f"🔧 PIL={PIL_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}, CV2={CV2_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════
class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs):
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                else:
                    raise Exception(f"Circuit {self.name} OPEN")
        
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            return result
        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
            raise e

# ═══════════════════════════════════════════════════════════
# MULTI-TIER CACHE
# ═══════════════════════════════════════════════════════════
class MultiTierCache:
    def __init__(self, maxsize: int = 10000):
        self.l1_cache = {}
        self.l1_expiry = {}
        self.maxsize = maxsize
        self._lock = asyncio.Lock()
        self.redis = None
        self._hits = 0
        self._misses = 0
        
    async def setup(self):
        if REDIS_AVAILABLE and Config.REDIS_URL:
            try:
                self.redis = await redis.from_url(Config.REDIS_URL, decode_responses=True)
                await self.redis.ping()
                logger.info("✅ Redis connected")
            except Exception as e:
                logger.warning(f"Redis failed: {e}")
                self.redis = None
    
    def _make_key(self, key: str) -> str:
        return f"omega:{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        if key in self.l1_cache:
            if time.time() < self.l1_expiry.get(key, 0):
                self._hits += 1
                return self.l1_cache[key]
            else:
                del self.l1_cache[key]
                if key in self.l1_expiry:
                    del self.l1_expiry[key]
        
        if self.redis:
            try:
                data = await self.redis.get(self._make_key(key))
                if data:
                    value = json_loads(data)
                    await self.set_l1(key, value)
                    self._hits += 1
                    return value
            except:
                pass
        
        self._misses += 1
        return None
    
    async def set_l1(self, key: str, value: Any, ttl: int = 60):
        async with self._lock:
            if len(self.l1_cache) >= self.maxsize:
                if self.l1_cache:
                    oldest = min(self.l1_expiry.items(), key=lambda x: x[1])
                    del self.l1_cache[oldest[0]]
                    del self.l1_expiry[oldest[0]]
            self.l1_cache[key] = value
            self.l1_expiry[key] = time.time() + ttl
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        await self.set_l1(key, value, min(ttl, 300))
        
        if self.redis:
            try:
                await self.redis.setex(self._make_key(key), ttl, json_dumps(value))
            except:
                pass
    
    def get_stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {"hits": self._hits, "misses": self._misses, "hit_rate": f"{hit_rate:.1f}%", "l1_size": len(self.l1_cache)}

# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════
@dataclass
class DetectedUser:
    username: str
    display_name: Optional[str]
    confidence: float
    source: str

@dataclass
class ScanResult:
    success: bool
    detected_users: List[DetectedUser]
    raw_text: str = ""
    scan_time: float = 0.0
    engines_used: List[str] = field(default_factory=list)

@dataclass
class FriendInfo:
    id: int
    username: str
    display_name: str
    thumbnail_url: Optional[str]
    is_online: bool

# ═══════════════════════════════════════════════════════════
# FAST IMAGE PREPROCESSING
# ═══════════════════════════════════════════════════════════
class ImagePreprocessor:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    async def preprocess(self, image_data: bytes) -> List[Tuple[bytes, str]]:
        if not PIL_AVAILABLE:
            return [(image_data, "original")]
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._preprocess_sync, image_data)
    
    def _preprocess_sync(self, image_data: bytes) -> List[Tuple[bytes, str]]:
        versions = []
        
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            w, h = img.size
            
            # Original
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            versions.append((buf.getvalue(), "original"))
            
            # Quick upscaling for small images
            if w < 400 or h < 200:
                scaled = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                scaled.save(buf, format='PNG', optimize=True)
                versions.append((buf.getvalue(), "scaled"))
            
            # High contrast (fast)
            contrast = ImageEnhance.Contrast(img).enhance(2.0)
            buf = io.BytesIO()
            contrast.save(buf, format='PNG', optimize=True)
            versions.append((buf.getvalue(), "contrast"))
            
        except Exception as e:
            logger.error(f"Preprocess error: {e}")
            versions.append((image_data, "original"))
        
        return versions

# ═══════════════════════════════════════════════════════════
# FAST OCR MANAGER
# ═══════════════════════════════════════════════════════════
class OCREngine:
    async def scan(self, image_data: bytes) -> Tuple[str, float]:
        raise NotImplementedError

class TesseractEngine(OCREngine):
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    async def scan(self, image_data: bytes) -> Tuple[str, float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._scan_sync, image_data)
    
    def _scan_sync(self, image_data: bytes) -> Tuple[str, float]:
        img = Image.open(io.BytesIO(image_data))
        # Fast config for username detection
        config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@'
        text = pytesseract.image_to_string(img, config=config)
        return text, 0.7 if text.strip() else 0.0

class EasyOCREngine(OCREngine):
    def __init__(self):
        self.reader = None
        self._ready = False
        self.executor = ThreadPoolExecutor(max_workers=1)
    
    async def initialize(self):
        if not self._ready and EASYOCR_AVAILABLE:
            try:
                loop = asyncio.get_event_loop()
                self.reader = await loop.run_in_executor(
                    None,
                    lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
                )
                self._ready = True
                logger.info("✅ EasyOCR ready")
            except Exception as e:
                logger.error(f"EasyOCR init: {e}")
    
    async def scan(self, image_data: bytes) -> Tuple[str, float]:
        if not self._ready:
            return "", 0.0
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._scan_sync, image_data)
    
    def _scan_sync(self, image_data: bytes) -> Tuple[str, float]:
        if not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return "", 0.0
        
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        results = self.reader.readtext(img, paragraph=True, detail=1)
        
        texts = []
        total_conf = 0
        for r in results:
            if len(r) >= 3:
                texts.append(r[1])
                total_conf += r[2]
        
        avg_conf = total_conf / len(results) if results else 0
        return '\n'.join(texts), avg_conf

class OCRSpaceEngine(OCREngine):
    def __init__(self, api_key: str, session: aiohttp.ClientSession):
        self.api_key = api_key
        self.session = session
        self.circuit_breaker = CircuitBreaker("ocrspace", failure_threshold=2)
    
    async def scan(self, image_data: bytes) -> Tuple[str, float]:
        if not self.api_key:
            return "", 0.0
        
        try:
            return await self.circuit_breaker.call(self._scan_impl, image_data)
        except:
            return "", 0.0
    
    async def _scan_impl(self, image_data: bytes) -> Tuple[str, float]:
        b64 = base64.b64encode(image_data).decode()
        data = {
            'apikey': self.api_key,
            'base64Image': f'data:image/png;base64,{b64}',
            'OCREngine': '2',
            'scale': 'true'
        }
        
        async with self.session.post(
            'https://api.ocr.space/parse/image',
            data=data,
            timeout=aiohttp.ClientTimeout(total=Config.OCR_TIMEOUT)
        ) as resp:
            result = await resp.json()
            if result.get('OCRExitCode') == 1:
                parsed = result.get('ParsedResults', [{}])[0]
                text = parsed.get('ParsedText', '')
                return text, 0.6
            return "", 0.0

class OCRManager:
    def __init__(self, ocr_space_key: str, session: aiohttp.ClientSession):
        self.session = session
        self.ocr_space_key = ocr_space_key
        self.preprocessor = ImagePreprocessor()
        self.engines: Dict[str, OCREngine] = {}
        self.semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_OCR)
        
        if TESSERACT_AVAILABLE:
            self.engines['tesseract'] = TesseractEngine()
        if EASYOCR_AVAILABLE:
            self.engines['easyocr'] = EasyOCREngine()
        if ocr_space_key:
            self.engines['ocrspace'] = OCRSpaceEngine(ocr_space_key, session)
    
    async def initialize(self):
        if 'easyocr' in self.engines:
            await self.engines['easyocr'].initialize()
    
    async def scan(self, image_data: bytes, hint: str = None) -> ScanResult:
        start = time.time()
        
        # Quick preprocess
        versions = await self.preprocessor.preprocess(image_data)
        
        # Run OCR with racing - return first good result
        tasks = []
        for engine_name, engine in self.engines.items():
            for version_data, version_name in versions[:2]:  # Limit versions
                task = self._run_ocr_with_timeout(engine, engine_name, version_data, version_name)
                tasks.append(task)
        
        # Race for fastest result
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_texts = []
        engines_used = []
        for result in results:
            if isinstance(result, tuple) and result[0]:
                all_texts.append(result[0])
                engines_used.append(result[2])
        
        combined_text = '\n'.join(all_texts)
        users = self._extract_usernames(combined_text, hint)
        
        return ScanResult(
            success=len(users) > 0,
            detected_users=users,
            raw_text=combined_text[:1500],
            scan_time=time.time() - start,
            engines_used=list(set(engines_used))
        )
    
    async def _run_ocr_with_timeout(self, engine: OCREngine, name: str, image_data: bytes, version: str) -> Tuple[str, float, str]:
        async with self.semaphore:
            try:
                text, conf = await asyncio.wait_for(engine.scan(image_data), timeout=Config.OCR_TIMEOUT)
                return text, conf, f"{name}"
            except:
                return "", 0.0, ""
    
    def _extract_usernames(self, text: str, hint: str = None) -> List[DetectedUser]:
        users = []
        lines = text.split('\n')
        
        # Pattern 1: @username
        for match in re.finditer(r'[@＠﹫]([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            username = match.group(1)
            conf = 0.95
            if hint and username.lower() == hint.lower().lstrip('@'):
                conf = 1.0
            users.append(DetectedUser(username=username, display_name=None, confidence=conf, source='@mention'))
        
        # Pattern 2: Display @ Username
        for match in re.finditer(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠﹫]\s*([a-z][a-z0-9_]{2,19})\b', text):
            display, username = match.groups()
            display = display.strip()
            if display and len(display) > 2:
                users.append(DetectedUser(username=username, display_name=display, confidence=0.98, source='display@user'))
        
        # Pattern 3: roblox.com/users/ID
        for match in re.finditer(r'roblox\.com/users/(\d+)', text, re.I):
            users.append(DetectedUser(username=f"ID:{match.group(1)}", display_name=None, confidence=0.99, source='url'))
        
        # Pattern 4: Context username
        for i, line in enumerate(lines):
            line_lower = line.lower()
            has_context = any(word in line_lower for word in ['roblox', 'profile', '@', 'user'])
            
            for match in re.finditer(r'\b([a-z][a-z0-9_]{2,19})\b', line):
                username = match.group(1)
                if username.lower() in {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 'friends', 'following', 'followers', 'home'}:
                    continue
                
                conf = 0.65 if has_context else 0.45
                surrounding = ' '.join(lines[max(0,i-1):min(len(lines), i+2)]).lower()
                if any(x in surrounding for x in ['roblox', '@', 'profile']):
                    conf = min(conf + 0.15, 0.90)
                
                if hint and username.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                
                users.append(DetectedUser(username=username, display_name=None, confidence=conf, source='context'))
        
        # Deduplicate
        seen = {}
        for u in sorted(users, key=lambda x: x.confidence, reverse=True):
            key = u.username.lower()
            if key not in seen:
                seen[key] = u
        
        return list(seen.values())

# ═══════════════════════════════════════════════════════════
# ROBLOX API
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: MultiTierCache):
        self.cache = cache
        self.session = None
        self.connector = None
        
    async def setup(self):
        self.connector = TCPConnector(limit=100, limit_per_host=30, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        verified = []
        
        for user in users[:5]:
            cached = await self.cache.get(f"user:{user.username.lower()}")
            if cached:
                verified.append({'profile': cached, 'detected': user, 'score': user.confidence})
                continue
            
            profile = await self._fetch_user(user.username)
            if profile:
                await self.cache.set(f"user:{user.username.lower()}", profile, Config.CACHE_TTL_USER)
                verified.append({'profile': profile, 'detected': user, 'score': user.confidence})
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, username: str) -> Optional[Dict]:
        try:
            if username.startswith("ID:"):
                user_id = int(username.split(":")[1])
                return await self._fetch_by_id(user_id)
            
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [username], "excludeBannedUsers": False},
                timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data.get('data'):
                    return None
                return await self._fetch_by_id(data['data'][0]['id'])
        except:
            return None
    
    async def _fetch_by_id(self, user_id: int) -> Optional[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/{user_id}',
                timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    return None
                profile = await resp.json()
                profile['thumbnailUrl'] = await self._get_avatar_url(user_id)
                return profile
        except:
            return None
    
    async def _get_avatar_url(self, user_id: int) -> Optional[str]:
        cached = await self.cache.get(f"avatar:{user_id}")
        if cached:
            return cached
        
        try:
            async with self.session.get(
                f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png',
                timeout=aiohttp.ClientTimeout(total=4)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        url = data['data'][0].get('imageUrl')
                        if url:
                            await self.cache.set(f"avatar:{user_id}", url, Config.CACHE_TTL_THUMBNAIL)
                        return url
        except:
            pass
        return None
    
    async def get_friends(self, user_id: int) -> List[FriendInfo]:
        cached = await self.cache.get(f"friends:{user_id}")
        if cached:
            return [FriendInfo(**f) for f in cached]
        
        try:
            async with self.session.get(
                f'https://friends.roblox.com/v1/users/{user_id}/friends',
                timeout=aiohttp.ClientTimeout(total=Config.FRIENDS_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    return []
                
                data = await resp.json()
                friends_data = data.get('data', [])[:50]
                
                if not friends_data:
                    return []
                
                # Get thumbnails
                friend_ids = [str(f['id']) for f in friends_data]
                thumb_map = await self._get_batch_thumbnails(friend_ids)
                
                friend_infos = []
                for friend in friends_data:
                    fid = str(friend['id'])
                    friend_infos.append(FriendInfo(
                        id=friend['id'],
                        username=friend['name'],
                        display_name=friend.get('displayName', friend['name']),
                        thumbnail_url=thumb_map.get(fid),
                        is_online=friend.get('isOnline', False)
                    ))
                
                cache_data = [{
                    'id': f.id, 'username': f.username, 'display_name': f.display_name,
                    'thumbnail_url': f.thumbnail_url, 'is_online': f.is_online
                } for f in friend_infos]
                await self.cache.set(f"friends:{user_id}", cache_data, Config.CACHE_TTL_FRIENDS)
                
                return friend_infos
        except Exception as e:
            logger.error(f"Get friends error: {e}")
            return []
    
    async def _get_batch_thumbnails(self, user_ids: List[str]) -> Dict[str, str]:
        if not user_ids:
            return {}
        
        try:
            requests_data = [
                {
                    "requestId": f"{uid}:headshot:150x150:png",
                    "type": "AvatarHeadShot",
                    "targetId": int(uid),
                    "size": "150x150",
                    "format": "png"
                }
                for uid in user_ids[:100]
            ]
            
            async with self.session.post(
                'https://thumbnails.roblox.com/v1/batch',
                json={"requests": requests_data},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    thumb_map = {}
                    for item in data.get('data', []):
                        uid = item.get('requestId', '').split(':')[0]
                        thumb_map[uid] = item.get('imageUrl')
                    return thumb_map
        except:
            pass
        return {}
    
    async def search_similar(self, username: str) -> List[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5',
                timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', [])
                return []
        except:
            return []

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
class DatabaseManager:
    def __init__(self):
        self.pool = None
        self._whitelist: Set[str] = set()
        self.json_path = "data"
        os.makedirs(self.json_path, exist_ok=True)
        
    async def setup(self):
        if DB_AVAILABLE and Config.DATABASE_URL:
            try:
                self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=1, max_size=5)
                await self._init_tables()
            except:
                pass
        await self._load_whitelist()
    
    async def _init_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS whitelist (user_id TEXT PRIMARY KEY)")
            await conn.execute("CREATE TABLE IF NOT EXISTS user_stats (user_id TEXT PRIMARY KEY, data JSONB)")
    
    async def _load_whitelist(self):
        self._whitelist = {Config.OWNER_ID}
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT user_id FROM whitelist")
                    for row in rows:
                        self._whitelist.add(str(row['user_id']))
            except:
                pass
        
        try:
            path = os.path.join(self.json_path, "whitelist.json")
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    self._whitelist.update(str(u) for u in data.get('users', []))
        except:
            pass
        
        logger.info(f"✅ Whitelist: {len(self._whitelist)} users")
    
    def is_whitelisted(self, user_id: str) -> bool:
        return str(user_id) in self._whitelist
    
    async def add_to_whitelist(self, user_id: str) -> bool:
        user_id = str(user_id)
        if user_id in self._whitelist:
            return False
        self._whitelist.add(user_id)
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("INSERT INTO whitelist (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
            except:
                pass
        
        try:
            with open(os.path.join(self.json_path, "whitelist.json"), 'w') as f:
                json.dump({'users': list(self._whitelist)}, f)
        except:
            pass
        return True
    
    async def remove_from_whitelist(self, user_id: str) -> bool:
        user_id = str(user_id)
        if user_id not in self._whitelist or user_id == Config.OWNER_ID:
            return False
        self._whitelist.discard(user_id)
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("DELETE FROM whitelist WHERE user_id = $1", user_id)
            except:
                pass
        
        try:
            with open(os.path.join(self.json_path, "whitelist.json"), 'w') as f:
                json.dump({'users': list(self._whitelist)}, f)
        except:
            pass
        return True
    
    async def get_stats(self, user_id: str) -> Dict:
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT data FROM user_stats WHERE user_id = $1", user_id)
                    if row:
                        return row['data'] if isinstance(row['data'], dict) else json_loads(row['data'])
            except:
                pass
        
        try:
            path = os.path.join(self.json_path, f"{user_id}.json")
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return json.load(f)
        except:
            pass
        
        return {'total_scans': 0, 'successful_scans': 0, 'favorite_users': []}
    
    async def save_stats(self, user_id: str, data: Dict):
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO user_stats (user_id, data) VALUES ($1, $2)
                        ON CONFLICT (user_id) DO UPDATE SET data = $2
                    """, user_id, json_dumps(data))
            except:
                pass
        
        try:
            with open(os.path.join(self.json_path, f"{user_id}.json"), 'w') as f:
                json.dump(data, f, default=str)
        except:
            pass

# ═══════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════
class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()
    
    async def check(self, key: str) -> Tuple[bool, float]:
        now = time.time()
        async with self._lock:
            if key not in self.requests:
                self.requests[key] = []
            
            self.requests[key] = [t for t in self.requests[key] if now - t < self.window_seconds]
            
            if len(self.requests[key]) >= self.max_requests:
                retry_after = self.requests[key][0] + self.window_seconds - now
                return False, max(0, retry_after)
            
            self.requests[key].append(now)
            return True, 0

# ═══════════════════════════════════════════════════════════
# BOT CLASS
# ═══════════════════════════════════════════════════════════
class TrueOmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = DatabaseManager()
        self.cache = MultiTierCache()
        self.rate_limiter = RateLimiter(Config.RATE_LIMIT_PER_MINUTE, 60)
        self.ocr = None
        self.roblox = None
        self.scan_semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_SCANS)
        
    async def setup_hook(self):
        logger.info("🔧 Starting TRUE OMEGA v4.1...")
        
        await self.cache.setup()
        await self.db.setup()
        
        self.roblox = RobloxAPI(self.cache)
        await self.roblox.setup()
        
        self.ocr = OCRManager(Config.OCR_SPACE_KEY, self.roblox.session)
        await self.ocr.initialize()
        
        self._register_commands()
        await self._sync_commands()
        
        logger.info("✅ Bot ready!")
    
    def _register_commands(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username")
        @app_commands.describe(image="Screenshot", hint="Optional username hint")
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self._scan(interaction, image, hint)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (owner only)")
        @app_commands.describe(user="User ID")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self._whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search user by username")
        @app_commands.describe(username="Username")
        async def search_cmd(interaction: discord.Interaction, username: str):
            await self._search(interaction, username)
        
        @self.tree.command(name="stats", description="📊 Your stats")
        async def stats_cmd(interaction: discord.Interaction):
            await self._stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Status")
        async def ping_cmd(interaction: discord.Interaction):
            await self._ping(interaction)
    
    async def _sync_commands(self):
        for i in range(3):
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} commands")
                return
            except Exception as e:
                logger.error(f"Sync error: {e}")
                await asyncio.sleep(5)
    
    async def _scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
        user_id = str(interaction.user.id)
        
        if not self.db.is_whitelisted(user_id):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Not Whitelisted", color=0xFF0000),
                ephemeral=True
            )
            return
        
        allowed, retry_after = await self.rate_limiter.check(user_id)
        if not allowed:
            await interaction.response.send_message(
                embed=discord.Embed(title="⏰ Rate Limited", description=f"Wait {int(retry_after)}s", color=0xFFA500),
                ephemeral=True
            )
            return
        
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ File too large", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        async with self.scan_semaphore:
            try:
                # Download
                download_start = time.time()
                async with self.roblox.session.get(image.url, timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
                download_time = time.time() - download_start
                
                # OCR with timeout
                ocr_task = self.ocr.scan(img_data, hint)
                result = await asyncio.wait_for(ocr_task, timeout=Config.OVERALL_TIMEOUT)
                
                if not result.success:
                    embed = discord.Embed(
                        title="❌ No Username Found",
                        description="Could not detect a valid Roblox username.",
                        color=0xFF6B6B
                    )
                    if result.raw_text:
                        clean_lines = [line.strip() for line in result.raw_text.split('\n') if len(line.strip()) > 2][:15]
                        if clean_lines:
                            embed.add_field(name="📝 Detected Text", value=f"```{'\n'.join(clean_lines)[:900]}```", inline=False)
                    embed.add_field(name="💡 Tips", value="• Make sure @username is visible\n• Use the `hint` parameter\n• Ensure good image quality", inline=False)
                    embed.set_footer(text=f"Engines: {', '.join(result.engines_used) or 'none'} | Time: {result.scan_time:.2f}s")
                    await interaction.followup.send(embed=embed)
                    return
                
                # Verify
                verified = await self.roblox.verify_users(result.detected_users)
                
                if not verified:
                    similar = await self.roblox.search_similar(result.detected_users[0].username)
                    embed = discord.Embed(
                        title="❌ User Not Found",
                        description=f"`@{result.detected_users[0].username}` doesn't exist.",
                        color=0xFF6B6B
                    )
                    if similar:
                        similar_text = '\n'.join(f"• [{s.get('displayName', s['name'])} (@{s['name']})](https://roblox.com/users/{s['id']}/profile)" for s in similar[:5])
                        embed.add_field(name="🔍 Did you mean?", value=similar_text, inline=False)
                    await interaction.followup.send(embed=embed)
                    return
                
                # SUCCESS
                best = verified[0]
                profile = best['profile']
                detected = best['detected']
                
                embed = self._create_profile_embed(profile, detected, result.scan_time, best['score'], download_time)
                embed.set_image(url=image.url)
                
                view = ResultView(profile, self, user_id)
                await interaction.followup.send(embed=embed, view=view)
                
                # Stats
                stats = await self.db.get_stats(user_id)
                stats['total_scans'] = stats.get('total_scans', 0) + 1
                stats['successful_scans'] = stats.get('successful_scans', 0) + 1
                if profile['name'] not in stats.get('favorite_users', []):
                    stats['favorite_users'] = [profile['name']] + stats.get('favorite_users', [])[:9]
                await self.db.save_stats(user_id, stats)
                
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    embed=discord.Embed(title="⏱️ Timeout", description="Scan took too long. Try a clearer image.", color=0xFFA500)
                )
            except Exception as e:
                logger.error(f"Scan error: {traceback.format_exc()}")
                await interaction.followup.send(embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000))
    
    def _create_profile_embed(self, profile: Dict, detected: DetectedUser, scan_time: float, score: float, download_time: float = 0) -> discord.Embed:
        if profile.get('isBanned'):
            color, status = 0xFF0000, "🔴 BANNED"
        elif score >= 0.95:
            color, status = 0x00FF00, "✅ CERTAIN"
        elif score >= 0.80:
            color, status = 0x55FF55, "✓ HIGH"
        elif score >= 0.60:
            color, status = 0xFFAA00, "⚠ MEDIUM"
        else:
            color, status = 0xFF5555, "? LOW"
        
        embed = discord.Embed(
            title=f"{profile.get('displayName', profile['name'])}",
            url=f"https://roblox.com/users/{profile['id']}/profile",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.description = f"**@{profile['name']}** | `{score:.0%} {status}`"
        
        if detected.display_name and detected.display_name != profile['name']:
            embed.add_field(name="📝 Detected Display", value=detected.display_name, inline=True)
        
        embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
        
        created = str(profile.get('created', 'Unknown'))[:10]
        embed.add_field(name="📅 Created", value=created, inline=True)
        
        embed.add_field(name="⚡ Speed", value=f"Total: `{scan_time:.2f}s` | DL: `{download_time:.2f}s`", inline=True)
        
        if profile.get('description'):
            desc = profile['description'][:200]
            if len(profile['description']) > 200:
                desc += "..."
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        if profile.get('thumbnailUrl'):
            embed.set_thumbnail(url=profile['thumbnailUrl'])
        
        embed.set_footer(text="TRUE OMEGA v4.1 | Click buttons below")
        return embed
    
    async def _whitelist(self, interaction: discord.Interaction, user: str):
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message(embed=discord.Embed(title="⛔ Owner only", color=0xFF0000), ephemeral=True)
            return
        
        target = re.sub(r'[<@!>]', '', user).strip()
        if not target.isdigit():
            await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid ID", color=0xFF0000), ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        if self.db.is_whitelisted(target):
            if await self.db.remove_from_whitelist(target):
                await interaction.followup.send(embed=discord.Embed(title=f"✅ Removed {target}", color=0x00FF00))
            else:
                await interaction.followup.send(embed=discord.Embed(title="❌ Cannot remove owner", color=0xFF0000))
        else:
            if await self.db.add_to_whitelist(target):
                await interaction.followup.send(embed=discord.Embed(title=f"✅ Added {target}", color=0x00FF00))
            else:
                await interaction.followup.send(embed=discord.Embed(title="❌ Already whitelisted", color=0xFFA500))
    
    async def _search(self, interaction: discord.Interaction, username: str):
        if not self.db.is_whitelisted(str(interaction.user.id)):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        users = [DetectedUser(username=username, display_name=None, confidence=1.0, source="direct")]
        verified = await self.roblox.verify_users(users)
        
        if verified:
            best = verified[0]
            embed = self._create_profile_embed(best['profile'], users[0], 0.1, 1.0)
            view = ResultView(best['profile'], self, str(interaction.user.id))
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=discord.Embed(title="❌ Not found", color=0xFF0000))
    
    async def _stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(str(interaction.user.id))
        total = stats.get('total_scans', 0)
        success = stats.get('successful_scans', 0)
        rate = (success / total * 100) if total > 0 else 0
        
        embed = discord.Embed(title="📊 Your Stats", color=0x00D4AA)
        embed.add_field(name="Total Scans", value=str(total), inline=True)
        embed.add_field(name="Successful", value=str(success), inline=True)
        embed.add_field(name="Success Rate", value=f"{rate:.1f}%", inline=True)
        
        favorites = stats.get('favorite_users', [])
        if favorites:
            embed.add_field(name="⭐ Recent Favorites", value='\n'.join(f"• @{u}" for u in favorites[:5]), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
        embed.add_field(name="Whitelisted", value=str(len(self.db._whitelist)), inline=True)
        embed.add_field(name="Cache Hit Rate", value=self.cache.get_stats()['hit_rate'], inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# FIXED FRIENDS VIEW - CLEAN FORMAT
# ═══════════════════════════════════════════════════════════
class FriendsView(discord.ui.View):
    def __init__(self, friends: List[FriendInfo], profile_name: str, bot: TrueOmegaBot, user_id: str, page: int = 0):
        super().__init__(timeout=180)
        self.friends = friends
        self.profile_name = profile_name
        self.bot = bot
        self.user_id = user_id
        self.page = page
        self.per_page = 15  # 15 friends per page for cleaner display
        
        self._update_buttons()
    
    def _update_buttons(self):
        self.clear_items()
        total_pages = (len(self.friends) + self.per_page - 1) // self.per_page
        
        if self.page > 0:
            prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary)
            prev_btn.callback = self._prev_page
            self.add_item(prev_btn)
        
        page_btn = discord.ui.Button(label=f"Page {self.page + 1}/{max(1, total_pages)}", style=discord.ButtonStyle.gray, disabled=True)
        self.add_item(page_btn)
        
        if self.page < total_pages - 1:
            next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            next_btn.callback = self._next_page
            self.add_item(next_btn)
    
    async def _prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self._update_buttons()
        embed = self._create_friends_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def _next_page(self, interaction: discord.Interaction):
        self.page += 1
        self._update_buttons()
        embed = self._create_friends_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    def _create_friends_embed(self) -> discord.Embed:
        start = self.page * self.per_page
        end = min(start + self.per_page, len(self.friends))
        page_friends = self.friends[start:end]
        
        embed = discord.Embed(
            title=f"👥 {self.profile_name}'s Friends",
            description=f"**{len(self.friends)}** total friends | Showing **{start + 1}-{end}**",
            color=0x00D4AA
        )
        
        # Build clean friend list - ONE friend per line for clarity
        friend_lines = []
        for friend in page_friends:
            status = "🟢" if friend.is_online else "⚫"
            display = friend.display_name if friend.display_name != friend.username else ""
            
            if display:
                line = f"{status} **{display}** (@{friend.username})"
            else:
                line = f"{status} **@{friend.username}**"
            
            friend_lines.append(line)
        
        # Split into chunks of 5 for fields (Discord limit)
        chunk_size = 5
        for i in range(0, len(friend_lines), chunk_size):
            chunk = friend_lines[i:i + chunk_size]
            chunk_num = (i // chunk_size) + 1
            total_chunks = (len(friend_lines) + chunk_size - 1) // chunk_size
            
            embed.add_field(
                name=f"Friends {start + i + 1}-{min(start + i + chunk_size, end)}",
                value='\n'.join(chunk) if chunk else "No friends",
                inline=False
            )
        
        # Add footer with navigation hint
        embed.set_footer(text="Click Previous/Next to navigate • 🟢 = Online")
        
        return embed

class ResultView(discord.ui.View):
    def __init__(self, profile: Dict, bot: TrueOmegaBot, user_id: str):
        super().__init__(timeout=300)
        self.profile = profile
        self.bot = bot
        self.user_id = user_id
        
        self.add_item(discord.ui.Button(
            label="View Profile",
            style=discord.ButtonStyle.link,
            url=f"https://roblox.com/users/{profile['id']}/profile",
            emoji="🔗"
        ))
    
    @discord.ui.button(label="View Friends", style=discord.ButtonStyle.primary, emoji="👥")
    async def view_friends(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        try:
            friends = await self.bot.roblox.get_friends(self.profile['id'])
            
            if not friends:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="👥 Friends",
                        description="This user has no friends or their friends list is private.",
                        color=0xFFAA00
                    ),
                    ephemeral=True
                )
                return
            
            view = FriendsView(
                friends,
                self.profile.get('displayName', self.profile['name']),
                self.bot,
                self.user_id
            )
            embed = view._create_friends_embed()
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Friends error: {e}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error loading friends", color=0xFF0000),
                ephemeral=True
            )
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="⭐")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        stats = await self.bot.db.get_stats(self.user_id)
        
        if self.profile['name'] in stats.get('favorite_users', []):
            await interaction.response.send_message(embed=discord.Embed(title="⭐ Already saved", color=0xFFA500), ephemeral=True)
            return
        
        stats['favorite_users'] = [self.profile['name']] + stats.get('favorite_users', [])[:9]
        await self.bot.db.save_stats(self.user_id, stats)
        
        await interaction.response.send_message(embed=discord.Embed(title=f"⭐ Saved @{self.profile['name']}!", color=0x00FF00), ephemeral=True)
    
    @discord.ui.button(label="Scan Again", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def scan_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(title="🔄 Scan Again", description="Use `/scan` with a new image!", color=0x00D4AA),
            ephemeral=True
        )

# ═══════════════════════════════════════════════════════════
# HEALTH SERVER
# ═══════════════════════════════════════════════════════════
async def health_check_server():
    from aiohttp import web
    
    async def health(request):
        return web.Response(text='OK - TRUE OMEGA v4.1')
    
    app = web.Application()
    app.router.add_get('/health', health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"✅ Health server on port {port}")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def main():
    asyncio.create_task(health_check_server())
    bot = TrueOmegaBot()
    
    try:
        await bot.start(Config.TOKEN)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.close()

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"Fatal: {e}")
            logger.error(traceback.format_exc())
            time.sleep(10)
