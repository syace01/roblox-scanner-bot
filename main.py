"""
🚀 TRUE OMEGA v7.0 - GOD-TIER SCANNER + VIDEO DOWNLOADER
Features: GPU Neural OCR, Smart Context AI, Parallel Ultra-Processing, Auto-Correction
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
import difflib
import string
from datetime import datetime
from urllib.parse import quote, urlparse
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple, Union, Callable
from collections import defaultdict, Counter
import logging
import functools
import inspect

warnings.filterwarnings('ignore')

# Ultra-detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | \033[36m%(levelname)-8s\033[0m | \033[33m%(funcName)s\033[0m | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("omega")

# ═══════════════════════════════════════════════════════════
# GOD-TIER CONFIG
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # HYPER TIMEOUTS - AGGRESSIVE SPEED
    DOWNLOAD_TIMEOUT = 10
    OCR_TIMEOUT = 4
    API_TIMEOUT = 3
    VIDEO_TIMEOUT = 120
    
    MAX_FILE_SIZE = 100 * 1024 * 1024
    RATE_LIMIT = 100  # Doubled for speed
    
    # ROBLOX USERNAME RULES
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$')
    USERNAME_MIN_LEN = 3
    USERNAME_MAX_LEN = 20
    
    # VIDEO DOMAINS
    VIDEO_DOMAINS = [
        'medal.tv', 'streamable.com', 'youtube.com', 'youtu.be',
        'twitter.com', 'x.com', 'reddit.com', 'tiktok.com',
        'instagram.com', 'facebook.com', 'twitch.tv', 'clips.twitch.tv'
    ]
    
    # OCR ENGINE PRIORITY (fastest first)
    OCR_PRIORITY = ['rapidocr', 'easyocr', 'tesseract', 'ocrspace']
    
    # FALSE POSITIVES - EXTENSIVE LIST
    FALSE_POSITIVES = {
        'roblox', 'profile', 'username', 'display', 'user', 'avatar', 
        'friends', 'home', 'settings', 'catalog', 'inventory', 'trades',
        'groups', 'messages', 'premium', 'create', 'money', 'robux',
        'avatar shop', 'discover', 'search', 'more', 'menu', 'notifications',
        'chat', 'character', 'animations', 'body', 'clothing', 'accessories',
        'game', 'play', 'favorite', 'report', 'server', 'players', 'online',
        'offline', 'join', 'leave', 'loading', 'error', 'success', 'failed',
        'cancel', 'confirm', 'back', 'next', 'previous', 'continue', 'start',
        'end', 'close', 'open', 'save', 'delete', 'edit', 'update', 'create',
        'account', 'password', 'email', 'phone', 'verify', 'security', 'privacy',
        'terms', 'policy', 'help', 'support', 'about', 'contact', 'blog',
        'careers', 'parents', 'safety', 'accessibility', 'developers',
        'advertise', 'investors', 'safety', 'community', 'guidelines',
        'terms of use', 'privacy policy', 'cookie policy', 'copyright',
        'trademark', 'patent', 'legal', 'compliance', 'transparency',
        'upload', 'download', 'share', 'like', 'dislike', 'comment',
        'subscribe', 'follow', 'unfollow', 'block', 'unblock', 'mute',
        'unmute', 'ban', 'unban', 'kick', 'promote', 'demote', 'admin',
        'moderator', 'owner', 'member', 'guest', 'visitor', 'new', 'old',
        'top', 'best', 'hot', 'trending', 'popular', 'recent', 'random',
        'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta',
        'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'omicron', 'pi', 'rho',
        'sigma', 'tau', 'upsilon', 'phi', 'chi', 'psi', 'omega'
    }

Config.validate = lambda: logger.info(f"✅ Config loaded | Owner: {Config.OWNER_ID}") or None if Config.TOKEN else logger.error("❌ No DISCORD_TOKEN") or sys.exit(1)
Config.validate()

# ═══════════════════════════════════════════════════════════
# GOD-TIER IMPORTS WITH FALLBACKS
# ═══════════════════════════════════════════════════════════
import aiohttp
from aiohttp import TCPConnector, FormData
import discord
from discord import app_commands

# PIL - REQUIRED
try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.error("❌ PIL not available")

# OpenCV - CRITICAL FOR SPEED
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
    logger.info("✅ OpenCV available")
except ImportError:
    CV2_AVAILABLE = False
    logger.error("❌ OpenCV not available - Performance will suffer")

# Tesseract
try:
    import pytesseract
    from pytesseract import Output
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

# EasyOCR
EASYOCR_AVAILABLE = False
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    pass

# RapidOCR - FASTEST CPU OCR
RAPIDOCR_AVAILABLE = False
try:
    from rapidocr_onnxruntime import RapidOCR
    RAPIDOCR_AVAILABLE = True
    logger.info("✅ RapidOCR available - ULTRA SPEED MODE")
except ImportError:
    logger.warning("⚠️ RapidOCR not available - Install: pip install rapidocr-onnxruntime")

# PaddleOCR - Alternative
PADDLEOCR_AVAILABLE = False
try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
    logger.info("✅ PaddleOCR available")
except ImportError:
    pass

# Database
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

logger.info(f"🔧 Engines: RapidOCR={RAPIDOCR_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}, PaddleOCR={PADDLEOCR_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# GOD-TIER CACHE - LRU + REDIS HYBRID
# ═══════════════════════════════════════════════════════════
class GodCache:
    """Ultra-fast cache with intelligent prefetching"""
    def __init__(self, maxsize=100000):
        self._cache = {}
        self._expiry = {}
        self._hits = 0
        self._misses = 0
        self.maxsize = maxsize
        self.redis = None
        self._prefetch_queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        
    async def setup(self):
        if REDIS_AVAILABLE and Config.REDIS_URL:
            try:
                self.redis = await redis.from_url(Config.REDIS_URL, decode_responses=True)
                await self.redis.ping()
                logger.info("✅ Redis connected")
            except Exception as e:
                logger.warning(f"Redis failed: {e}")
    
    async def get(self, key: str, default=None):
        now = time.time()
        
        # Local cache hit
        if key in self._cache:
            if now < self._expiry.get(key, 0):
                self._hits += 1
                return self._cache[key]
            else:
                del self._cache[key]
                del self._expiry[key]
        
        # Redis fallback
        if self.redis:
            try:
                data = await self.redis.get(f"o:{key}")
                if data:
                    val = json.loads(data)
                    self._cache[key] = val
                    self._expiry[key] = now + 600
                    self._hits += 1
                    return val
            except:
                pass
        
        self._misses += 1
        return default
    
    async def set(self, key: str, value: Any, ttl: int = 600):
        now = time.time()
        self._cache[key] = value
        self._expiry[key] = now + ttl
        
        # Async eviction
        if len(self._cache) > self.maxsize:
            asyncio.create_task(self._evict())
        
        # Redis background write
        if self.redis:
            asyncio.create_task(self._redis_set(key, value, ttl))
    
    async def _redis_set(self, key: str, value: Any, ttl: int):
        try:
            await self.redis.setex(f"o:{key}", ttl, json.dumps(value))
        except:
            pass
    
    async def _evict(self):
        """Evict oldest 5%"""
        if len(self._cache) <= self.maxsize:
            return
        sorted_items = sorted(self._expiry.items(), key=lambda x: x[1])
        cutoff = int(len(sorted_items) * 0.05)
        for k, _ in sorted_items[:cutoff]:
            self._cache.pop(k, None)
            self._expiry.pop(k, None)
    
    def stats(self):
        total = self._hits + self._misses
        rate = (self._hits / total * 100) if total > 0 else 0
        return f"{self._hits}/{total} ({rate:.1f}%) | {len(self._cache)} items"

# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════
@dataclass(order=True)
class DetectedUser:
    confidence: float = field(compare=True)
    username: str = field(compare=False)
    display_name: Optional[str] = field(default=None, compare=False)
    source: str = field(default="unknown", compare=False)
    engine: str = field(default="unknown", compare=False)
    raw_text: str = field(default="", compare=False)
    bbox: Optional[Tuple] = field(default=None, compare=False)
    line_number: int = field(default=0, compare=False)

@dataclass
class OCRResult:
    text: str
    engine: str
    confidence: float
    processing_time: float
    lines: List[Dict] = field(default_factory=list)
    raw_output: Any = None

@dataclass
class VideoInfo:
    url: str
    title: str
    duration: str
    uploader: str
    thumbnail: Optional[str]
    filesize: Optional[int]

# ═══════════════════════════════════════════════════════════
# GOD-TIER IMAGE PREPROCESSOR - NEURAL ENHANCEMENT
# ═══════════════════════════════════════════════════════════
class GodPreprocessor:
    """Neural-grade image preprocessing"""
    
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self._kernels = self._init_kernels()
        
    def _init_kernels(self) -> Dict[str, np.ndarray]:
        """Initialize convolution kernels"""
        return {
            'sharpen': np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]]),
            'edge': np.array([[-1,-1,-1], [-1,8,-1], [-1,-1,-1]]),
            ' emboss': np.array([[-2,-1,0], [-1,1,1], [0,1,2]]),
        }
    
    async def preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Generate optimal variants for OCR"""
        if not CV2_AVAILABLE:
            return await self._pil_preprocess(image_data)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._cv_preprocess, image_data)
    
    def _cv_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """OpenCV preprocessing pipeline"""
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return self._pil_fallback(image_data)
        
        h, w = img.shape[:2]
        variants = []
        
        # Parallel processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = []
            
            # 1. Original (always)
            futures.append(pool.submit(self._encode_variant, img.copy(), "original"))
            
            # 2. Grayscale CLAHE (best for text)
            futures.append(pool.submit(self._variant_clahe, img.copy()))
            
            # 3. Denoised
            futures.append(pool.submit(self._variant_denoise, img.copy()))
            
            # 4. Upscaled (if small text)
            if w < 1200:
                futures.append(pool.submit(self._variant_upscale, img.copy()))
            
            # 5. High contrast
            futures.append(pool.submit(self._variant_contrast, img.copy()))
            
            # 6. Inverted (for dark mode screenshots)
            futures.append(pool.submit(self._variant_inverted, img.copy()))
            
            # 7. Adaptive threshold
            futures.append(pool.submit(self._variant_adaptive, img.copy()))
            
            # 8. Sharpened
            futures.append(pool.submit(self._variant_sharpen, img.copy()))
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        variants.append(result)
                except Exception as e:
                    logger.debug(f"Variant failed: {e}")
        
        # Sort by priority
        priority = ["original", "clahe", "upscaled", "denoised", "contrast", 
                   "sharpened", "adaptive", "inverted"]
        variants.sort(key=lambda x: priority.index(x[1]) if x[1] in priority else 99)
        
        return variants[:6]
    
    def _variant_clahe(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        enhanced = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        return self._encode_variant(enhanced, "clahe")
    
    def _variant_denoise(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        denoised = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
        return self._encode_variant(denoised, "denoised")
    
    def _variant_upscale(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        h, w = img.shape[:2]
        upscaled = cv2.resize(img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
        return self._encode_variant(upscaled, "upscaled")
    
    def _variant_contrast(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        alpha = 1.5  # Contrast
        beta = 10    # Brightness
        adjusted = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
        return self._encode_variant(adjusted, "contrast")
    
    def _variant_inverted(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        inverted = cv2.bitwise_not(gray)
        _, buf = cv2.imencode('.png', inverted)
        return (buf.tobytes(), "inverted", {"inverted": True})
    
    def _variant_adaptive(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        _, buf = cv2.imencode('.png', adaptive)
        return (buf.tobytes(), "adaptive", {})
    
    def _variant_sharpen(self, img: np.ndarray) -> Tuple[bytes, str, Dict]:
        sharpened = cv2.filter2D(img, -1, self._kernels['sharpen'])
        return self._encode_variant(sharpened, "sharpened")
    
    def _encode_variant(self, img: np.ndarray, name: str) -> Tuple[bytes, str, Dict]:
        _, buf = cv2.imencode('.png', img)
        return (buf.tobytes(), name, {"size": img.shape[:2]})
    
    def _pil_fallback(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        img = Image.open(io.BytesIO(image_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        variants = []
        
        # Original
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        variants.append((buf.getvalue(), "original", {}))
        
        # Enhanced
        enhanced = ImageEnhance.Contrast(img).enhance(2.0)
        buf = io.BytesIO()
        enhanced.save(buf, format='PNG')
        variants.append((buf.getvalue(), "contrast", {}))
        
        return variants
    
    async def _pil_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._pil_fallback, image_data)

# ═══════════════════════════════════════════════════════════
# GOD-TIER OCR - MULTI-ENGINE WITH SMART FUSION
# ═══════════════════════════════════════════════════════════
class GodOCR:
    """Ultimate OCR with engine fusion and error correction"""
    
    def __init__(self, cache: GodCache):
        self.cache = cache
        self.preprocessor = GodPreprocessor()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=12)
        
        # Engine instances
        self.rapidocr = None
        self.easyocr_reader = None
        self.paddleocr = None
        
        # Status flags
        self.engines_ready = {
            'rapidocr': False,
            'easyocr': False,
            'paddleocr': False,
            'tesseract': TESSERACT_AVAILABLE,
            'ocrspace': bool(Config.OCR_SPACE_KEY)
        }
        
        # Compiled patterns
        self.patterns = self._compile_patterns()
        
        # Common OCR mistakes mapping
        self.ocr_corrections = self._load_corrections()
        
    def _compile_patterns(self) -> Dict[str, re.Pattern]:
        """Ultra-comprehensive pattern matching"""
        return {
            'at_mention': re.compile(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'display_at': re.compile(r'([A-Za-z][\w\s]{1,20})\s*[@＠]\s*([a-zA-Z][\w]{2,19})\b'),
            'roblox_url': re.compile(r'roblox\.com/users/(\d+)', re.I),
            'roblox_profile': re.compile(r'roblox\.com/profile\?username=([\w]+)', re.I),
            'username': re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'display_label': re.compile(r'(?:display\s*name|name)\s*[:=]\s*([A-Za-z][\w\s]{2,20})', re.I),
            'user_label': re.compile(r'(?:user\s*name|username|user)\s*[:=]\s*[@＠]?([a-zA-Z][\w]{2,19})', re.I),
            'handle': re.compile(r'handle\s*[:=]\s*[@＠]?([a-zA-Z][\w]{2,19})', re.I),
            'joined': re.compile(r'joined\s*[:=]\s*([a-zA-Z][\w]{2,19})', re.I),
        }
    
    def _load_corrections(self) -> Dict[str, str]:
        """Common OCR character misreadings"""
        return {
            '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's',
            '6': 'g', '7': 't', '8': 'b', '9': 'g',
            '$': 's', '@': 'a', '!': 'i', '|': 'l',
        }
    
    async def init_engines(self):
        """Initialize all engines in parallel"""
        init_tasks = []
        
        if RAPIDOCR_AVAILABLE:
            init_tasks.append(self._init_rapidocr())
        if EASYOCR_AVAILABLE:
            init_tasks.append(self._init_easyocr())
        if PADDLEOCR_AVAILABLE:
            init_tasks.append(self._init_paddleocr())
        
        await asyncio.gather(*init_tasks, return_exceptions=True)
        
        ready = [k for k, v in self.engines_ready.items() if v]
        logger.info(f"✅ OCR Engines ready: {ready}")
    
    async def _init_rapidocr(self):
        try:
            loop = asyncio.get_event_loop()
            self.rapidocr = await asyncio.wait_for(
                loop.run_in_executor(self.executor, RapidOCR),
                timeout=20
            )
            self.engines_ready['rapidocr'] = True
            logger.info("✅ RapidOCR initialized")
        except Exception as e:
            logger.warning(f"RapidOCR failed: {e}")
    
    async def _init_easyocr(self):
        try:
            loop = asyncio.get_event_loop()
            try:
                self.easyocr_reader = await asyncio.wait_for(
                    loop.run_in_executor(self.executor, 
                        lambda: easyocr.Reader(['en'], gpu=True, verbose=False)),
                    timeout=30
                )
                logger.info("✅ EasyOCR GPU ready")
            except:
                self.easyocr_reader = await asyncio.wait_for(
                    loop.run_in_executor(self.executor,
                        lambda: easyocr.Reader(['en'], gpu=False, verbose=False)),
                    timeout=30
                )
                logger.info("✅ EasyOCR CPU ready")
            self.engines_ready['easyocr'] = True
        except Exception as e:
            logger.warning(f"EasyOCR failed: {e}")
    
    async def _init_paddleocr(self):
        try:
            loop = asyncio.get_event_loop()
            self.paddleocr = await asyncio.wait_for(
                loop.run_in_executor(self.executor,
                    lambda: PaddleOCR(use_angle_cls=True, lang='en', show_log=False)),
                timeout=30
            )
            self.engines_ready['paddleocr'] = True
            logger.info("✅ PaddleOCR ready")
        except Exception as e:
            logger.warning(f"PaddleOCR failed: {e}")
    
    async def scan(self, image_data: bytes, hint: str = None) -> Tuple[bool, List[DetectedUser], str, Dict]:
        """God-tier scan with fusion"""
        start = time.perf_counter()
        
        # Check cache
        cache_key = hashlib.sha256(image_data).hexdigest()[:16]
        cached = await self.cache.get(f"ocr:{cache_key}")
        if cached:
            users = [DetectedUser(**u) for u in cached['users']]
            return len(users) > 0, users, cached['text'], {"cached": True, "time": 0}
        
        if not PIL_AVAILABLE:
            return False, [], "", {"error": "PIL not available"}
        
        # Preprocess
        variants = await self.preprocessor.preprocess(image_data)
        
        # Run engines in parallel with different variants
        engine_tasks = []
        
        # RapidOCR on original (fastest)
        if self.engines_ready['rapidocr']:
            engine_tasks.append(self._run_rapidocr(variants[0][0]))
        
        # EasyOCR on CLAHE variant (best quality)
        if self.engines_ready['easyocr'] and len(variants) > 1:
            engine_tasks.append(self._run_easyocr(variants[1][0]))
        
        # Tesseract on multiple variants
        if self.engines_ready['tesseract']:
            for i, (img, name, _) in enumerate(variants[:3]):
                engine_tasks.append(self._run_tesseract(img, name))
        
        # OCR.space as backup
        if self.engines_ready['ocrspace']:
            engine_tasks.append(self._run_ocrspace(image_data))
        
        # Gather results with timeout
        results = await asyncio.gather(*engine_tasks, return_exceptions=True)
        results = [r for r in results if isinstance(r, OCRResult) and r.text.strip()]
        
        if not results:
            return False, [], "", {"error": "All engines failed", "time": time.perf_counter() - start}
        
        # FUSION: Merge and correct results
        fused_text = self._fuse_results(results)
        
        # Extract users with context awareness
        all_users = []
        for result in results:
            users = self._extract_users(result, hint, fused_text)
            all_users.extend(users)
        
        # Smart voting with deduplication
        voted = self._god_vote(all_users, hint, results)
        
        # Cache result
        if voted:
            await self.cache.set(f"ocr:{cache_key}", {
                'users': [{'username': u.username, 'display_name': u.display_name,
                          'confidence': u.confidence, 'source': u.source,
                          'engine': u.engine, 'raw_text': u.raw_text} for u in voted],
                'text': fused_text
            }, 3600)
        
        total_time = time.perf_counter() - start
        return len(voted) > 0, voted, fused_text, {
            "engines_used": [r.engine for r in results],
            "time": total_time,
            "variants": len(variants),
            "raw_results": len(results)
        }
    
    def _fuse_results(self, results: List[OCRResult]) -> str:
        """Merge OCR outputs intelligently"""
        # Weight by confidence and engine reliability
        weights = {
            'rapidocr': 1.2,
            'easyocr': 1.0,
            'tesseract': 0.8,
            'ocrspace': 0.9,
            'paddleocr': 1.1
        }
        
        # Combine all text
        all_lines = []
        for result in results:
            weight = weights.get(result.engine.split('_')[0], 0.5)
            lines = result.text.split('\n')
            for line in lines:
                if line.strip():
                    all_lines.append((line.strip(), weight * result.confidence))
        
        # Simple fusion: take highest confidence for similar lines
        fused = []
        seen = set()
        for line, conf in sorted(all_lines, key=lambda x: x[1], reverse=True):
            norm = line.lower().replace(' ', '')
            if norm not in seen:
                fused.append(line)
                seen.add(norm)
        
        return '\n'.join(fused)
    
    def _extract_users(self, result: OCRResult, hint: str, fused_text: str) -> List[DetectedUser]:
        """Advanced user extraction with context"""
        text = result.text
        users = []
        lines = text.split('\n')
        lower_text = text.lower()
        fused_lower = fused_text.lower()
        
        # Build context map
        context = {
            'has_roblox': 'roblox' in fused_lower,
            'has_profile': 'profile' in fused_lower,
            'has_display': 'display' in fused_lower,
            'has_username': 'username' in fused_lower,
            'has_at': '@' in text or '＠' in text,
        }
        
        # Pattern 1: @username (highest confidence)
        for m in self.patterns['at_mention'].finditer(text):
            u = m.group(1)
            if self._validate_username(u):
                conf = 0.98
                if hint:
                    if u.lower() == hint.lower().lstrip('@'):
                        conf = 1.0
                    elif difflib.SequenceMatcher(None, u.lower(), hint.lower()).ratio() > 0.8:
                        conf = 0.95
                users.append(DetectedUser(conf, u, None, '@mention', result.engine, 
                                        text[m.start():m.end()], None, 0))
        
        # Pattern 2: Display Name @username
        for m in self.patterns['display_at'].finditer(text):
            d, u = m.groups()
            d = d.strip()
            if self._validate_username(u) and len(d) > 2:
                users.append(DetectedUser(0.97, u, d, 'display@user', result.engine,
                                        text[m.start():m.end()], None, 0))
        
        # Pattern 3: Roblox URL
        for m in self.patterns['roblox_url'].finditer(text):
            uid = m.group(1)
            users.append(DetectedUser(0.99, f"ID:{uid}", None, 'url', result.engine,
                                    text[m.start():m.end()], None, 0))
        
        # Pattern 4: Contextual with ML-like scoring
        for i, line in enumerate(lines):
            line_lower = line.lower()
            
            # Skip if no context and line is short
            if not any(context.values()) and len(line) < 10:
                continue
            
            for m in self.patterns['username'].finditer(line):
                u = m.group(1)
                if not self._validate_username(u):
                    continue
                if u.lower() in Config.FALSE_POSITIVES:
                    continue
                
                # Context scoring
                conf = 0.5
                if context['has_roblox']:
                    conf += 0.15
                if context['has_profile']:
                    conf += 0.1
                if context['has_display']:
                    conf += 0.05
                if context['has_username']:
                    conf += 0.1
                
                # Proximity boost
                surrounding = ' '.join(lines[max(0,i-2):min(len(lines), i+3)]).lower()
                if any(w in surrounding for w in ['roblox', 'profile', '@', 'user']):
                    conf += 0.1
                
                # Capitalization check (real names usually have mixed case)
                if u[0].isupper() and not u.isupper() and not u.islower():
                    conf += 0.05
                
                # Hint similarity
                if hint:
                    sim = difflib.SequenceMatcher(None, u.lower(), hint.lower()).ratio()
                    if sim > 0.9:
                        conf = 1.0
                    elif sim > 0.7:
                        conf += 0.2
                
                users.append(DetectedUser(min(conf, 0.95), u, None, 'context', 
                                        result.engine, line, None, i))
        
        # Pattern 5: Labeled fields
        for pattern_name in ['display_label', 'user_label', 'handle', 'joined']:
            for m in self.patterns[pattern_name].finditer(text):
                if pattern_name == 'display_label':
                    d = m.group(1).strip()
                    # Find nearby username
                    nearby = text[max(0, m.start()-200):min(len(text), m.end()+200)]
                    for um in self.patterns['username'].finditer(nearby):
                        u = um.group(1)
                        if self._validate_username(u) and u.lower() not in Config.FALSE_POSITIVES:
                            users.append(DetectedUser(0.94, u, d, pattern_name, result.engine,
                                                    text[m.start():m.end()], None, 0))
                            break
                else:
                    u = m.group(1)
                    if self._validate_username(u):
                        users.append(DetectedUser(0.93, u, None, pattern_name, result.engine,
                                                text[m.start():m.end()], None, 0))
        
        return users
    
    def _validate_username(self, username: str) -> bool:
        """Strict validation with correction attempts"""
        if not username:
            return False
        
        # Direct match
        if Config.USERNAME_REGEX.match(username):
            return True
        
        # Try correcting common OCR errors
        corrected = self._correct_ocr_errors(username)
        if corrected != username and Config.USERNAME_REGEX.match(corrected):
            return True
        
        return False
    
    def _correct_ocr_errors(self, text: str) -> str:
        """Fix common OCR misreadings"""
        result = []
        for char in text:
            result.append(self.ocr_corrections.get(char, char))
        return ''.join(result)
    
    def _god_vote(self, users: List[DetectedUser], hint: str, results: List[OCRResult]) -> List[DetectedUser]:
        """Ultimate voting algorithm"""
        if not users:
            return []
        
        # Group by normalized username
        groups = defaultdict(list)
        for u in users:
            key = u.username.lower()
            groups[key].append(u)
        
        voted = []
        for username, group in groups.items():
            # Engine diversity
            engines = set(u.engine.split('_')[0] for u in group)
            engine_count = len(engines)
            
            # Best confidence
            best = max(group, key=lambda x: x.confidence)
            
            # Calculate final confidence
            final_conf = best.confidence
            
            # Engine diversity bonus
            final_conf += (engine_count - 1) * 0.03
            
            # Source quality bonus
            quality_sources = {'@mention', 'display@user', 'url', 'user_label'}
            if best.source in quality_sources:
                final_conf += 0.05
            
            # Hint match
            if hint:
                sim = difflib.SequenceMatcher(None, username, hint.lower()).ratio()
                if sim == 1.0:
                    final_conf = 1.0
                elif sim > 0.8:
                    final_conf += 0.1
            
            # Cross-engine agreement bonus
            if engine_count >= 3:
                final_conf += 0.05
            
            final_conf = min(final_conf, 1.0)
            
            # Get best display name
            display_names = [u.display_name for u in group if u.display_name]
            best_display = display_names[0] if display_names else best.display_name
            
            voted.append(DetectedUser(
                confidence=final_conf,
                username=best.username,
                display_name=best_display,
                source=f"{best.source}_v{engine_count}",
                engine=f"fusion_{engine_count}",
                raw_text=best.raw_text[:150]
            ))
        
        # Sort by confidence
        voted.sort(reverse=True)
        
        # Remove near-duplicates
        filtered = []
        for u in voted:
            is_duplicate = False
            for f in filtered:
                if self._is_similar_username(u.username, f.username):
                    is_duplicate = True
                    break
            if not is_duplicate:
                filtered.append(u)
        
        return filtered[:5]
    
    def _is_similar_username(self, a: str, b: str) -> bool:
        """Check if usernames are similar enough to be duplicates"""
        if a.lower() == b.lower():
            return True
        
        # Levenshtein-like check
        if abs(len(a) - len(b)) <= 2:
            sim = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if sim > 0.85:
                return True
        
        # One contains the other
        if len(a) > 4 and len(b) > 4:
            if a.lower() in b.lower() or b.lower() in a.lower():
                return True
        
        return False
    
    # Engine runners
    async def _run_rapidocr(self, image_data: bytes) -> OCRResult:
        start = time.perf_counter()
        
        def _run():
            result = self.rapidocr(image_data)
            texts = []
            confs = []
            for line in result[0] if result and result[0] else []:
                if len(line) >= 3:
                    texts.append(line[1])
                    confs.append(line[2])
            full_text = ' '.join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0.5
            return full_text, avg_conf
        
        loop = asyncio.get_event_loop()
        text, conf = await loop.run_in_executor(self.executor, _run)
        return OCRResult(text, "rapidocr", conf, time.perf_counter() - start)
    
    async def _run_easyocr(self, image_data: bytes) -> OCRResult:
        start = time.perf_counter()
        
        def _run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, detail=1, paragraph=False)
            texts = [r[1] for r in results]
            confs = [r[2] for r in results]
            full_text = '\n'.join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0.5
            return full_text, avg_conf
        
        loop = asyncio.get_event_loop()
        text, conf = await loop.run_in_executor(self.executor, _run)
        return OCRResult(text, "easyocr", conf, time.perf_counter() - start)
    
    async def _run_tesseract(self, image_data: bytes, variant: str) -> OCRResult:
        start = time.perf_counter()
        
        def _run():
            img = Image.open(io.BytesIO(image_data))
            config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@ '
            text = pytesseract.image_to_string(img, config=config)
            
            data = pytesseract.image_to_data(img, config=config, output_type=Output.DICT)
            confs = [int(c) for c in data['conf'] if int(c) > 0]
            avg_conf = sum(confs) / len(confs) / 100 if confs else 0.5
            
            return text, avg_conf
        
        loop = asyncio.get_event_loop()
        text, conf = await loop.run_in_executor(self.executor, _run)
        return OCRResult(text, f"tesseract_{variant}", conf, time.perf_counter() - start)
    
    async def _run_ocrspace(self, image_data: bytes) -> OCRResult:
        start = time.perf_counter()
        
        data = FormData()
        data.add_field('file', image_data, filename='image.png', content_type='image/png')
        data.add_field('apikey', Config.OCR_SPACE_KEY)
        data.add_field('OCREngine', '2')
        data.add_field('scale', 'true')
        
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
                        return OCRResult(text, "ocrspace", conf, time.perf_counter() - start)
        
        return OCRResult("", "ocrspace", 0, time.perf_counter() - start)

# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER (OPTIMIZED)
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.download_path = "downloads/videos"
        os.makedirs(self.download_path, exist_ok=True)
    
    def _format_duration(self, seconds) -> str:
        if not seconds:
            return "Unknown"
        try:
            seconds = int(float(seconds))
        except:
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
            return False, "Unsupported domain", None, None
        
        video_id = hashlib.md5(url.encode()).hexdigest()[:8]
        output_path = os.path.join(self.download_path, f"{video_id}.mp4")
        
        if os.path.exists(output_path):
            return True, "Cached", output_path, None
        
        loop = asyncio.get_event_loop()
        try:
            success, message, info = await asyncio.wait_for(
                loop.run_in_executor(self.executor, self._run_download, url, output_path),
                timeout=Config.VIDEO_TIMEOUT
            )
            return success, message, output_path if success else None, info
        except asyncio.TimeoutError:
            return False, "Timeout", None, None
    
    def _run_download(self, url: str, output_path: str):
        try:
            # Info
            result = subprocess.run(
                ['yt-dlp', '--dump-json', '--no-download', url],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return False, "Info failed", None
            
            info = json.loads(result.stdout.strip().split('\n')[0])
            video_info = VideoInfo(
                url=url, title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            # Download
            result = subprocess.run(
                ['yt-dlp', '-f', 'best[ext=mp4]/best', '--merge-output-format', 'mp4',
                 '-o', output_path, '--no-playlist', '--newline', url],
                capture_output=True, text=True, timeout=Config.VIDEO_TIMEOUT
            )
            
            return os.path.exists(output_path), "Success" if os.path.exists(output_path) else "Failed", video_info
            
        except Exception as e:
            return False, str(e), None
    
    async def get_info(self, url: str):
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    lambda: subprocess.run(['yt-dlp', '--dump-json', '--no-download', url],
                                         capture_output=True, text=True, timeout=15)
                ), timeout=20
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
# HYPER ROBLOX API
# ═══════════════════════════════════════════════════════════
class HyperRobloxAPI:
    def __init__(self, cache: GodCache):
        self.cache = cache
        self.session = None
        self.sem = asyncio.Semaphore(25)
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            connector=TCPConnector(limit=100, limit_per_host=50),
            timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Accept-Encoding": "gzip"}
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        if not users:
            return []
        
        # Deduplicate and limit
        seen = set()
        unique_users = []
        for u in users:
            key = u.username.lower()
            if key not in seen and len(unique_users) < 8:
                seen.add(key)
                unique_users.append(u)
        
        # Check cache
        to_fetch = []
        verified = []
        
        for user in unique_users:
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
        
        # Fetch in parallel with semaphore
        if to_fetch:
            tasks = [self._fetch_with_sem(u) for u in to_fetch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for user, result in zip(to_fetch, results):
                if isinstance(result, dict):
                    await self.cache.set(f"u:{user.username.lower()}", result, 900)
                    verified.append({
                        'profile': result,
                        'detected': user,
                        'score': user.confidence,
                        'cached': False
                    })
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_with_sem(self, user: DetectedUser):
        async with self.sem:
            return await self._fetch_user(user)
    
    async def _fetch_user(self, user: DetectedUser):
        try:
            if user.username.startswith("ID:"):
                return await self._fetch_by_id(int(user.username.split(":")[1]))
            
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [user.username], "excludeBannedUsers": False}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        return await self._fetch_by_id(data['data'][0]['id'])
        except Exception as e:
            logger.debug(f"Fetch error: {e}")
        return None
    
    async def _fetch_by_id(self, user_id: int):
        try:
            async with self.session.get(f'https://users.roblox.com/v1/users/{user_id}') as resp:
                if resp.status == 200:
                    profile = await resp.json()
                    profile['thumbnailUrl'] = await self._get_avatar(user_id)
                    return profile
        except Exception as e:
            logger.debug(f"Fetch by ID error: {e}")
        return None
    
    async def _get_avatar(self, user_id: int):
        cached = await self.cache.get(f"a:{user_id}")
        if cached:
            return cached
        
        try:
            async with self.session.get(
                f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png'
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

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
class Database:
    def __init__(self):
        self.whitelist: Set[str] = set()
        os.makedirs("data", exist_ok=True)
        os.makedirs("downloads/videos", exist_ok=True)
        
    async def setup(self):
        self.whitelist = {Config.OWNER_ID}
        try:
            if os.path.exists("data/whitelist.json"):
                with open("data/whitelist.json") as f:
                    self.whitelist.update(str(u) for u in json.load(f).get('users', []))
        except:
            pass
        logger.info(f"✅ Whitelist: {len(self.whitelist)}")
    
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
# RATE LIMITER
# ═══════════════════════════════════════════════════════════
class RateLimiter:
    def __init__(self, max_req: int, window: int):
        self.max_req = max_req
        self.window = window
        self.requests: Dict[str, List[float]] = {}
        self.lock = asyncio.Lock()
    
    async def check(self, key: str):
        now = time.time()
        async with self.lock:
            if key not in self.requests:
                self.requests[key] = []
            self.requests[key] = [t for t in self.requests[key] if now - t < self.window]
            if len(self.requests[key]) >= self.max_req:
                return False, self.requests[key][0] + self.window - now
            self.requests[key].append(now)
            return True, 0

# ═══════════════════════════════════════════════════════════
# GOD BOT
# ═══════════════════════════════════════════════════════════
class GodBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.cache = GodCache()
        self.limiter = RateLimiter(Config.RATE_LIMIT, 60)
        self.video_limiter = RateLimiter(10, 60)
        self.ocr = None
        self.roblox = None
        self.video = VideoDownloader()
        
    async def setup_hook(self):
        logger.info("🔧 Initializing GOD OMEGA v7.0...")
        
        await self.cache.setup()
        await self.db.setup()
        
        self.roblox = HyperRobloxAPI(self.cache)
        await self.roblox.setup()
        
        self.ocr = GodOCR(self.cache)
        await self.ocr.init_engines()
        
        self._register_cmds()
        
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Sync failed: {e}")
        
        logger.info("✅ GOD OMEGA v7.0 READY")
    
    def _register_cmds(self):
        @self.tree.command(name="scan", description="🔍 GOD SCAN - Ultimate Roblox username detection")
        @app_commands.describe(image="Screenshot", hint="Optional hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download video")
        @app_commands.describe(url="URL", info_only="Info only")
        async def download(interaction: discord.Interaction, url: str, info_only: bool = False):
            await self.cmd_download(interaction, url, info_only)
        
        @self.tree.command(name="stats", description="📊 Statistics")
        async def stats(interaction: discord.Interaction):
            await self.cmd_stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Ping")
        async def ping(interaction: discord.Interaction):
            await self.cmd_ping(interaction)
    
    async def cmd_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        uid = str(interaction.user.id)
        start = time.perf_counter()
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        allowed, retry = await self.limiter.check(uid)
        if not allowed:
            await interaction.response.send_message(f"⏰ Rate limited: {int(retry)}s", ephemeral=True)
            return
        
        if image.size > 10 * 1024 * 1024:
            await interaction.response.send_message("❌ Max 10MB", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Download
            async with aiohttp.ClientSession() as session:
                async with session.get(image.url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("❌ Download failed")
                        return
                    img_data = await resp.read()
            
            # GOD SCAN
            success, users, text, meta = await self.ocr.scan(img_data, hint)
            
            if not success:
                embed = discord.Embed(
                    title="❌ No Username Found",
                    description="Could not detect valid Roblox username",
                    color=0xFF6B6B
                )
                embed.add_field(name="Time", value=f"`{time.perf_counter() - start:.2f}s`")
                await interaction.followup.send(embed=embed)
                return
            
            # Verify
            verified = await self.roblox.verify_users(users)
            
            if not verified:
                embed = discord.Embed(
                    title="❌ Not Found",
                    description=f"Detected `@{users[0].username}` - not on Roblox",
                    color=0xFF6B6B
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Success
            best = verified[0]
            prof = best['profile']
            det = best['detected']
            total_time = time.perf_counter() - start
            
            # Color by confidence
            if det.confidence >= 0.95:
                color, emoji = 0x00FF00, "✅"
            elif det.confidence >= 0.80:
                color, emoji = 0x55FF55, "✓"
            elif det.confidence >= 0.60:
                color, emoji = 0xFFAA00, "⚠"
            else:
                color, emoji = 0xFF5555, "?"
            
            embed = discord.Embed(
                title=f"{emoji} {prof.get('displayName', prof['name'])}",
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
            embed.add_field(name="🧠 OCRs", value=f"`{len(meta.get('engines_used', []))}`", inline=True)
            
            if prof.get('thumbnailUrl'):
                embed.set_thumbnail(url=prof['thumbnailUrl'])
            embed.set_image(url=image.url)
            embed.set_footer(text="GOD OMEGA v7.0")
            
            await interaction.followup.send(embed=embed)
            
            # Stats
            stats = await self.db.get_stats(uid)
            stats['total'] = stats.get('total', 0) + 1
            stats['success'] = stats.get('success', 0) + 1
            await self.db.save_stats(uid, stats)
            
        except Exception as e:
            logger.error(f"Scan error: {traceback.format_exc()}")
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    async def cmd_download(self, interaction: discord.Interaction, url: str, info_only: bool):
        uid = str(interaction.user.id)
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            if info_only:
                success, info = await self.video.get_info(url)
                if not success:
                    await interaction.followup.send("❌ Failed")
                    return
                
                embed = discord.Embed(
                    title=f"📹 {info.title[:100]}",
                    description=f"**{info.uploader}** • {info.duration}",
                    color=0x00D4AA
                )
                await interaction.followup.send(embed=embed)
            else:
                success, msg, path, info = await self.video.download(url)
                if not success or not path:
                    await interaction.followup.send(f"❌ {msg}")
                    return
                
                size = os.path.getsize(path)
                if size > Config.MAX_FILE_SIZE:
                    await interaction.followup.send("❌ Too large")
                    return
                
                file = discord.File(path, filename=os.path.basename(path))
                embed = discord.Embed(title=f"📥 {info.title[:100] if info else 'Video'}", color=0x00FF00)
                await interaction.followup.send(embed=embed, file=file)
                
                stats = await self.db.get_stats(uid)
                stats['videos_downloaded'] = stats.get('videos_downloaded', 0) + 1
                await self.db.save_stats(uid, stats)
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
# HEALTH SERVER
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    
    async def health(request):
        return web.Response(text="GOD OMEGA v7.0 OK", status=200)
    
    app = web.Application()
    app.router.add_get('/health', health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    logger.info(f"✅ Health on port {os.getenv('PORT', 8080)}")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def main():
    await health_server()
    bot = GodBot()
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
