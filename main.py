"""
🚀 TRUE OMEGA v4.0 - ULTIMATE ROBLOX SCANNER
The fastest, most powerful, most reliable Roblox scanner ever built.
Maximum performance optimization with aggressive caching and parallel execution.
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
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple, Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from enum import Enum
import logging
import functools

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
    # Core
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # Performance
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '52428800'))
    OVERALL_TIMEOUT = 20  # Max total scan time
    DOWNLOAD_TIMEOUT = 8
    OCR_TIMEOUT = 6
    API_TIMEOUT = 5
    FRIENDS_TIMEOUT = 10
    
    # Concurrency
    MAX_CONCURRENT_SCANS = int(os.getenv('MAX_CONCURRENT_SCANS', '100'))
    MAX_CONCURRENT_OCR = int(os.getenv('MAX_CONCURRENT_OCR', '5'))
    MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '20'))
    
    # Caching
    CACHE_TTL_USER = 600      # 10 minutes
    CACHE_TTL_FRIENDS = 300   # 5 minutes
    CACHE_TTL_THUMBNAIL = 1800  # 30 minutes
    CACHE_MAXSIZE = 10000
    
    # OCR
    OCR_CONFIDENCE_THRESHOLD = 0.4
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT', '10'))
    
    @classmethod
    def validate(cls):
        if not cls.TOKEN:
            logger.error("❌ DISCORD_TOKEN not set!")
            sys.exit(1)
        logger.info(f"✅ Config loaded | Owner: {cls.OWNER_ID}")
        logger.info(f"⚡ Performance: {cls.MAX_CONCURRENT_SCANS} concurrent scans, {cls.OVERALL_TIMEOUT}s timeout")

Config.validate()

# ═══════════════════════════════════════════════════════════
# IMPORTS WITH FALLBACKS
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
    logger.warning("orjson not available, using standard json")

import aiohttp
from aiohttp import TCPConnector
import discord
from discord import app_commands
from discord.ui import Button, View, Select

try:
    import asyncpg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    logger.warning("asyncpg not available")

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL not available")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("Tesseract not available")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.warning("EasyOCR not available")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("CV2 not available")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.warning("NumPy not available")

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available")

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logger.info("✅ Using uvloop for faster event loop")
except ImportError:
    logger.info("Using standard asyncio event loop")

logger.info(f"🔧 PIL={PIL_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}, CV2={CV2_AVAILABLE}, orjson={JSON_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# CIRCUIT BREAKER PATTERN
# ═══════════════════════════════════════════════════════════
class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered

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
                    logger.info(f"🔧 Circuit {self.name} half-open, testing...")
                else:
                    raise Exception(f"Circuit {self.name} is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    logger.info(f"✅ Circuit {self.name} closed")
            return result
        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"🔴 Circuit {self.name} OPEN after {self.failure_count} failures")
            raise e

# ═══════════════════════════════════════════════════════════
# MULTI-TIER CACHE SYSTEM
# ═══════════════════════════════════════════════════════════
class MultiTierCache:
    """L1: In-memory dict, L2: LRU, L3: Redis"""
    
    def __init__(self, maxsize: int = 10000):
        self.l1_cache = {}  # Fast in-memory
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
                logger.info("✅ Redis cache connected")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                self.redis = None
    
    def _make_key(self, key: str) -> str:
        return f"omega:{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        # L1 Check
        if key in self.l1_cache:
            if time.time() < self.l1_expiry.get(key, 0):
                self._hits += 1
                return self.l1_cache[key]
            else:
                del self.l1_cache[key]
                if key in self.l1_expiry:
                    del self.l1_expiry[key]
        
        # L3 Redis Check
        if self.redis:
            try:
                data = await self.redis.get(self._make_key(key))
                if data:
                    value = json_loads(data)
                    # Promote to L1
                    await self.set_l1(key, value)
                    self._hits += 1
                    return value
            except Exception as e:
                logger.debug(f"Redis get error: {e}")
        
        self._misses += 1
        return None
    
    async def set_l1(self, key: str, value: Any, ttl: int = 60):
        async with self._lock:
            if len(self.l1_cache) >= self.maxsize:
                # Remove oldest
                if self.l1_cache:
                    oldest = min(self.l1_expiry.items(), key=lambda x: x[1])
                    del self.l1_cache[oldest[0]]
                    del self.l1_expiry[oldest[0]]
            self.l1_cache[key] = value
            self.l1_expiry[key] = time.time() + ttl
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        # Set L1
        await self.set_l1(key, value, min(ttl, 300))
        
        # Set L3 Redis
        if self.redis:
            try:
                await self.redis.setex(
                    self._make_key(key),
                    ttl,
                    json_dumps(value)
                )
            except Exception as e:
                logger.debug(f"Redis set error: {e}")
    
    async def delete(self, key: str):
        if key in self.l1_cache:
            del self.l1_cache[key]
            if key in self.l1_expiry:
                del self.l1_expiry[key]
        if self.redis:
            try:
                await self.redis.delete(self._make_key(key))
            except:
                pass
    
    def get_stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "l1_size": len(self.l1_cache)
        }

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
    preprocessing_time: float = 0.0
    ocr_time: float = 0.0
    verification_time: float = 0.0

@dataclass
class FriendInfo:
    id: int
    username: str
    display_name: str
    thumbnail_url: Optional[str]
    is_online: bool

# ═══════════════════════════════════════════════════════════
# ADVANCED IMAGE PREPROCESSING
# ═══════════════════════════════════════════════════════════
class ImagePreprocessor:
    """Advanced preprocessing pipeline for OCR optimization"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    async def preprocess(self, image_data: bytes) -> List[Tuple[bytes, str]]:
        """Generate multiple preprocessed versions for multi-scale OCR"""
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
            
            # Smart upscaling based on image size
            if w < 300 or h < 150:
                scale = 3
            elif w < 500 or h < 250:
                scale = 2
            else:
                scale = 1.5
            
            if scale > 1:
                scaled = img.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                scaled.save(buf, format='PNG', optimize=True)
                versions.append((buf.getvalue(), f"scaled_{scale}x"))
            
            # High contrast version
            contrast = ImageEnhance.Contrast(img).enhance(2.5)
            contrast = ImageEnhance.Sharpness(contrast).enhance(2.0)
            buf = io.BytesIO()
            contrast.save(buf, format='PNG', optimize=True)
            versions.append((buf.getvalue(), "high_contrast"))
            
            # Inverted (for dark mode)
            inverted = ImageOps.invert(img)
            inverted = ImageEnhance.Contrast(inverted).enhance(2.0)
            buf = io.BytesIO()
            inverted.save(buf, format='PNG', optimize=True)
            versions.append((buf.getvalue(), "inverted"))
            
            # CLAHE (Contrast Limited Adaptive Histogram Equalization)
            if CV2_AVAILABLE and NUMPY_AVAILABLE:
                img_array = np.array(img)
                lab = cv2.cvtColor(img_array, cv2.COLOR_RGB2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                lab = cv2.merge([l, a, b])
                enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
                enhanced_pil = Image.fromarray(enhanced)
                buf = io.BytesIO()
                enhanced_pil.save(buf, format='PNG', optimize=True)
                versions.append((buf.getvalue(), "clahe"))
            
            # Grayscale with adaptive thresholding
            gray = img.convert('L')
            gray = ImageEnhance.Contrast(gray).enhance(2.0)
            buf = io.BytesIO()
            gray.save(buf, format='PNG', optimize=True)
            versions.append((buf.getvalue(), "grayscale"))
            
        except Exception as e:
            logger.error(f"Preprocessing error: {e}")
            versions.append((image_data, "original_fallback"))
        
        return versions

# ═══════════════════════════════════════════════════════════
# OCR ENGINE MANAGER - PARALLEL EXECUTION
# ═══════════════════════════════════════════════════════════
class OCREngine:
    """Base class for OCR engines"""
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
        # Optimized config for Roblox username detection
        config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@'
        text = pytesseract.image_to_string(img, config=config)
        confidence = 0.7 if text.strip() else 0.0
        return text, confidence

class EasyOCREngine(OCREngine):
    def __init__(self):
        self.reader = None
        self._ready = False
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    async def initialize(self):
        if not self._ready and EASYOCR_AVAILABLE:
            try:
                loop = asyncio.get_event_loop()
                self.reader = await loop.run_in_executor(
                    None,
                    lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
                )
                self._ready = True
                logger.info("✅ EasyOCR engine ready")
            except Exception as e:
                logger.error(f"EasyOCR init failed: {e}")
    
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
                bbox, text, conf = r[0], r[1], r[2]
                texts.append(text)
                total_conf += conf
        
        avg_conf = total_conf / len(results) if results else 0
        return '\n'.join(texts), avg_conf

class OCRSpaceEngine(OCREngine):
    def __init__(self, api_key: str, session: aiohttp.ClientSession):
        self.api_key = api_key
        self.session = session
        self.circuit_breaker = CircuitBreaker("ocrspace", failure_threshold=3)
    
    async def scan(self, image_data: bytes) -> Tuple[str, float]:
        if not self.api_key:
            return "", 0.0
        
        try:
            return await self.circuit_breaker.call(self._scan_impl, image_data)
        except Exception as e:
            logger.debug(f"OCR.space failed: {e}")
            return "", 0.0
    
    async def _scan_impl(self, image_data: bytes) -> Tuple[str, float]:
        b64 = base64.b64encode(image_data).decode()
        data = {
            'apikey': self.api_key,
            'base64Image': f'data:image/png;base64,{b64}',
            'OCREngine': '2',
            'scale': 'true',
            'detectOrientation': 'true'
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
                conf = float(parsed.get('TextOverlay', {}).get('Lines', [{}])[0].get('Words', [{}])[0].get('Confidence', 50)) / 100
                return text, conf
            return "", 0.0

class OCRManager:
    """Manages multiple OCR engines with parallel execution and racing"""
    
    def __init__(self, ocr_space_key: str, session: aiohttp.ClientSession):
        self.session = session
        self.ocr_space_key = ocr_space_key
        self.preprocessor = ImagePreprocessor()
        self.engines: Dict[str, OCREngine] = {}
        self.semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_OCR)
        
        # Initialize engines
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
        
        # Preprocess
        prep_start = time.time()
        versions = await self.preprocessor.preprocess(image_data)
        prep_time = time.time() - prep_start
        
        # Run OCR on all versions in parallel with racing
        ocr_start = time.time()
        all_results = []
        
        # Create tasks for all engine/version combinations
        tasks = []
        for engine_name, engine in self.engines.items():
            for version_data, version_name in versions[:3]:  # Limit to first 3 versions
                task = self._run_ocr_with_timeout(engine, engine_name, version_data, version_name)
                tasks.append(task)
        
        # Race - return as soon as we have good results
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, tuple) and result[0]:
                all_results.append(result)
        
        ocr_time = time.time() - ocr_start
        
        # Combine all texts
        combined_text = '\n'.join([r[0] for r in all_results])
        engines_used = list(set([r[2] for r in all_results]))
        
        # Extract usernames
        users = self._extract_usernames(combined_text, hint)
        
        total_time = time.time() - start
        
        return ScanResult(
            success=len(users) > 0,
            detected_users=users,
            raw_text=combined_text[:2000],
            scan_time=total_time,
            engines_used=engines_used,
            preprocessing_time=prep_time,
            ocr_time=ocr_time,
            verification_time=0
        )
    
    async def _run_ocr_with_timeout(self, engine: OCREngine, name: str, image_data: bytes, version: str) -> Tuple[str, float, str]:
        async with self.semaphore:
            try:
                text, conf = await asyncio.wait_for(
                    engine.scan(image_data),
                    timeout=Config.OCR_TIMEOUT
                )
                return text, conf, f"{name}_{version}"
            except asyncio.TimeoutError:
                logger.debug(f"OCR timeout: {name}_{version}")
                return "", 0.0, ""
            except Exception as e:
                logger.debug(f"OCR error {name}: {e}")
                return "", 0.0, ""
    
    def _extract_usernames(self, text: str, hint: str = None) -> List[DetectedUser]:
        """Advanced username extraction with Roblox-specific patterns"""
        users = []
        lines = text.split('\n')
        text_lower = text.lower()
        
        # Pattern 1: @username (most common)
        for match in re.finditer(r'[@＠﹫]([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            username = match.group(1)
            conf = 0.95
            if hint and username.lower() == hint.lower().lstrip('@'):
                conf = 1.0
            users.append(DetectedUser(username=username, display_name=None, confidence=conf, source='@mention'))
        
        # Pattern 2: Display Name @ Username format
        for match in re.finditer(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠﹫]\s*([a-z][a-z0-9_]{2,19})\b', text):
            display, username = match.groups()
            display = display.strip()
            if display and len(display) > 2:
                users.append(DetectedUser(
                    username=username,
                    display_name=display,
                    confidence=0.98,
                    source='display@user'
                ))
        
        # Pattern 3: roblox.com/users/ID
        for match in re.finditer(r'roblox\.com/users/(\d+)', text, re.I):
            users.append(DetectedUser(
                username=f"ID:{match.group(1)}",
                display_name=None,
                confidence=0.99,
                source='url'
            ))
        
        # Pattern 4: Username with Roblox context
        for i, line in enumerate(lines):
            line_lower = line.lower()
            has_context = any(word in line_lower for word in ['roblox', 'profile', '@', 'user', 'display', 'username'])
            
            for match in re.finditer(r'\b([a-z][a-z0-9_]{2,19})\b', line):
                username = match.group(1)
                
                # Skip common words
                if username.lower() in {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 'friends', 'following', 'followers', 'home', 'catalog', 'create'}:
                    continue
                
                conf = 0.70 if has_context else 0.50
                
                # Check surrounding lines
                surrounding = ' '.join(lines[max(0,i-1):min(len(lines), i+2)]).lower()
                if any(x in surrounding for x in ['roblox', '@', 'profile', 'user']):
                    conf = min(conf + 0.15, 0.90)
                
                if hint and username.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                
                users.append(DetectedUser(username=username, display_name=None, confidence=conf, source='context'))
        
        # Deduplicate - keep highest confidence
        seen = {}
        for u in sorted(users, key=lambda x: x.confidence, reverse=True):
            key = u.username.lower()
            if key not in seen:
                seen[key] = u
        
        return list(seen.values())

# ═══════════════════════════════════════════════════════════
# ROBLOX API - OPTIMIZED WITH CONNECTION POOLING
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: MultiTierCache):
        self.cache = cache
        self.session = None
        self.connector = None
        self.circuit_breakers = {
            'users': CircuitBreaker("roblox_users"),
            'friends': CircuitBreaker("roblox_friends"),
            'thumbnails': CircuitBreaker("roblox_thumbnails")
        }
        
    async def setup(self):
        # Create optimized connector with HTTP/2 support
        self.connector = TCPConnector(
            limit=100,
            limit_per_host=30,
            enable_cleanup_closed=True,
            force_close=False,
            ttl_dns_cache=300
        )
        
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        """Verify multiple users concurrently"""
        verified = []
        
        # Create tasks for concurrent verification
        tasks = []
        for user in users[:5]:
            cached = await self.cache.get(f"user:{user.username.lower()}")
            if cached:
                verified.append({'profile': cached, 'detected': user, 'score': user.confidence})
            else:
                tasks.append(self._fetch_and_cache_user(user))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    verified.append(result)
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_and_cache_user(self, user: DetectedUser) -> Optional[Dict]:
        try:
            profile = await self._fetch_user(user.username)
            if profile:
                await self.cache.set(f"user:{user.username.lower()}", profile, Config.CACHE_TTL_USER)
                return {'profile': profile, 'detected': user, 'score': user.confidence}
        except Exception as e:
            logger.debug(f"Fetch user error: {e}")
        return None
    
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
                
                user_id = data['data'][0]['id']
                return await self._fetch_by_id(user_id)
        except Exception as e:
            logger.debug(f"Fetch user error: {e}")
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
                
                # Get avatar concurrently
                avatar_task = self._get_avatar_url(user_id)
                profile['thumbnailUrl'] = await avatar_task
                
                return profile
        except Exception as e:
            logger.debug(f"Fetch by ID error: {e}")
            return None
    
    async def _get_avatar_url(self, user_id: int) -> Optional[str]:
        cached = await self.cache.get(f"avatar:{user_id}")
        if cached:
            return cached
        
        try:
            async with self.session.get(
                f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png',
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        url = data['data'][0].get('imageUrl')
                        if url:
                            await self.cache.set(f"avatar:{user_id}", url, Config.CACHE_TTL_THUMBNAIL)
                        return url
        except Exception as e:
            logger.debug(f"Avatar fetch error: {e}")
        return None
    
    async def get_friends(self, user_id: int) -> List[FriendInfo]:
        """Get friends with avatars - batched and optimized"""
        cached = await self.cache.get(f"friends:{user_id}")
        if cached:
            return [FriendInfo(**f) for f in cached]
        
        try:
            return await self.circuit_breakers['friends'].call(self._fetch_friends_impl, user_id)
        except Exception as e:
            logger.error(f"Get friends error: {e}")
            return []
    
    async def _fetch_friends_impl(self, user_id: int) -> List[FriendInfo]:
        # Get friends list
        async with self.session.get(
            f'https://friends.roblox.com/v1/users/{user_id}/friends',
            timeout=aiohttp.ClientTimeout(total=Config.FRIENDS_TIMEOUT)
        ) as resp:
            if resp.status != 200:
                return []
            
            data = await resp.json()
            friends_data = data.get('data', [])
            
            if not friends_data:
                return []
            
            # Get avatars in batches of 100
            friends = friends_data[:50]  # Limit to 50 for performance
            friend_ids = [str(f['id']) for f in friends]
            
            # Batch thumbnail request
            thumb_map = await self._get_batch_thumbnails(friend_ids)
            
            # Build friend info list
            friend_infos = []
            for friend in friends:
                fid = str(friend['id'])
                friend_infos.append(FriendInfo(
                    id=friend['id'],
                    username=friend['name'],
                    display_name=friend.get('displayName', friend['name']),
                    thumbnail_url=thumb_map.get(fid),
                    is_online=friend.get('isOnline', False)
                ))
            
            # Cache result
            cache_data = [{
                'id': f.id,
                'username': f.username,
                'display_name': f.display_name,
                'thumbnail_url': f.thumbnail_url,
                'is_online': f.is_online
            } for f in friend_infos]
            await self.cache.set(f"friends:{user_id}", cache_data, Config.CACHE_TTL_FRIENDS)
            
            return friend_infos
    
    async def _get_batch_thumbnails(self, user_ids: List[str]) -> Dict[str, str]:
        """Get thumbnails for multiple users in one request"""
        if not user_ids:
            return {}
        
        try:
            requests_data = [
                {
                    "requestId": f"{uid}:undefined:150x150:png:regular",
                    "type": "AvatarHeadShot",
                    "targetId": int(uid),
                    "size": "150x150",
                    "format": "png"
                }
                for uid in user_ids
            ]
            
            async with self.session.post(
                'https://thumbnails.roblox.com/v1/batch',
                json={"requests": requests_data},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    thumb_map = {}
                    for item in data.get('data', []):
                        uid = item.get('requestId', '').split(':')[0]
                        thumb_map[uid] = item.get('imageUrl')
                    return thumb_map
        except Exception as e:
            logger.debug(f"Batch thumbnails error: {e}")
        
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
# DATABASE MANAGER
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
                self.pool = await asyncpg.create_pool(
                    Config.DATABASE_URL,
                    min_size=1,
                    max_size=5,
                    command_timeout=10
                )
                await self._init_tables()
                logger.info("✅ PostgreSQL connected")
            except Exception as e:
                logger.warning(f"PostgreSQL failed: {e}")
        
        await self._load_whitelist()
    
    async def _init_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    user_id TEXT PRIMARY KEY,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id TEXT PRIMARY KEY,
                    data JSONB,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
    
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
                    await conn.execute(
                        "INSERT INTO whitelist (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                        user_id
                    )
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
                    row = await conn.fetchrow(
                        "SELECT data FROM user_stats WHERE user_id = $1",
                        user_id
                    )
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
                        ON CONFLICT (user_id) DO UPDATE SET data = $2, updated_at = NOW()
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
            
            # Remove old requests
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
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Roblox | /scan v4.0"
            )
        )
        self.tree = app_commands.CommandTree(self)
        self.db = DatabaseManager()
        self.cache = MultiTierCache()
        self.rate_limiter = RateLimiter(Config.RATE_LIMIT_PER_MINUTE, 60)
        self.ocr = None
        self.roblox = None
        self.scan_semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_SCANS)
        self._process_pool = ProcessPoolExecutor(max_workers=4)
        
    async def setup_hook(self):
        logger.info("🔧 Initializing TRUE OMEGA v4.0...")
        
        # Setup components
        await self.cache.setup()
        await self.db.setup()
        
        # Setup Roblox API
        self.roblox = RobloxAPI(self.cache)
        await self.roblox.setup()
        
        # Setup OCR
        self.ocr = OCRManager(Config.OCR_SPACE_KEY, self.roblox.session)
        await self.ocr.initialize()
        
        # Register commands
        self._register_commands()
        await self._sync_commands()
        
        logger.info("✅ TRUE OMEGA v4.0 ready!")
    
    def _register_commands(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username (v4.0)")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self._scan(interaction, image, hint)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (owner only)")
        @app_commands.describe(user="User ID to add/remove")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self._whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search user by username")
        @app_commands.describe(username="Username to search")
        async def search_cmd(interaction: discord.Interaction, username: str):
            await self._search(interaction, username)
        
        @self.tree.command(name="stats", description="📊 Your scanning stats")
        async def stats_cmd(interaction: discord.Interaction):
            await self._stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Bot status and performance")
        async def ping_cmd(interaction: discord.Interaction):
            await self._ping(interaction)
        
        @self.tree.command(name="cache", description="📈 View cache statistics (owner only)")
        async def cache_cmd(interaction: discord.Interaction):
            await self._cache_stats(interaction)
    
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
        
        # Whitelist check
        if not self.db.is_whitelisted(user_id):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⛔ Access Denied",
                    description="You are not whitelisted to use this bot.",
                    color=0xFF0000
                ),
                ephemeral=True
            )
            return
        
        # Rate limit check
        allowed, retry_after = await self.rate_limiter.check(user_id)
        if not allowed:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏰ Rate Limited",
                    description=f"Please wait {int(retry_after)} seconds before scanning again.",
                    color=0xFFA500
                ),
                ephemeral=True
            )
            return
        
        # File size check
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ File Too Large",
                    description=f"Maximum file size is {Config.MAX_FILE_SIZE / 1024 / 1024:.1f}MB",
                    color=0xFF0000
                ),
                ephemeral=True
            )
            return
        
        # Defer immediately for fast response
        await interaction.response.defer(thinking=True)
        
        async with self.scan_semaphore:
            try:
                # Download with timeout
                download_start = time.time()
                async with self.roblox.session.get(
                    image.url,
                    timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)
                ) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(
                            embed=discord.Embed(title="❌ Download Failed", color=0xFF0000)
                        )
                        return
                    img_data = await resp.read()
                download_time = time.time() - download_start
                
                # OCR with overall timeout
                ocr_task = self.ocr.scan(img_data, hint)
                result = await asyncio.wait_for(ocr_task, timeout=Config.OVERALL_TIMEOUT)
                
                if not result.success:
                    # Show debug info when no user found
                    embed = discord.Embed(
                        title="❌ No Username Found",
                        description="Could not detect a valid Roblox username in this image.",
                        color=0xFF6B6B
                    )
                    
                    # Show detected text for debugging
                    if result.raw_text:
                        clean_lines = [
                            line.strip() for line in result.raw_text.split('\n')
                            if len(line.strip()) > 2 and not line.strip().isdigit()
                        ][:15]
                        if clean_lines:
                            embed.add_field(
                                name="📝 Detected Text (Debug)",
                                value=f"```{'\n'.join(clean_lines)[:900]}```",
                                inline=False
                            )
                    
                    embed.add_field(
                        name="💡 Tips",
                        value="• Make sure @username is clearly visible\n"
                              "• Use the `hint` parameter if you know the username\n"
                              "• Ensure good lighting and focus\n"
                              "• Try cropping to just the username area",
                        inline=False
                    )
                    embed.set_footer(text=f"Engines: {', '.join(result.engines_used) or 'none'} | Time: {result.scan_time:.2f}s")
                    await interaction.followup.send(embed=embed)
                    return
                
                # Verify users
                verify_start = time.time()
                verified = await self.roblox.verify_users(result.detected_users)
                verify_time = time.time() - verify_start
                
                if not verified:
                    # Suggest similar users
                    similar = await self.roblox.search_similar(result.detected_users[0].username)
                    
                    embed = discord.Embed(
                        title="❌ User Not Found",
                        description=f"`@{result.detected_users[0].username}` doesn't exist on Roblox.",
                        color=0xFF6B6B
                    )
                    
                    if similar:
                        similar_text = '\n'.join(
                            f"• [{s.get('displayName', s['name'])} (@{s['name']})](https://roblox.com/users/{s['id']}/profile)"
                            for s in similar[:5]
                        )
                        embed.add_field(name="🔍 Did you mean?", value=similar_text, inline=False)
                    
                    await interaction.followup.send(embed=embed)
                    return
                
                # SUCCESS - Show result
                best = verified[0]
                profile = best['profile']
                detected = best['detected']
                
                embed = self._create_profile_embed(
                    profile, detected, result.scan_time, best['score'],
                    download_time, result.preprocessing_time, result.ocr_time, verify_time
                )
                embed.set_image(url=image.url)
                
                # Create interactive view
                view = ResultView(profile, self, user_id)
                
                await interaction.followup.send(embed=embed, view=view)
                
                # Update stats
                stats = await self.db.get_stats(user_id)
                stats['total_scans'] = stats.get('total_scans', 0) + 1
                stats['successful_scans'] = stats.get('successful_scans', 0) + 1
                if profile['name'] not in stats.get('favorite_users', []):
                    stats['favorite_users'] = [profile['name']] + stats.get('favorite_users', [])[:9]
                await self.db.save_stats(user_id, stats)
                
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="⏱️ Scan Timeout",
                        description="The scan took too long. Please try again with a clearer image.",
                        color=0xFFA500
                    )
                )
            except Exception as e:
                logger.error(f"Scan error: {traceback.format_exc()}")
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ Scan Error",
                        description=f"An error occurred: {str(e)[:200]}",
                        color=0xFF0000
                    )
                )
    
    def _create_profile_embed(
        self, profile: Dict, detected: DetectedUser, scan_time: float, score: float,
        download_time: float = 0, prep_time: float = 0, ocr_time: float = 0, verify_time: float = 0
    ) -> discord.Embed:
        # Color based on confidence
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
        
        # Performance breakdown
        perf_text = f"Total: `{scan_time:.2f}s`\n"
        if download_time:
            perf_text += f"↓ Download: `{download_time:.2f}s`\n"
        if prep_time:
            perf_text += f"⚙️ Prep: `{prep_time:.2f}s`\n"
        if ocr_time:
            perf_text += f"🔍 OCR: `{ocr_time:.2f}s`\n"
        if verify_time:
            perf_text += f"✓ Verify: `{verify_time:.2f}s`"
        
        embed.add_field(name="⚡ Performance", value=perf_text, inline=True)
        
        if profile.get('description'):
            desc = profile['description'][:200]
            if len(profile['description']) > 200:
                desc += "..."
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        if profile.get('thumbnailUrl'):
            embed.set_thumbnail(url=profile['thumbnailUrl'])
        
        embed.set_footer(text="TRUE OMEGA v4.0 | Click buttons below for more")
        return embed
    
    async def _whitelist(self, interaction: discord.Interaction, user: str):
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Owner Only", color=0xFF0000),
                ephemeral=True
            )
            return
        
        target = re.sub(r'[<@!>]', '', user).strip()
        if not target.isdigit():
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Invalid User ID", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        if self.db.is_whitelisted(target):
            if await self.db.remove_from_whitelist(target):
                await interaction.followup.send(
                    embed=discord.Embed(title=f"✅ Removed {target} from whitelist", color=0x00FF00)
                )
            else:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Cannot remove owner", color=0xFF0000)
                )
        else:
            if await self.db.add_to_whitelist(target):
                await interaction.followup.send(
                    embed=discord.Embed(title=f"✅ Added {target} to whitelist", color=0x00FF00)
                )
            else:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Already whitelisted", color=0xFFA500)
                )
    
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
            await interaction.followup.send(
                embed=discord.Embed(title="❌ User not found", color=0xFF0000)
            )
    
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
            embed.add_field(
                name="⭐ Recent Favorites",
                value='\n'.join(f"• @{u}" for u in favorites[:5]),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
        embed.add_field(name="Whitelisted", value=str(len(self.db._whitelist)), inline=True)
        embed.add_field(name="Cache Hit Rate", value=self.cache.get_stats()['hit_rate'], inline=True)
        embed.add_field(name="Version", value="v4.0 ULTIMATE", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _cache_stats(self, interaction: discord.Interaction):
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message("⛔ Owner only", ephemeral=True)
            return
        
        stats = self.cache.get_stats()
        embed = discord.Embed(title="📈 Cache Statistics", color=0x00D4AA)
        embed.add_field(name="Hits", value=str(stats['hits']), inline=True)
        embed.add_field(name="Misses", value=str(stats['misses']), inline=True)
        embed.add_field(name="Hit Rate", value=stats['hit_rate'], inline=True)
        embed.add_field(name="L1 Size", value=str(stats['l1_size']), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# UI COMPONENTS - ENHANCED FRIENDS FEATURE
# ═══════════════════════════════════════════════════════════
class FriendsView(discord.ui.View):
    """View for friends list with pagination"""
    
    def __init__(self, friends: List[FriendInfo], profile_name: str, bot: TrueOmegaBot, user_id: str, page: int = 0):
        super().__init__(timeout=180)
        self.friends = friends
        self.profile_name = profile_name
        self.bot = bot
        self.user_id = user_id
        self.page = page
        self.per_page = 24
        
        self._update_buttons()
    
    def _update_buttons(self):
        # Clear existing buttons except navigation
        self.clear_items()
        
        total_pages = (len(self.friends) + self.per_page - 1) // self.per_page
        
        # Previous button
        if self.page > 0:
            prev_btn = discord.ui.Button(
                label="◀ Previous",
                style=discord.ButtonStyle.secondary,
                custom_id="prev"
            )
            prev_btn.callback = self._prev_page
            self.add_item(prev_btn)
        
        # Page indicator
        page_btn = discord.ui.Button(
            label=f"Page {self.page + 1}/{total_pages}",
            style=discord.ButtonStyle.gray,
            disabled=True
        )
        self.add_item(page_btn)
        
        # Next button
        if self.page < total_pages - 1:
            next_btn = discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                custom_id="next"
            )
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
        end = start + self.per_page
        page_friends = self.friends[start:end]
        
        embed = discord.Embed(
            title=f"👥 {self.profile_name}'s Friends",
            description=f"Showing {start + 1}-{min(end, len(self.friends))} of {len(self.friends)} friends",
            color=0x00D4AA
        )
        
        # Create rows of 3 friends
        rows = []
        current_row = []
        
        for friend in page_friends:
            status_emoji = "🟢" if friend.is_online else "⚫"
            text = f"{status_emoji} [{friend.display_name}](https://roblox.com/users/{friend.id}/profile)\n`@{friend.username}`"
            current_row.append(text)
            
            if len(current_row) == 3:
                rows.append(current_row)
                current_row = []
        
        if current_row:
            rows.append(current_row)
        
        # Add fields
        for i, row in enumerate(rows):
            embed.add_field(
                name=f"Friends {start + i*3 + 1}-{min(start + (i+1)*3, len(self.friends))}",
                value='\n'.join(row) if len(row) == 3 else '\n'.join(row) + '\n\u200b',
                inline=False
            )
        
        return embed

class ResultView(discord.ui.View):
    """Main result view with action buttons"""
    
    def __init__(self, profile: Dict, bot: TrueOmegaBot, user_id: str):
        super().__init__(timeout=300)
        self.profile = profile
        self.bot = bot
        self.user_id = user_id
        
        # Profile link button
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
            
            # Create paginated friends view
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
                embed=discord.Embed(
                    title="❌ Error Loading Friends",
                    description="Could not load friends list. Please try again.",
                    color=0xFF0000
                ),
                ephemeral=True
            )
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="⭐")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        stats = await self.bot.db.get_stats(self.user_id)
        
        if self.profile['name'] in stats.get('favorite_users', []):
            await interaction.response.send_message(
                embed=discord.Embed(title="⭐ Already Saved", color=0xFFA500),
                ephemeral=True
            )
            return
        
        stats['favorite_users'] = [self.profile['name']] + stats.get('favorite_users', [])[:9]
        await self.bot.db.save_stats(self.user_id, stats)
        
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"⭐ Saved @{self.profile['name']}!",
                color=0x00FF00
            ),
            ephemeral=True
        )
    
    @discord.ui.button(label="Scan Again", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def scan_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔄 Scan Again",
                description="Use `/scan` with a new image to scan again!",
                color=0x00D4AA
            ),
            ephemeral=True
        )

# ═══════════════════════════════════════════════════════════
# HEALTH CHECK SERVER
# ═══════════════════════════════════════════════════════════
async def health_check_server():
    from aiohttp import web
    
    async def health(request):
        return web.Response(text='OK - TRUE OMEGA v4.0')
    
    async def metrics(request):
        # Simple metrics endpoint
        return web.Response(text='omega_ready 1')
    
    app = web.Application()
    app.router.add_get('/health', health)
    app.router.add_get('/metrics', metrics)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"✅ Health server running on port {port}")

# ═══════════════════════════════════════════════════════════
# MAIN ENTRY
# ═══════════════════════════════════════════════════════════
async def main():
    # Start health check server
    asyncio.create_task(health_check_server())
    
    # Create and start bot
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
            logger.error(f"Fatal error: {e}")
            logger.error(traceback.format_exc())
            time.sleep(10)
