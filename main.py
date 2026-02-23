"""
🚀 TRUE OMEGA v6.0 - HYPER SCANNER + VIDEO DOWNLOADER
Features: Parallel GPU OCR, Async Preprocessing, Smart Caching, Multi-Engine Voting
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
import subprocess
import tempfile
import concurrent.futures
from datetime import datetime
from urllib.parse import quote, urlparse
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor
from collections import Counter, defaultdict
import logging
import functools
import multiprocessing as mp

warnings.filterwarnings('ignore')

# Ultra-fast logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | \033[36m%(levelname)-8s\033[0m | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("omega")

# ═══════════════════════════════════════════════════════════
# HYPER CONFIG - MAXIMUM POWER
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # HYPER TIMEOUTS
    DOWNLOAD_TIMEOUT = 15
    OCR_TIMEOUT = 3  # Aggressive timeout
    API_TIMEOUT = 3
    VIDEO_TIMEOUT = 120
    
    MAX_FILE_SIZE = 100 * 1024 * 1024
    RATE_LIMIT = 50  # Doubled
    
    # HYPER OCR SETTINGS
    OCR_ENGINES = ['easyocr', 'tesseract', 'ocrspace', 'rapidocr']
    MAX_WORKERS = min(32, (os.cpu_count() or 4) * 4)  # Massive parallelism
    GPU_THREADS = 4
    
    # USERNAME VALIDATION
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$')
    USERNAME_CACHE_SIZE = 50000
    
    # VIDEO DOMAINS
    VIDEO_DOMAINS = [
        'medal.tv', 'streamable.com', 'youtube.com', 'youtu.be',
        'twitter.com', 'x.com', 'reddit.com', 'tiktok.com',
        'instagram.com', 'facebook.com', 'twitch.tv'
    ]

Config.validate = lambda: logger.info(f"✅ Config loaded | Owner: {Config.OWNER_ID} | Workers: {Config.MAX_WORKERS}") or None if Config.TOKEN else logger.error("❌ No DISCORD_TOKEN") or sys.exit(1)
Config.validate()

# ═══════════════════════════════════════════════════════════
# HYPER IMPORTS
# ═══════════════════════════════════════════════════════════
import aiohttp
from aiohttp import TCPConnector, FormData
import discord
from discord import app_commands

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    from pytesseract import Output
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
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import asyncpg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Try RapidOCR for speed
try:
    from rapidocr_onnxruntime import RapidOCR
    RAPIDOCR_AVAILABLE = True
except ImportError:
    RAPIDOCR_AVAILABLE = False

logger.info(f"🔧 PIL={PIL_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}, CV2={CV2_AVAILABLE}, RapidOCR={RAPIDOCR_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# HYPER CACHE - LOCK-FREE DESIGN
# ═══════════════════════════════════════════════════════════
class HyperCache:
    """Ultra-fast cache with TTL and LRU eviction"""
    def __init__(self, maxsize=50000):
        self._cache = {}
        self._expiry = {}
        self._access_time = {}
        self.maxsize = maxsize
        self._lock = asyncio.Lock()
        self.redis = None
        self._hits = 0
        self._misses = 0
        self._local_ttl = 600  # 10 minutes local
        
    async def setup(self):
        if REDIS_AVAILABLE and Config.REDIS_URL:
            try:
                self.redis = await redis.from_url(Config.REDIS_URL, decode_responses=True)
                await self.redis.ping()
                logger.info("✅ Redis connected")
            except Exception as e:
                logger.warning(f"Redis: {e}")
    
    async def get(self, key: str):
        now = time.time()
        
        # Fast path - no lock
        if key in self._cache:
            if now < self._expiry.get(key, 0):
                self._access_time[key] = now
                self._hits += 1
                return self._cache[key]
        
        # Slow path - check Redis
        if self.redis:
            try:
                data = await self.redis.get(f"o:{key}")
                if data:
                    val = json.loads(data)
                    # Populate local cache
                    self._cache[key] = val
                    self._expiry[key] = now + self._local_ttl
                    self._access_time[key] = now
                    self._hits += 1
                    return val
            except:
                pass
        
        self._misses += 1
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        now = time.time()
        
        # Update local cache
        self._cache[key] = value
        self._expiry[key] = now + min(ttl, self._local_ttl)
        self._access_time[key] = now
        
        # Evict if needed (async cleanup)
        if len(self._cache) > self.maxsize:
            asyncio.create_task(self._evict_oldest())
        
        # Update Redis in background
        if self.redis:
            try:
                await self.redis.setex(f"o:{key}", ttl, json.dumps(value))
            except:
                pass
    
    async def _evict_oldest(self):
        """Evict oldest 10% of entries"""
        if len(self._cache) <= self.maxsize:
            return
        
        # Sort by access time and remove oldest 10%
        sorted_items = sorted(self._access_time.items(), key=lambda x: x[1])
        to_remove = int(len(sorted_items) * 0.1)
        
        for key, _ in sorted_items[:to_remove]:
            self._cache.pop(key, None)
            self._expiry.pop(key, None)
            self._access_time.pop(key, None)
    
    def stats(self):
        total = self._hits + self._misses
        rate = (self._hits / total * 100) if total > 0 else 0
        return f"Cache: {self._hits} hits, {self._misses} misses ({rate:.1f}%) | Size: {len(self._cache)}"

# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════
@dataclass
class DetectedUser:
    username: str
    display_name: Optional[str]
    confidence: float
    source: str
    engine: str = "unknown"
    raw_text: str = ""
    bbox: Optional[Tuple] = None  # Bounding box for precise location

@dataclass
class OCRResult:
    text: str
    engine: str
    confidence: float
    processing_time: float
    detections: List[Dict] = field(default_factory=list)  # Detailed detections

@dataclass
class VideoInfo:
    url: str
    title: str
    duration: str
    uploader: str
    thumbnail: Optional[str]
    filesize: Optional[int]

# ═══════════════════════════════════════════════════════════
# HYPER IMAGE PREPROCESSOR - PARALLEL GPU PIPELINE
# ═══════════════════════════════════════════════════════════
class HyperPreprocessor:
    """Massively parallel image preprocessing with GPU acceleration"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        self.process_pool = ProcessPoolExecutor(max_workers=4)
        
    async def preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        if not CV2_AVAILABLE or not PIL_AVAILABLE:
            return [(image_data, "original", {})]
        
        loop = asyncio.get_event_loop()
        
        # Run preprocessing in thread pool for I/O, then process pool for CPU
        return await loop.run_in_executor(
            self.executor,
            self._parallel_preprocess,
            image_data
        )
    
    def _parallel_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Generate multiple preprocessed versions in parallel"""
        versions = []
        
        # Decode once
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return self._pil_preprocess(image_data)
        
        h, w = img.shape[:2]
        
        # Use ThreadPoolExecutor for parallel preprocessing
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = []
            
            # Submit all transformations
            futures.append(pool.submit(self._version_original, img.copy()))
            futures.append(pool.submit(self._version_grayscale_clahe, img.copy()))
            futures.append(pool.submit(self._version_denoised, img.copy()))
            futures.append(pool.submit(self._version_sharpened, img.copy()))
            futures.append(pool.submit(self._version_binary, img.copy()))
            
            if w < 1000:
                futures.append(pool.submit(self._version_upscaled, img.copy()))
            
            futures.append(pool.submit(self._version_contrast, img.copy()))
            futures.append(pool.submit(self._version_adaptive_threshold, img.copy()))
            
            # Collect results
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        versions.append(result)
                except Exception as e:
                    logger.debug(f"Preprocessing variant failed: {e}")
        
        # Sort by priority
        priority = {
            "original": 0, "grayscale_clahe": 1, "upscaled": 2,
            "sharpened": 3, "denoised": 4, "contrast": 5,
            "binary": 6, "adaptive": 7
        }
        versions.sort(key=lambda x: priority.get(x[1], 99))
        
        return versions[:6]  # Return top 6 variants
    
    def _version_original(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        _, buf = cv2.imencode('.png', img)
        return (buf.tobytes(), "original", {"size": img.shape[:2]})
    
    def _version_grayscale_clahe(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        _, buf = cv2.imencode('.png', enhanced)
        return (buf.tobytes(), "grayscale_clahe", {"size": enhanced.shape})
    
    def _version_denoised(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        _, buf = cv2.imencode('.png', denoised)
        return (buf.tobytes(), "denoised", {"size": denoised.shape})
    
    def _version_sharpened(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(img, -1, kernel)
        _, buf = cv2.imencode('.png', sharpened)
        return (buf.tobytes(), "sharpened", {"size": sharpened.shape[:2]})
    
    def _version_binary(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, buf = cv2.imencode('.png', binary)
        return (buf.tobytes(), "binary", {"size": binary.shape})
    
    def _version_upscaled(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        h, w = img.shape[:2]
        scaled = cv2.resize(img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
        _, buf = cv2.imencode('.png', scaled)
        return (buf.tobytes(), "upscaled", {"size": scaled.shape[:2]})
    
    def _version_contrast(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        _, buf = cv2.imencode('.png', enhanced)
        return (buf.tobytes(), "contrast", {"size": enhanced.shape[:2]})
    
    def _version_adaptive_threshold(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                         cv2.THRESH_BINARY, 11, 2)
        _, buf = cv2.imencode('.png', adaptive)
        return (buf.tobytes(), "adaptive", {"size": adaptive.shape})
    
    def _pil_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Fallback PIL preprocessing"""
        img = Image.open(io.BytesIO(image_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        versions = []
        
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        versions.append((buf.getvalue(), "original", {}))
        
        # Contrast
        enhanced = ImageEnhance.Contrast(img).enhance(2.5)
        buf = io.BytesIO()
        enhanced.save(buf, format='PNG')
        versions.append((buf.getvalue(), "contrast", {}))
        
        # Sharpen
        sharpened = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        buf = io.BytesIO()
        sharpened.save(buf, format='PNG')
        versions.append((buf.getvalue(), "sharpened", {}))
        
        return versions

# ═══════════════════════════════════════════════════════════
# HYPER OCR ENGINE - PARALLEL MULTI-ENGINE
# ═══════════════════════════════════════════════════════════
class HyperOCR:
    """Ultra-fast parallel OCR with multiple engines"""
    
    def __init__(self, cache: HyperCache):
        self.easyocr_reader = None
        self.easy_ready = False
        self.rapidocr = None
        self.rapid_ready = False
        self.preprocessor = HyperPreprocessor()
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        self.cache = cache
        self.ocr_space_available = bool(Config.OCR_SPACE_KEY)
        self._username_patterns = self._compile_patterns()
        
    def _compile_patterns(self) -> Dict[str, re.Pattern]:
        """Pre-compile all regex patterns for speed"""
        return {
            'mention': re.compile(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'display_user': re.compile(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠]\s*([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'roblox_url': re.compile(r'roblox\.com/users/(\d+)', re.I),
            'username': re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'display_name_only': re.compile(r'Display\s*Name\s*:?\s*([A-Za-z][A-Za-z0-9_\s]{2,20})', re.I),
            'username_label': re.compile(r'[@＠]?\s*([a-zA-Z][a-zA-Z0-9_]{2,19})\s*\(?(?:@|username|user)\)?', re.I),
        }
        
    async def init_engines(self):
        """Initialize all OCR engines in parallel"""
        init_tasks = []
        
        if EASYOCR_AVAILABLE:
            init_tasks.append(self._init_easyocr())
        
        if RAPIDOCR_AVAILABLE:
            init_tasks.append(self._init_rapidocr())
        
        await asyncio.gather(*init_tasks, return_exceptions=True)
        logger.info(f"✅ OCR Engines: EasyOCR={self.easy_ready}, RapidOCR={self.rapid_ready}")
    
    async def _init_easyocr(self):
        try:
            loop = asyncio.get_event_loop()
            try:
                self.easyocr_reader = await loop.run_in_executor(
                    None, lambda: easyocr.Reader(['en'], gpu=True, verbose=False)
                )
                logger.info("✅ EasyOCR GPU ready")
            except:
                self.easyocr_reader = await loop.run_in_executor(
                    None, lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
                )
                logger.info("✅ EasyOCR CPU ready")
            self.easy_ready = True
        except Exception as e:
            logger.error(f"EasyOCR init: {e}")
    
    async def _init_rapidocr(self):
        try:
            loop = asyncio.get_event_loop()
            self.rapidocr = await loop.run_in_executor(
                None, lambda: RapidOCR()
            )
            self.rapid_ready = True
            logger.info("✅ RapidOCR ready")
        except Exception as e:
            logger.error(f"RapidOCR init: {e}")
    
    async def scan(self, image_data: bytes, hint: str = None) -> Tuple[bool, List[DetectedUser], str, Dict]:
        """Hyper-fast parallel scan"""
        start_time = time.time()
        
        # Check cache first
        cache_key = hashlib.md5(image_data).hexdigest()
        cached = await self.cache.get(f"ocr:{cache_key}")
        if cached:
            users = [DetectedUser(**u) for u in cached.get('users', [])]
            return len(users) > 0, users, cached.get('text', ''), {"cached": True, "time": 0}
        
        # Parallel preprocessing and OCR
        versions = await self.preprocessor.preprocess(image_data)
        
        # Run all OCR engines in parallel with timeout
        ocr_tasks = []
        
        # EasyOCR on best 3 variants
        if self.easy_ready:
            for img, name, _ in versions[:3]:
                ocr_tasks.append(self._run_with_timeout(
                    self._run_easyocr(img, name), Config.OCR_TIMEOUT
                ))
        
        # RapidOCR on original (fastest)
        if self.rapid_ready:
            ocr_tasks.append(self._run_with_timeout(
                self._run_rapidocr(versions[0][0]), Config.OCR_TIMEOUT
            ))
        
        # Tesseract on all variants
        if TESSERACT_AVAILABLE:
            for img, name, _ in versions:
                ocr_tasks.append(self._run_with_timeout(
                    self._run_tesseract(img, name), Config.OCR_TIMEOUT
                ))
        
        # OCR.space as backup
        if self.ocr_space_available:
            ocr_tasks.append(self._run_with_timeout(
                self._run_ocrspace(image_data), Config.OCR_TIMEOUT + 2
            ))
        
        # Gather all results
        results = await asyncio.gather(*ocr_tasks, return_exceptions=True)
        results = [r for r in results if isinstance(r, OCRResult) and r.text.strip()]
        
        if not results:
            return False, [], "", {"error": "All OCR engines failed", "time": time.time() - start_time}
        
        # Parallel user extraction
        extraction_tasks = []
        for result in results:
            extraction_tasks.append(self._extract_users_parallel(result, hint))
        
        user_lists = await asyncio.gather(*extraction_tasks)
        all_users = [u for sublist in user_lists for u in sublist]
        
        # Smart voting
        voted_users = self._smart_vote(all_users, hint)
        
        # Cache results
        if voted_users:
            await self.cache.set(f"ocr:{cache_key}", {
                'users': [{'username': u.username, 'display_name': u.display_name, 
                          'confidence': u.confidence, 'source': u.source, 
                          'engine': u.engine, 'raw_text': u.raw_text} for u in voted_users],
                'text': '\n'.join(r.text for r in results)
            }, 3600)
        
        total_time = time.time() - start_time
        
        metadata = {
            "engines_used": list(set(r.engine for r in results)),
            "versions_processed": len(versions),
            "processing_time": total_time,
            "raw_results": len(results),
            "users_found": len(voted_users)
        }
        
        return len(voted_users) > 0, voted_users, '\n'.join(r.text for r in results), metadata
    
    async def _run_with_timeout(self, coro, timeout):
        """Run coroutine with timeout"""
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.debug(f"OCR task failed: {e}")
            return None
    
    async def _run_easyocr(self, image_data: bytes, version_name: str) -> OCRResult:
        start = time.time()
        
        def _run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, paragraph=False, detail=1)
            
            texts = []
            detections = []
            confs = []
            
            for r in results:
                bbox, text, conf = r
                texts.append(text)
                detections.append({"text": text, "conf": conf, "bbox": bbox})
                confs.append(conf)
            
            full_text = ' '.join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0
            return full_text, avg_conf, detections
        
        loop = asyncio.get_event_loop()
        text, conf, dets = await loop.run_in_executor(self.executor, _run)
        
        return OCRResult(text, f"easyocr_{version_name}", conf, time.time() - start, dets)
    
    async def _run_rapidocr(self, image_data: bytes) -> OCRResult:
        """RapidOCR - fastest engine"""
        start = time.time()
        
        def _run():
            result = self.rapidocr(image_data)
            texts = []
            confs = []
            dets = []
            
            if result and result[0]:
                for line in result[0]:
                    bbox, text, conf = line
                    texts.append(text)
                    confs.append(conf)
                    dets.append({"text": text, "conf": conf, "bbox": bbox})
            
            full_text = ' '.join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0
            return full_text, avg_conf, dets
        
        loop = asyncio.get_event_loop()
        text, conf, dets = await loop.run_in_executor(self.executor, _run)
        
        return OCRResult(text, "rapidocr", conf, time.time() - start, dets)
    
    async def _run_tesseract(self, image_data: bytes, version_name: str) -> OCRResult:
        start = time.time()
        
        def _run():
            img = Image.open(io.BytesIO(image_data))
            
            # Optimize for username detection
            config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@ '
            text = pytesseract.image_to_string(img, config=config)
            
            # Get confidence data
            data = pytesseract.image_to_data(img, config=config, output_type=Output.DICT)
            confs = [int(c) for c in data['conf'] if int(c) > 0]
            avg_conf = sum(confs) / len(confs) / 100 if confs else 0.5
            
            return text, avg_conf, []
        
        loop = asyncio.get_event_loop()
        text, conf, dets = await loop.run_in_executor(self.executor, _run)
        
        return OCRResult(text, f"tesseract_{version_name}", conf, time.time() - start, dets)
    
    async def _run_ocrspace(self, image_data: bytes) -> OCRResult:
        start = time.time()
        
        try:
            data = FormData()
            data.add_field('file', image_data, filename='image.png', content_type='image/png')
            data.add_field('apikey', Config.OCR_SPACE_KEY)
            data.add_field('OCREngine', '2')
            data.add_field('scale', 'true')
            data.add_field('detectOrientation', 'true')
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.ocr.space/parse/image',
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ParsedResults'):
                            text = result['ParsedResults'][0].get('ParsedText', '')
                            conf = float(result['ParsedResults'][0].get('FileParseExitCode', 0)) / 100
                            return OCRResult(text, "ocrspace", conf, time.time() - start, [])
        except Exception as e:
            logger.debug(f"OCR.space error: {e}")
        
        return OCRResult("", "ocrspace", 0, time.time() - start, [])
    
    async def _extract_users_parallel(self, result: OCRResult, hint: str) -> List[DetectedUser]:
        """Extract users from OCR result"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._extract_users_sync,
            result,
            hint
        )
    
    def _extract_users_sync(self, result: OCRResult, hint: str) -> List[DetectedUser]:
        """Synchronous user extraction with all patterns"""
        text = result.text
        users = []
        lines = text.split('\n')
        lower_text = text.lower()
        
        # Pattern 1: @username (highest confidence)
        for m in self._username_patterns['mention'].finditer(text):
            u = m.group(1)
            if self._validate_username(u):
                conf = 0.98
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                users.append(DetectedUser(u, None, conf, '@mention', result.engine, 
                                        text[m.start():m.end()], getattr(m, 'bbox', None)))
        
        # Pattern 2: Display Name @username
        for m in self._username_patterns['display_user'].finditer(text):
            d, u = m.groups()
            d = d.strip()
            if self._validate_username(u) and len(d) > 2:
                users.append(DetectedUser(u, d, 0.97, 'display@user', result.engine,
                                        text[m.start():m.end()]))
        
        # Pattern 3: Roblox URL
        for m in self._username_patterns['roblox_url'].finditer(text):
            uid = m.group(1)
            users.append(DetectedUser(f"ID:{uid}", None, 0.99, 'url', result.engine,
                                    text[m.start():m.end()]))
        
        # Pattern 4: Contextual detection with ML-like scoring
        context_words = ['roblox', 'profile', 'user', 'display', 'name', '@', 'username']
        has_context = any(w in lower_text for w in context_words)
        
        for i, line in enumerate(lines):
            line_lower = line.lower()
            line_has_context = has_context or any(w in line_lower for w in context_words)
            
            for m in self._username_patterns['username'].finditer(line):
                u = m.group(1)
                if not self._validate_username(u):
                    continue
                
                # Skip common false positives
                if u.lower() in {'roblox', 'profile', 'username', 'display', 'user', 
                                'avatar', 'friends', 'home', 'settings', 'catalog',
                                'inventory', 'trades', 'groups', 'messages'}:
                    continue
                
                # Calculate confidence based on context
                conf = 0.6 if line_has_context else 0.4
                
                # Boost if near context words
                surrounding = ' '.join(lines[max(0,i-2):min(len(lines), i+3)]).lower()
                context_boost = sum(1 for w in context_words if w in surrounding) * 0.05
                conf = min(conf + context_boost, 0.90)
                
                # Boost if matches hint
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                
                # Boost if capitalized properly (likely a name)
                if u[0].isupper() and not u.isupper():
                    conf += 0.05
                
                users.append(DetectedUser(u, None, min(conf, 0.95), 'context', result.engine, line))
        
        # Pattern 5: Display Name labels
        for m in self._username_patterns['display_name_only'].finditer(text):
            d = m.group(1).strip()
            if len(d) > 2:
                # Try to find associated username nearby
                nearby = text[max(0, m.start()-100):min(len(text), m.end()+100)]
                for um in self._username_patterns['username'].finditer(nearby):
                    u = um.group(1)
                    if self._validate_username(u) and u.lower() not in {'roblox', 'profile'}:
                        users.append(DetectedUser(u, d, 0.93, 'display_label', result.engine,
                                                text[m.start():m.end()]))
                        break
        
        return users
    
    def _validate_username(self, username: str) -> bool:
        if not username:
            return False
        return bool(Config.USERNAME_REGEX.match(username))
    
    def _smart_vote(self, users: List[DetectedUser], hint: str) -> List[DetectedUser]:
        """Intelligent voting with hint boosting and engine diversity"""
        if not users:
            return []
        
        # Group by username
        groups = defaultdict(list)
        for u in users:
            key = u.username.lower()
            groups[key].append(u)
        
        voted = []
        for username, group in groups.items():
            # Engine diversity bonus
            engines = set(u.engine.split('_')[0] for u in group)
            engine_diversity = len(engines)
            
            # Best confidence
            best = max(group, key=lambda x: x.confidence)
            
            # Hint match bonus
            hint_boost = 0.15 if (hint and username == hint.lower().lstrip('@')) else 0
            
            # Source quality bonus
            source_bonus = 0.1 if best.source in {'@mention', 'display@user', 'url'} else 0
            
            # Calculate final confidence
            final_conf = min(best.confidence + (engine_diversity - 1) * 0.03 + hint_boost + source_bonus, 1.0)
            
            # Get best display name
            display_names = [u.display_name for u in group if u.display_name]
            best_display = display_names[0] if display_names else best.display_name
            
            voted.append(DetectedUser(
                username=best.username,
                display_name=best_display,
                confidence=final_conf,
                source=f"{best.source}_voted",
                engine=f"ensemble_{engine_diversity}",
                raw_text=best.raw_text[:100]
            ))
        
        # Sort by confidence
        voted.sort(key=lambda x: x.confidence, reverse=True)
        
        # Deduplicate similar usernames (levenshtein-like)
        filtered = []
        for u in voted:
            if not any(self._similar_names(u.username, f.username) for f in filtered):
                filtered.append(u)
        
        return filtered[:5]  # Return top 5
    
    def _similar_names(self, a: str, b: str) -> bool:
        """Check if two usernames are similar (simple edit distance)"""
        if a.lower() == b.lower():
            return True
        # Simple check: one is substring of other or differ by 1 char
        a_lower, b_lower = a.lower(), b.lower()
        if len(a_lower) > 3 and len(b_lower) > 3:
            if a_lower in b_lower or b_lower in a_lower:
                return True
            # Check edit distance for short names
            if abs(len(a) - len(b)) <= 1:
                diff = sum(c1 != c2 for c1, c2 in zip(a_lower, b_lower))
                if diff <= 1:
                    return True
        return False

# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.download_path = "downloads/videos"
        os.makedirs(self.download_path, exist_ok=True)
    
    def _format_duration(self, seconds: Optional[Union[int, float]]) -> str:
        if not seconds:
            return "Unknown"
        try:
            seconds = int(float(seconds))
        except (ValueError, TypeError):
            return "Unknown"
        
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
    
    async def download(self, url: str) -> Tuple[bool, str, Optional[str], Optional[VideoInfo]]:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')
        
        if not any(d in domain for d in Config.VIDEO_DOMAINS):
            return False, f"Unsupported domain", None, None
        
        video_id = hashlib.md5(url.encode()).hexdigest()[:8]
        output_path = os.path.join(self.download_path, f"{video_id}.mp4")
        
        if os.path.exists(output_path):
            return True, "Cached", output_path, None
        
        loop = asyncio.get_event_loop()
        success, message, info = await loop.run_in_executor(
            self.executor,
            self._run_yt_dlp,
            url, output_path
        )
        
        return (success, message, output_path if success else None, info)
    
    def _run_yt_dlp(self, url: str, output_path: str) -> Tuple[bool, str, Optional[VideoInfo]]:
        try:
            # Get info
            info_cmd = ['yt-dlp', '--dump-json', '--no-download', url]
            result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=20)
            
            if result.returncode != 0:
                return False, f"Info failed: {result.stderr}", None
            
            info = json.loads(result.stdout.strip().split('\n')[0])
            video_info = VideoInfo(
                url=url,
                title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            # Download
            download_cmd = [
                'yt-dlp', '-f', 'best[ext=mp4]/best', '--merge-output-format', 'mp4',
                '-o', output_path, '--no-playlist', '--newline', url
            ]
            result = subprocess.run(download_cmd, capture_output=True, text=True, timeout=Config.VIDEO_TIMEOUT)
            
            if result.returncode != 0:
                return False, f"Download failed: {result.stderr}", video_info
            
            return os.path.exists(output_path), "Success" if os.path.exists(output_path) else "Not found", video_info
            
        except Exception as e:
            return False, str(e), None
    
    async def get_info(self, url: str) -> Tuple[bool, Optional[VideoInfo]]:
        try:
            cmd = ['yt-dlp', '--dump-json', '--no-download', url]
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            )
            
            if result.returncode != 0:
                return False, None
            
            info = json.loads(result.stdout.strip().split('\n')[0])
            return True, VideoInfo(
                url=url, title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
        except Exception as e:
            logger.error(f"Get info error: {e}")
            return False, None

# ═══════════════════════════════════════════════════════════
# HYPER ROBLOX API - ASYNC CONNECTION POOL
# ═══════════════════════════════════════════════════════════
class HyperRobloxAPI:
    def __init__(self, cache: HyperCache):
        self.cache = cache
        self.session = None
        self.semaphore = asyncio.Semaphore(20)  # Limit concurrent requests
        
    async def setup(self):
        connector = TCPConnector(limit=200, limit_per_host=50, enable_cleanup_closed=True, force_close=True)
        timeout = aiohttp.ClientTimeout(total=Config.API_TIMEOUT, connect=2)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate"
            }
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        """Verify multiple users in parallel"""
        if not users:
            return []
        
        # Check cache first (fast path)
        to_fetch = []
        verified = []
        
        for user in users[:8]:  # Check top 8
            cached = await self.cache.get(f"u:{user.username.lower()}")
            if cached:
                verified.append({
                    'profile': cached,
                    'detected': user,
                    'score': user.confidence,
                    'cached': True
                })
            else:
                to_fetch.append(user)
        
        # Fetch remaining in parallel
        if to_fetch:
            fetch_tasks = [self._fetch_user_with_retry(u) for u in to_fetch]
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            
            for user, result in zip(to_fetch, fetch_results):
                if isinstance(result, dict):
                    await self.cache.set(f"u:{user.username.lower()}", result, 900)
                    verified.append({
                        'profile': result,
                        'detected': user,
                        'score': user.confidence,
                        'cached': False
                    })
        
        # Sort by confidence score
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user_with_retry(self, user: DetectedUser, retries: int = 2) -> Optional[Dict]:
        """Fetch with retry logic"""
        for attempt in range(retries):
            try:
                async with self.semaphore:
                    if user.username.startswith("ID:"):
                        return await self._fetch_by_id(int(user.username.split(":")[1]))
                    
                    # Bulk username lookup
                    async with self.session.post(
                        'https://users.roblox.com/v1/usernames/users',
                        json={"usernames": [user.username], "excludeBannedUsers": False},
                        ssl=False
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('data'):
                                return await self._fetch_by_id(data['data'][0]['id'])
                        elif resp.status == 429:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(0.3)
                continue
        return None
    
    async def _fetch_by_id(self, user_id: int) -> Optional[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/{user_id}',
                ssl=False
            ) as resp:
                if resp.status == 200:
                    profile = await resp.json()
                    # Fetch avatar in parallel
                    avatar_task = asyncio.create_task(self._get_avatar(user_id))
                    profile['thumbnailUrl'] = await avatar_task
                    return profile
        except Exception as e:
            logger.debug(f"Fetch by ID error: {e}")
        return None
    
    async def _get_avatar(self, user_id: int) -> Optional[str]:
        cached = await self.cache.get(f"a:{user_id}")
        if cached:
            return cached
        
        try:
            async with self.session.get(
                f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png',
                ssl=False
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        url = data['data'][0].get('imageUrl')
                        if url:
                            await self.cache.set(f"a:{user_id}", url, 3600)
                        return url
        except:
            pass
        return None
    
    async def search_similar(self, username: str) -> List[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5',
                ssl=False
            ) as resp:
                if resp.status == 200:
                    return (await resp.json()).get('data', [])
        except:
            pass
        return []

# ═══════════════════════════════════════════════════════════
# WEBHOOK MANAGER
# ═══════════════════════════════════════════════════════════
class WebhookManager:
    def __init__(self):
        self.url = Config.WEBHOOK_URL
        self.session = None
    
    async def setup(self):
        if self.url:
            self.session = aiohttp.ClientSession()
    
    async def send_scan_result(self, user: discord.User, profile: Dict, detected: DetectedUser, 
                              image_url: str, processing_time: float, meta: Dict):
        if not self.url or not self.session:
            return
        
        try:
            color = 0x00FF00 if detected.confidence >= 0.95 else \
                   0x55FF55 if detected.confidence >= 0.80 else \
                   0xFFAA00 if detected.confidence >= 0.60 else 0xFF5555
            
            embed = {
                "title": f"🔍 {profile.get('displayName', profile['name'])}",
                "description": f"**@{profile['name']}** • `{detected.confidence:.0%}` confidence",
                "url": f"https://roblox.com/users/{profile['id']}/profile",
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "thumbnail": {"url": profile.get('thumbnailUrl', '')},
                "image": {"url": image_url},
                "author": {
                    "name": f"Scanned by {user.name}",
                    "icon_url": str(user.display_avatar.url) if user.display_avatar else None
                },
                "fields": [
                    {"name": "🆔 User ID", "value": f"`{profile['id']}`", "inline": True},
                    {"name": "📊 Confidence", "value": f"`{detected.confidence:.0%}`", "inline": True},
                    {"name": "🔎 Source", "value": f"`{detected.source}`", "inline": True},
                    {"name": "⚡ Speed", "value": f"`{processing_time:.2f}s`", "inline": True},
                    {"name": "🤖 Engine", "value": f"`{detected.engine}`", "inline": True},
                    {"name": "🧠 OCR Engines", "value": f"`{len(meta.get('engines_used', []))}`", "inline": True}
                ],
                "footer": {
                    "text": "TRUE OMEGA v6.0 HYPER SCANNER",
                    "icon_url": "https://i.imgur.com/4M34hi2.png"
                }
            }
            
            await self.session.post(self.url, json={"embeds": [embed]})
        except Exception as e:
            logger.error(f"Webhook error: {e}")

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
class Database:
    def __init__(self):
        self.pool = None
        self.whitelist: Set[str] = set()
        os.makedirs("data", exist_ok=True)
        os.makedirs("downloads/videos", exist_ok=True)
        
    async def setup(self):
        if DB_AVAILABLE and Config.DATABASE_URL:
            try:
                self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=2, max_size=10)
            except Exception as e:
                logger.warning(f"DB: {e}")
        
        self.whitelist = {Config.OWNER_ID}
        try:
            if os.path.exists("data/whitelist.json"):
                with open("data/whitelist.json") as f:
                    self.whitelist.update(str(u) for u in json.load(f).get('users', []))
        except:
            pass
    
    def is_whitelisted(self, uid: str) -> bool:
        return str(uid) in self.whitelist
    
    async def get_stats(self, uid: str) -> Dict:
        try:
            path = f"data/{uid}.json"
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        except:
            pass
        return {'total': 0, 'success': 0, 'favorites': [], 'videos_downloaded': 0}
    
    async def save_stats(self, uid: str, data: Dict):
        try:
            with open(f"data/{uid}.json", 'w') as f:
                json.dump(data, f)
        except:
            pass

# ═══════════════════════════════════════════════════════════
# HYPER BOT
# ═══════════════════════════════════════════════════════════
class OmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan | /download")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.cache = HyperCache()
        self.limiter = RateLimiter(Config.RATE_LIMIT, 60)
        self.video_limiter = RateLimiter(10, 60)
        self.ocr = HyperOCR(self.cache)
        self.roblox = None
        self.video_downloader = VideoDownloader()
        self.webhook = WebhookManager()
        
    async def setup_hook(self):
        logger.info("🔧 Starting HYPER OMEGA v6.0...")
        await self.cache.setup()
        await self.db.setup()
        await self.webhook.setup()
        self.roblox = HyperRobloxAPI(self.cache)
        await self.roblox.setup()
        await self.ocr.init_engines()
        self._register_cmds()
        await self._sync()
        logger.info("✅ HYPER OMEGA v6.0 Ready!")
    
    def _register_cmds(self):
        @self.tree.command(name="scan", description="🔍 HYPER SCAN - Ultra-fast Roblox username detection")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download video")
        @app_commands.describe(url="Video URL", info_only="Show info only")
        async def download(interaction: discord.Interaction, url: str, info_only: bool = False):
            await self.cmd_download(interaction, url, info_only)
        
        @self.tree.command(name="stats", description="📊 View statistics")
        async def stats(interaction: discord.Interaction):
            await self.cmd_stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Check latency")
        async def ping(interaction: discord.Interaction):
            await self.cmd_ping(interaction)
    
    async def _sync(self):
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Sync: {e}")
    
    async def cmd_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        """HYPER SCAN - Maximum speed and accuracy"""
        uid = str(interaction.user.id)
        start_time = time.time()
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        allowed, retry = await self.limiter.check(uid)
        if not allowed:
            await interaction.response.send_message(f"⏰ Rate limited: {int(retry)}s", ephemeral=True)
            return
        
        # Quick size check
        if image.size > 8 * 1024 * 1024:  # 8MB for speed
            await interaction.response.send_message("❌ Image too large (max 8MB)", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Parallel download and preprocessing
            async with self.roblox.session.get(image.url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Download failed")
                    return
                img_data = await resp.read()
            
            # HYPER SCAN
            success, users, raw_text, meta = await self.ocr.scan(img_data, hint)
            
            if not success:
                embed = discord.Embed(
                    title="❌ No Username Found",
                    description="Could not detect any valid Roblox username.",
                    color=0xFF6B6B
                )
                embed.add_field(name="⚡ Speed", value=f"`{time.time() - start_time:.2f}s`", inline=True)
                await interaction.followup.send(embed=embed)
                return
            
            # Parallel verification
            verified = await self.roblox.verify_users(users)
            
            if not verified:
                embed = discord.Embed(
                    title="❌ User Not Found",
                    description=f"Detected `@{users[0].username}` but not found on Roblox.",
                    color=0xFF6B6B
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Display best result
            best = verified[0]
            prof = best['profile']
            det = best['detected']
            total_time = time.time() - start_time
            
            # Color based on confidence
            color = 0x00FF00 if det.confidence >= 0.95 else \
                   0x55FF55 if det.confidence >= 0.80 else \
                   0xFFAA00 if det.confidence >= 0.60 else 0xFF5555
            
            embed = discord.Embed(
                title=f"{prof.get('displayName', prof['name'])}",
                url=f"https://roblox.com/users/{prof['id']}/profile",
                description=f"**@{prof['name']}** • `{det.confidence:.0%}` confidence",
                color=color,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="🎯 Confidence", value=f"`{det.confidence:.0%}`", inline=True)
            embed.add_field(name="🔍 Source", value=f"`{det.source}`", inline=True)
            embed.add_field(name="🤖 Engine", value=f"`{det.engine}`", inline=True)
            embed.add_field(name="🆔 User ID", value=f"`{prof['id']}`", inline=True)
            embed.add_field(name="⚡ Speed", value=f"`{total_time:.2f}s`", inline=True)
            embed.add_field(name="🧠 OCR Engines", value=f"`{len(meta.get('engines_used', []))}`", inline=True)
            
            if prof.get('thumbnailUrl'):
                embed.set_thumbnail(url=prof['thumbnailUrl'])
            embed.set_image(url=image.url)
            embed.set_footer(text="TRUE OMEGA v6.0 HYPER SCANNER")
            
            await interaction.followup.send(embed=embed)
            
            # Background tasks
            asyncio.create_task(self.webhook.send_scan_result(
                interaction.user, prof, det, image.url, total_time, meta
            ))
            
            # Update stats
            stats = await self.db.get_stats(uid)
            stats['total'] = stats.get('total', 0) + 1
            stats['success'] = stats.get('success', 0) + 1
            await self.db.save_stats(uid, stats)
            
        except Exception as e:
            logger.error(f"Scan error: {traceback.format_exc()}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
            )
    
    async def cmd_download(self, interaction: discord.Interaction, url: str, info_only: bool):
        uid = str(interaction.user.id)
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            if info_only:
                success, info = await self.video_downloader.get_info(url)
                if not success:
                    await interaction.followup.send("❌ Failed to get info")
                    return
                
                embed = discord.Embed(
                    title=f"📹 {info.title[:100]}",
                    description=f"**{info.uploader}** • {info.duration}",
                    color=0x00D4AA
                )
                await interaction.followup.send(embed=embed)
            else:
                success, message, file_path, info = await self.video_downloader.download(url)
                
                if not success or not file_path:
                    await interaction.followup.send(f"❌ {message}")
                    return
                
                file_size = os.path.getsize(file_path)
                if file_size > Config.MAX_FILE_SIZE:
                    await interaction.followup.send("❌ File too large")
                    return
                
                file = discord.File(file_path, filename=os.path.basename(file_path))
                embed = discord.Embed(
                    title=f"📥 {info.title[:100] if info else 'Video'}",
                    color=0x00FF00
                )
                await interaction.followup.send(embed=embed, file=file)
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            await interaction.followup.send("❌ Error")
    
    async def cmd_stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(str(interaction.user.id))
        embed = discord.Embed(title="📊 Statistics", color=0x00D4AA)
        embed.add_field(name="Scans", value=str(stats.get('total', 0)), inline=True)
        embed.add_field(name="Success", value=str(stats.get('success', 0)), inline=True)
        embed.add_field(name="Videos", value=str(stats.get('videos_downloaded', 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"`{round(self.latency * 1000)}ms`", inline=True)
        embed.add_field(name="Cache", value=f"`{self.cache.stats()}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text='HYPER OMEGA v6.0 OK'))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080))).start()

async def main():
    asyncio.create_task(health_server())
    bot = OmegaBot()
    try:
        await bot.start(Config.TOKEN)
    except KeyboardInterrupt:
        pass
    finally:
        await bot.close()

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"Fatal: {e}")
            time.sleep(10)
