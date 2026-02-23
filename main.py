"""
🚀 TRUE OMEGA v5.0 - ULTIMATE SCANNER
The most powerful Roblox username scanner ever made
Features: Ensemble OCR, Advanced Preprocessing, Beautiful Webhooks, Download Command
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
from datetime import datetime
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import logging

warnings.filterwarnings('ignore')

# Colorful logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | \033[36m%(levelname)-8s\033[0m | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("omega")

# ═══════════════════════════════════════════════════════════
# CONFIG - ULTIMATE POWER
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')  # For notifications
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # AGGRESSIVE TIMEOUTS FOR SPEED
    DOWNLOAD_TIMEOUT = 8
    OCR_TIMEOUT = 6
    API_TIMEOUT = 5
    
    MAX_FILE_SIZE = 25 * 1024 * 1024
    RATE_LIMIT = 20  # Increased
    
    # OCR ENGINE PRIORITIES
    OCR_ENGINES = ['easyocr', 'tesseract', 'ocrspace']  # Priority order
    
    # USERNAME VALIDATION (Roblox rules: 3-20 chars, start with letter, alphanumeric+underscore)
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$')

Config.validate = lambda: logger.info(f"✅ Config loaded | Owner: {Config.OWNER_ID}") or None if Config.TOKEN else logger.error("❌ No DISCORD_TOKEN") or sys.exit(1)
Config.validate()

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════
import aiohttp
from aiohttp import TCPConnector, FormData
import discord
from discord import app_commands

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
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

logger.info(f"🔧 PIL={PIL_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}, CV2={CV2_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# CACHE - ULTRA FAST
# ═══════════════════════════════════════════════════════════
class UltraCache:
    def __init__(self, maxsize=10000):
        self.cache = {}
        self.expiry = {}
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
                logger.warning(f"Redis: {e}")
    
    async def get(self, key: str):
        # Memory first
        if key in self.cache and time.time() < self.expiry.get(key, 0):
            self._hits += 1
            return self.cache[key]
        
        # Redis second
        if self.redis:
            try:
                data = await self.redis.get(f"o:{key}")
                if data:
                    val = json.loads(data)
                    self.cache[key] = val
                    self.expiry[key] = time.time() + 300
                    self._hits += 1
                    return val
            except:
                pass
        
        self._misses += 1
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        self.cache[key] = value
        self.expiry[key] = time.time() + ttl
        
        # Evict oldest if needed
        if len(self.cache) > self.maxsize:
            oldest = min(self.expiry.items(), key=lambda x: x[1])
            del self.cache[oldest[0]]
            del self.expiry[oldest[0]]
        
        if self.redis:
            try:
                await self.redis.setex(f"o:{key}", ttl, json.dumps(value))
            except:
                pass
    
    def stats(self):
        total = self._hits + self._misses
        rate = (self._hits / total * 100) if total > 0 else 0
        return f"Cache: {self._hits} hits, {self._misses} misses ({rate:.1f}%)"

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

@dataclass
class OCRResult:
    text: str
    engine: str
    confidence: float
    processing_time: float

# ═══════════════════════════════════════════════════════════
# ADVANCED IMAGE PREPROCESSING PIPELINE
# ═══════════════════════════════════════════════════════════
class ImagePreprocessor:
    """Advanced preprocessing for maximum OCR accuracy"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    async def preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """
        Generate multiple preprocessed versions for ensemble OCR
        Returns: [(image_bytes, version_name, metadata), ...]
        """
        if not CV2_AVAILABLE or not PIL_AVAILABLE:
            # Fallback to basic processing
            return await self._basic_preprocess(image_data)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._advanced_preprocess, image_data)
    
    def _advanced_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Advanced OpenCV preprocessing pipeline"""
        versions = []
        
        # Load with OpenCV
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return self._pil_fallback(image_data)
        
        original = img.copy()
        h, w = img.shape[:2]
        
        # 1. Original (baseline)
        versions.append(self._encode_cv2(original, "original"))
        
        # 2. Grayscale + CLAHE (adaptive histogram equalization)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)
        versions.append(self._encode_cv2(gray_clahe, "gray_clahe", is_gray=True))
        
        # 3. Denoised (bilateral filter preserves edges)
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)
        versions.append(self._encode_cv2(denoised, "denoised", is_gray=True))
        
        # 4. Upscaled (if small)
        if w < 800:
            scaled = cv2.resize(gray, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
            versions.append(self._encode_cv2(scaled, "upscaled", is_gray=True))
        
        # 5. Binarized (Otsu)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        versions.append(self._encode_cv2(binary, "binary", is_gray=True))
        
        # 6. Deskewed (if text is rotated)
        try:
            deskewed = self._deskew(gray)
            versions.append(self._encode_cv2(deskewed, "deskewed", is_gray=True))
        except Exception as e:
            logger.debug(f"Deskew failed: {e}")
        
        # 7. Sharpened
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(gray, -1, kernel)
        versions.append(self._encode_cv2(sharpened, "sharpened", is_gray=True))
        
        # 8. Morphological (close gaps in text)
        kernel = np.ones((2, 2), np.uint8)
        morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        versions.append(self._encode_cv2(morph, "morphological", is_gray=True))
        
        return versions
    
    def _deskew(self, gray_img: np.ndarray) -> np.ndarray:
        """Deskew text using minAreaRect method"""
        # Invert for contour detection
        gray_inv = cv2.bitwise_not(gray_img)
        thresh = cv2.threshold(gray_inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        
        # Find all text
        coords = np.column_stack(np.where(thresh > 0))
        angle = cv2.minAreaRect(coords)[-1]
        
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        
        if abs(angle) < 0.5:  # Already straight
            return gray_img
        
        # Rotate
        (h, w) = gray_img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(gray_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rotated
    
    def _encode_cv2(self, img: np.ndarray, name: str, is_gray: bool = False) -> Tuple[bytes, str, Dict]:
        """Encode OpenCV image to bytes"""
        if is_gray:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        _, buf = cv2.imencode('.png', img)
        return (buf.tobytes(), name, {"size": img.shape[:2]})
    
    def _pil_fallback(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Fallback PIL processing"""
        img = Image.open(io.BytesIO(image_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        versions = []
        
        # Original
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        versions.append((buf.getvalue(), "original", {}))
        
        # Enhanced contrast
        enhanced = ImageEnhance.Contrast(img).enhance(2.0)
        buf = io.BytesIO()
        enhanced.save(buf, format='PNG')
        versions.append((buf.getvalue(), "contrast", {}))
        
        # Sharpened
        sharpened = img.filter(ImageFilter.SHARPEN)
        buf = io.BytesIO()
        sharpened.save(buf, format='PNG')
        versions.append((buf.getvalue(), "sharpened", {}))
        
        return versions
    
    async def _basic_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Basic processing without OpenCV"""
        return [(image_data, "original", {})]

# ═══════════════════════════════════════════════════════════
# ENSEMBLE OCR MANAGER
# ═══════════════════════════════════════════════════════════
class EnsembleOCR:
    """Multi-engine OCR with voting and confidence scoring"""
    
    def __init__(self, cache: UltraCache):
        self.easyocr_reader = None
        self.easy_ready = False
        self.preprocessor = ImagePreprocessor()
        self.executor = ThreadPoolExecutor(max_workers=6)
        self.cache = cache
        self.ocr_space_available = bool(Config.OCR_SPACE_KEY)
        
    async def init_easyocr(self):
        """Initialize EasyOCR with GPU if available"""
        if EASYOCR_AVAILABLE and not self.easy_ready:
            try:
                loop = asyncio.get_event_loop()
                # Try GPU first, fallback to CPU
                try:
                    self.easyocr_reader = await loop.run_in_executor(
                        None, lambda: easyocr.Reader(['en'], gpu=True, verbose=False)
                    )
                    logger.info("✅ EasyOCR ready (GPU)")
                except:
                    self.easyocr_reader = await loop.run_in_executor(
                        None, lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
                    )
                    logger.info("✅ EasyOCR ready (CPU)")
                self.easy_ready = True
            except Exception as e:
                logger.error(f"EasyOCR init: {e}")
    
    async def scan(self, image_data: bytes, hint: str = None) -> Tuple[bool, List[DetectedUser], str, Dict]:
        """
        Ensemble OCR scanning with voting
        Returns: (success, users, combined_text, metadata)
        """
        start_time = time.time()
        
        # Preprocess - generate multiple versions
        versions = await self.preprocessor.preprocess(image_data)
        
        # Run all OCR engines in parallel on all versions
        tasks = []
        
        # EasyOCR on best versions
        if self.easy_ready:
            for img, name, _ in versions[:3]:  # Top 3 versions
                tasks.append(self._run_easyocr(img, name))
        
        # Tesseract on all versions
        if TESSERACT_AVAILABLE:
            for img, name, _ in versions:
                tasks.append(self._run_tesseract(img, name))
        
        # OCR.space as backup
        if self.ocr_space_available:
            tasks.append(self._run_ocrspace(image_data))
        
        # Wait for all with timeout
        results = await asyncio.gather(*tasks, return_exceptions=True)
        results = [r for r in results if isinstance(r, OCRResult)]
        
        if not results:
            return False, [], "", {"error": "All OCR engines failed"}
        
        # Combine all text
        all_texts = [r.text for r in results]
        combined_text = '\n'.join(all_texts)
        
        # Extract users from each result with voting
        all_users = []
        for result in results:
            users = self._extract_users(result.text, hint, result.engine)
            for u in users:
                u.engine = result.engine
                all_users.append(u)
        
        # Vote and deduplicate
        voted_users = self._vote_users(all_users)
        
        # Sort by confidence
        voted_users.sort(key=lambda x: x.confidence, reverse=True)
        
        metadata = {
            "engines_used": [r.engine for r in results],
            "versions_processed": len(versions),
            "processing_time": time.time() - start_time,
            "raw_texts": len(all_texts)
        }
        
        return len(voted_users) > 0, voted_users, combined_text, metadata
    
    async def _run_easyocr(self, image_data: bytes, version_name: str) -> OCRResult:
        """Run EasyOCR"""
        start = time.time()
        
        def _run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, paragraph=True, detail=1)
            text = '\n'.join([r[1] for r in results])
            conf = sum([r[2] for r in results]) / len(results) if results else 0
            return text, conf
        
        loop = asyncio.get_event_loop()
        text, conf = await asyncio.wait_for(
            loop.run_in_executor(self.executor, _run),
            timeout=Config.OCR_TIMEOUT
        )
        
        return OCRResult(text, f"easyocr_{version_name}", conf, time.time() - start)
    
    async def _run_tesseract(self, image_data: bytes, version_name: str) -> OCRResult:
        """Run Tesseract with optimized config"""
        start = time.time()
        
        def _run():
            img = Image.open(io.BytesIO(image_data))
            # Optimized for Roblox usernames: letters, numbers, underscore, @
            config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@'
            text = pytesseract.image_to_string(img, config=config)
            
            # Get confidence scores
            data = pytesseract.image_to_data(img, config=config, output_type=Output.DICT)
            confs = [int(c) for c in data['conf'] if int(c) > 0]
            avg_conf = sum(confs) / len(confs) / 100 if confs else 0.5
            
            return text, avg_conf
        
        loop = asyncio.get_event_loop()
        text, conf = await asyncio.wait_for(
            loop.run_in_executor(self.executor, _run),
            timeout=Config.OCR_TIMEOUT
        )
        
        return OCRResult(text, f"tesseract_{version_name}", conf, time.time() - start)
    
    async def _run_ocrspace(self, image_data: bytes) -> OCRResult:
        """Run OCR.space API as fallback"""
        start = time.time()
        
        try:
            data = FormData()
            data.add_field('file', image_data, filename='image.png', content_type='image/png')
            data.add_field('apikey', Config.OCR_SPACE_KEY)
            data.add_field('OCREngine', '2')  # Engine 2 is better for text
            data.add_field('scale', 'true')
            data.add_field('detectOrientation', 'true')
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.ocr.space/parse/image',
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('ParsedResults'):
                            text = result['ParsedResults'][0].get('ParsedText', '')
                            conf = float(result['ParsedResults'][0].get('FileParseExitCode', 0)) / 100
                            return OCRResult(text, "ocrspace", conf, time.time() - start)
        except Exception as e:
            logger.debug(f"OCR.space error: {e}")
        
        return OCRResult("", "ocrspace", 0, time.time() - start)
    
    def _extract_users(self, text: str, hint: str, engine: str) -> List[DetectedUser]:
        """Extract potential usernames from OCR text"""
        users = []
        lines = text.split('\n')
        
        # Pattern 1: @username (most common)
        for m in re.finditer(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            u = m.group(1)
            if self._validate_username(u):
                conf = 0.95
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                users.append(DetectedUser(u, None, conf, '@mention', engine, text[m.start():m.end()]))
        
        # Pattern 2: DisplayName @username
        for m in re.finditer(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠]\s*([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            d, u = m.groups()
            d = d.strip()
            if self._validate_username(u) and len(d) > 2:
                users.append(DetectedUser(u, d, 0.98, 'display@user', engine, text[m.start():m.end()]))
        
        # Pattern 3: roblox.com/users/ID/profile
        for m in re.finditer(r'roblox\.com/users/(\d+)', text, re.I):
            uid = m.group(1)
            users.append(DetectedUser(f"ID:{uid}", None, 0.99, 'url', engine, text[m.start():m.end()]))
        
        # Pattern 4: Contextual username (with Roblox keywords nearby)
        for i, line in enumerate(lines):
            low = line.lower()
            has_ctx = any(w in low for w in ['roblox', 'profile', 'user', 'display', 'name'])
            
            for m in re.finditer(r'\b([a-zA-Z][a-zA-Z0-9_]{2,19})\b', line):
                u = m.group(1)
                if not self._validate_username(u):
                    continue
                if u.lower() in {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 'friends', 'home', 'settings'}:
                    continue
                
                conf = 0.7 if has_ctx else 0.5
                # Check surrounding lines for context
                surr = ' '.join(lines[max(0,i-2):min(len(lines), i+3)]).lower()
                if any(x in surr for x in ['roblox', '@', 'profile', 'username']):
                    conf = min(conf + 0.15, 0.90)
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                
                users.append(DetectedUser(u, None, conf, 'context', engine, line))
        
        return users
    
    def _validate_username(self, username: str) -> bool:
        """Validate username against Roblox rules"""
        if not username:
            return False
        return bool(Config.USERNAME_REGEX.match(username))
    
    def _vote_users(self, users: List[DetectedUser]) -> List[DetectedUser]:
        """Ensemble voting: boost confidence for users detected by multiple engines"""
        if not users:
            return []
        
        # Group by username (case insensitive)
        groups = {}
        for u in users:
            key = u.username.lower()
            if key not in groups:
                groups[key] = []
            groups[key].append(u)
        
        voted = []
        for username, group in groups.items():
            # Count unique engines
            engines = set(u.engine for u in group)
            engine_count = len(engines)
            
            # Get best confidence
            best_conf = max(u.confidence for u in group)
            
            # Get best display name if any
            display_names = [u.display_name for u in group if u.display_name]
            best_display = display_names[0] if display_names else None
            
            # Boost confidence based on engine agreement
            # More engines = higher confidence
            boost = min((engine_count - 1) * 0.1, 0.2)
            final_conf = min(best_conf + boost, 1.0)
            
            voted.append(DetectedUser(
                username=group[0].username,
                display_name=best_display,
                confidence=final_conf,
                source=f"voted_{engine_count}engines",
                engine="ensemble",
                raw_text=group[0].raw_text
            ))
        
        return voted

# ═══════════════════════════════════════════════════════════
# ROBLOX API
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: UltraCache):
        self.cache = cache
        self.session = None
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            connector=TCPConnector(limit=100, limit_per_host=30),
            timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        """Verify detected users against Roblox API"""
        verified = []
        
        for user in users[:5]:  # Check top 5
            # Check cache
            cached = await self.cache.get(f"u:{user.username.lower()}")
            if cached:
                verified.append({
                    'profile': cached,
                    'detected': user,
                    'score': user.confidence,
                    'cached': True
                })
                continue
            
            # Fetch from API
            profile = await self._fetch_user(user.username)
            if profile:
                await self.cache.set(f"u:{user.username.lower()}", profile, 600)
                verified.append({
                    'profile': profile,
                    'detected': user,
                    'score': user.confidence,
                    'cached': False
                })
        
        # Sort by confidence score
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, username: str) -> Optional[Dict]:
        """Fetch user by username or ID"""
        try:
            if username.startswith("ID:"):
                return await self._fetch_by_id(int(username.split(":")[1]))
            
            # Username lookup
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [username], "excludeBannedUsers": False}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data.get('data'):
                    return None
                return await self._fetch_by_id(data['data'][0]['id'])
                
        except Exception as e:
            logger.debug(f"Fetch user error: {e}")
            return None
    
    async def _fetch_by_id(self, user_id: int) -> Optional[Dict]:
        """Fetch user details by ID"""
        try:
            async with self.session.get(f'https://users.roblox.com/v1/users/{user_id}') as resp:
                if resp.status != 200:
                    return None
                profile = await resp.json()
                profile['thumbnailUrl'] = await self._get_avatar(user_id)
                return profile
        except Exception as e:
            logger.debug(f"Fetch by ID error: {e}")
            return None
    
    async def _get_avatar(self, user_id: int) -> Optional[str]:
        """Get avatar thumbnail"""
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
                            await self.cache.set(f"a:{user_id}", url, 1800)
                        return url
        except:
            pass
        return None
    
    async def search_similar(self, username: str) -> List[Dict]:
        """Search for similar usernames"""
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5'
            ) as resp:
                if resp.status == 200:
                    return (await resp.json()).get('data', [])
        except:
            pass
        return []

# ═══════════════════════════════════════════════════════════
# WEBHOOK MANAGER - BEAUTIFUL EMBEDS
# ═══════════════════════════════════════════════════════════
class WebhookManager:
    """Beautiful webhook notifications"""
    
    def __init__(self):
        self.url = Config.WEBHOOK_URL
        self.session = None
    
    async def setup(self):
        if self.url:
            self.session = aiohttp.ClientSession()
            logger.info("✅ Webhook manager ready")
    
    async def send_scan_result(self, user: discord.User, profile: Dict, detected: DetectedUser, image_url: str, processing_time: float):
        """Send beautiful scan result to webhook"""
        if not self.url or not self.session:
            return
        
        try:
            # Color based on confidence
            if detected.confidence >= 0.95:
                color = 0x00FF00  # Green
                status = "✅ CERTAIN"
            elif detected.confidence >= 0.80:
                color = 0x55FF55  # Light green
                status = "✓ HIGH"
            elif detected.confidence >= 0.60:
                color = 0xFFAA00  # Orange
                status = "⚠ MEDIUM"
            else:
                color = 0xFF5555  # Red
                status = "? LOW"
            
            embed = {
                "title": f"🔍 Scan Result: {profile.get('displayName', profile['name'])}",
                "description": f"**@{profile['name']}** detected with `{detected.confidence:.0%}` confidence",
                "url": f"https://roblox.com/users/{profile['id']}/profile",
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "thumbnail": {
                    "url": profile.get('thumbnailUrl', 'https://tr.rbxcdn.com/avatar-default.png')
                },
                "image": {
                    "url": image_url
                },
                "author": {
                    "name": f"Scanned by {user.name}",
                    "icon_url": str(user.display_avatar.url) if user.display_avatar else None
                },
                "fields": [
                    {
                        "name": "🆔 User ID",
                        "value": f"`{profile['id']}`",
                        "inline": True
                    },
                    {
                        "name": "📊 Confidence",
                        "value": f"`{detected.confidence:.0%}` {status}",
                        "inline": True
                    },
                    {
                        "name": "🔎 Detection Source",
                        "value": f"`{detected.source}`",
                        "inline": True
                    },
                    {
                        "name": "⚡ Processing Time",
                        "value": f"`{processing_time:.2f}s`",
                        "inline": True
                    },
                    {
                        "name": "🤖 Detection Engine",
                        "value": f"`{detected.engine}`",
                        "inline": True
                    },
                    {
                        "name": "📅 Account Created",
                        "value": f"`{str(profile.get('created', 'Unknown'))[:10]}`",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "TRUE OMEGA v5.0 | Ultimate Scanner",
                    "icon_url": "https://i.imgur.com/4M34hi2.png"
                }
            }
            
            # Add description if exists
            if profile.get('description'):
                desc = profile['description'][:200]
                if len(profile['description']) > 200:
                    desc += "..."
                embed["fields"].append({
                    "name": "📝 About",
                    "value": desc,
                    "inline": False
                })
            
            payload = {
                "username": "TRUE OMEGA Scanner",
                "avatar_url": "https://i.imgur.com/4M34hi2.png",
                "embeds": [embed]
            }
            
            async with self.session.post(self.url, json=payload) as resp:
                if resp.status not in (200, 204):
                    logger.warning(f"Webhook failed: {resp.status}")
                    
        except Exception as e:
            logger.error(f"Webhook error: {e}")
    
    async def send_error(self, error: str, user: discord.User = None):
        """Send error notification"""
        if not self.url or not self.session:
            return
        
        try:
            embed = {
                "title": "❌ Scanner Error",
                "description": error[:2000],
                "color": 0xFF0000,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            if user:
                embed["author"] = {
                    "name": f"Requested by {user.name}",
                    "icon_url": str(user.display_avatar.url) if user.display_avatar else None
                }
            
            payload = {
                "username": "TRUE OMEGA Errors",
                "embeds": [embed]
            }
            
            await self.session.post(self.url, json=payload)
        except:
            pass

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
class Database:
    def __init__(self):
        self.pool = None
        self.whitelist: Set[str] = set()
        os.makedirs("data", exist_ok=True)
        os.makedirs("downloads", exist_ok=True)
        
    async def setup(self):
        if DB_AVAILABLE and Config.DATABASE_URL:
            try:
                self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=1, max_size=5)
                async with self.pool.acquire() as conn:
                    await conn.execute("CREATE TABLE IF NOT EXISTS whitelist (user_id TEXT PRIMARY KEY)")
                    await conn.execute("CREATE TABLE IF NOT EXISTS stats (user_id TEXT PRIMARY KEY, data JSONB)")
            except Exception as e:
                logger.warning(f"DB: {e}")
        
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
    
    async def add_whitelist(self, uid: str) -> bool:
        uid = str(uid)
        if uid in self.whitelist:
            return False
        self.whitelist.add(uid)
        await self._save_whitelist()
        return True
    
    async def remove_whitelist(self, uid: str) -> bool:
        uid = str(uid)
        if uid not in self.whitelist or uid == Config.OWNER_ID:
            return False
        self.whitelist.discard(uid)
        await self._save_whitelist()
        return True
    
    async def _save_whitelist(self):
        try:
            with open("data/whitelist.json", 'w') as f:
                json.dump({'users': list(self.whitelist)}, f)
        except:
            pass
    
    async def get_stats(self, uid: str) -> Dict:
        try:
            path = f"data/{uid}.json"
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        except:
            pass
        return {'total': 0, 'success': 0, 'favorites': []}
    
    async def save_stats(self, uid: str, data: Dict):
        try:
            with open(f"data/{uid}.json", 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    async def save_download(self, uid: str, profile: Dict, image_data: bytes) -> str:
        """Save profile image to downloads folder"""
        try:
            filename = f"{profile['name']}_{profile['id']}.png"
            filepath = f"downloads/{filename}"
            
            # Save image
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            # Save metadata
            meta = {
                'username': profile['name'],
                'user_id': profile['id'],
                'display_name': profile.get('displayName'),
                'downloaded_by': uid,
                'timestamp': datetime.utcnow().isoformat(),
                'filename': filename
            }
            
            with open(f"downloads/{profile['name']}_{profile['id']}.json", 'w') as f:
                json.dump(meta, f)
            
            return filename
        except Exception as e:
            logger.error(f"Save download error: {e}")
            return None

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
# BOT - ULTIMATE VERSION
# ═══════════════════════════════════════════════════════════
class OmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.cache = UltraCache()
        self.limiter = RateLimiter(Config.RATE_LIMIT, 60)
        self.ocr = EnsembleOCR(self.cache)
        self.roblox = None
        self.webhook = WebhookManager()
        self.scan_sem = asyncio.Semaphore(50)
        
    async def setup_hook(self):
        logger.info("🔧 Starting ULTIMATE OMEGA...")
        await self.cache.setup()
        await self.db.setup()
        await self.webhook.setup()
        self.roblox = RobloxAPI(self.cache)
        await self.roblox.setup()
        await self.ocr.init_easyocr()
        self._register_cmds()
        await self._sync()
        logger.info("✅ ULTIMATE OMEGA Ready!")
    
    def _register_cmds(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username (ULTIMATE)")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download user profile data")
        @app_commands.describe(username="Roblox username to download")
        async def download(interaction: discord.Interaction, username: str):
            await self.cmd_download(interaction, username)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (owner only)")
        @app_commands.describe(user="User ID to add/remove")
        async def whitelist(interaction: discord.Interaction, user: str):
            await self.cmd_whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search Roblox by username")
        @app_commands.describe(username="Username to search")
        async def search(interaction: discord.Interaction, username: str):
            await self.cmd_search(interaction, username)
        
        @self.tree.command(name="stats", description="📊 View your scan statistics")
        async def stats(interaction: discord.Interaction):
            await self.cmd_stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Check bot status and latency")
        async def ping(interaction: discord.Interaction):
            await self.cmd_ping(interaction)
        
        @self.tree.command(name="cache", description="📈 View cache statistics (owner)")
        async def cache_stats(interaction: discord.Interaction):
            await self.cmd_cache(interaction)
    
    async def _sync(self):
        for _ in range(3):
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} commands")
                return
            except Exception as e:
                logger.error(f"Sync: {e}")
                await asyncio.sleep(5)
    
    async def cmd_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        """ULTIMATE scan command with ensemble OCR"""
        uid = str(interaction.user.id)
        start_time = time.time()
        
        # Checks
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Not Whitelisted", description="Contact the bot owner for access.", color=0xFF0000),
                ephemeral=True
            )
            return
        
        allowed, retry = await self.limiter.check(uid)
        if not allowed:
            await interaction.response.send_message(
                embed=discord.Embed(title="⏰ Rate Limited", description=f"Try again in {int(retry)}s", color=0xFFA500),
                ephemeral=True
            )
            return
        
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ File Too Large", description="Max 25MB", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        async with self.scan_sem:
            try:
                # Download image
                dl_start = time.time()
                async with self.roblox.session.get(image.url, timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download Failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
                dl_time = time.time() - dl_start
                
                # ULTIMATE OCR SCAN
                ocr_start = time.time()
                success, users, raw_text, meta = await self.ocr.scan(img_data, hint)
                ocr_time = time.time() - ocr_start
                
                if not success:
                    embed = discord.Embed(
                        title="❌ No Username Detected",
                        description="Could not detect any valid Roblox username in this image.",
                        color=0xFF6B6B
                    )
                    embed.add_field(name="Engines Used", value=f"```{', '.join(meta.get('engines_used', []))}```", inline=False)
                    embed.add_field(name="Tip", value="Try using the `hint` parameter or upload a clearer image.", inline=False)
                    await interaction.followup.send(embed=embed)
                    return
                
                # Verify with Roblox API
                api_start = time.time()
                verified = await self.roblox.verify_users(users)
                api_time = time.time() - api_start
                
                if not verified:
                    # Try to find similar users
                    similar = await self.roblox.search_similar(users[0].username)
                    embed = discord.Embed(
                        title="❌ User Not Found",
                        description=f"Detected `@{users[0].username}` but it doesn't exist on Roblox.",
                        color=0xFF6B6B
                    )
                    if similar:
                        sim_text = '\n'.join([f"• {s.get('displayName', s['name'])} (@{s['name']})" for s in similar[:5]])
                        embed.add_field(name="Did you mean?", value=sim_text, inline=False)
                    embed.add_field(name="Raw Detection", value=f"```{users[0].raw_text[:100]}```", inline=False)
                    await interaction.followup.send(embed=embed)
                    return
                
                # SUCCESS
                best = verified[0]
                prof = best['profile']
                det = best['detected']
                total_time = time.time() - start_time
                
                # Create beautiful embed
                embed = self._make_result_embed(prof, det, dl_time, ocr_time, api_time, total_time, meta)
                embed.set_image(url=image.url)
                
                view = ResultView(prof, self, uid)
                await interaction.followup.send(embed=embed, view=view)
                
                # Send to webhook
                await self.webhook.send_scan_result(
                    interaction.user, prof, det, image.url, total_time
                )
                
                # Update stats
                await self._update_stats(uid, prof['name'])
                
            except Exception as e:
                logger.error(f"Scan error: {traceback.format_exc()}")
                await self.webhook.send_error(str(e), interaction.user)
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
                )
    
    def _make_result_embed(self, prof: Dict, det: DetectedUser, dl_t: float, ocr_t: float, api_t: float, total_t: float, meta: Dict) -> discord.Embed:
        """Create beautiful result embed"""
        score = det.confidence
        
        if prof.get('isBanned'):
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
            title=f"{prof.get('displayName', prof['name'])}",
            url=f"https://roblox.com/users/{prof['id']}/profile",
            description=f"**@{prof['name']}** | `{score:.0%}` {status}",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # Detection info
        embed.add_field(name="🎯 Confidence", value=f"`{score:.0%}`", inline=True)
        embed.add_field(name="🔍 Source", value=f"`{det.source}`", inline=True)
        embed.add_field(name="🤖 Engine", value=f"`{det.engine}`", inline=True)
        
        # User details
        embed.add_field(name="🆔 User ID", value=f"`{prof['id']}`", inline=True)
        embed.add_field(name="📅 Created", value=f"`{str(prof.get('created', 'Unknown'))[:10]}`", inline=True)
        embed.add_field(name="✅ Verified", value=f"{'✓' if not det.engine == 'ensemble' else '⚡'}", inline=True)
        
        # Performance
        perf_text = f"⬇️ `{dl_t:.2f}s` | 🔍 `{ocr_t:.2f}s` | 🌐 `{api_t:.2f}s` | ⚡ `{total_t:.2f}s`"
        embed.add_field(name="⚡ Performance", value=perf_text, inline=False)
        
        # OCR Metadata
        if meta.get('engines_used'):
            engines = ', '.join(meta['engines_used'][:3])
            embed.add_field(name="🧠 OCR Engines", value=f"`{engines}`", inline=True)
        
        if prof.get('description'):
            desc = prof['description'][:150] + "..." if len(prof['description']) > 150 else prof['description']
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        if prof.get('thumbnailUrl'):
            embed.set_thumbnail(url=prof['thumbnailUrl'])
        
        embed.set_footer(text="TRUE OMEGA v5.0 ULTIMATE | Click buttons below")
        return embed
    
    async def cmd_download(self, interaction: discord.Interaction, username: str):
        """Download user profile and avatar"""
        uid = str(interaction.user.id)
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Get user
            users = [DetectedUser(username, None, 1.0, "download")]
            verified = await self.roblox.verify_users(users)
            
            if not verified:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ User Not Found", color=0xFF0000)
                )
                return
            
            prof = verified[0]['profile']
            
            # Download avatar
            avatar_data = None
            if prof.get('thumbnailUrl'):
                async with self.roblox.session.get(prof['thumbnailUrl']) as resp:
                    if resp.status == 200:
                        avatar_data = await resp.read()
            
            # Save to disk
            filename = await self.db.save_download(uid, prof, avatar_data or b'')
            
            # Create embed
            embed = discord.Embed(
                title=f"📥 Downloaded: {prof.get('displayName', prof['name'])}",
                description=f"**@{prof['name']}** saved to database",
                color=0x00D4AA
            )
            embed.add_field(name="🆔 User ID", value=f"`{prof['id']}`", inline=True)
            embed.add_field(name="📁 Filename", value=f"`{filename}`", inline=True)
            embed.add_field(name="📅 Created", value=f"`{str(prof.get('created', 'Unknown'))[:10]}`", inline=True)
            
            if avatar_data:
                # Send file
                file = discord.File(io.BytesIO(avatar_data), filename=f"{prof['name']}_avatar.png")
                embed.set_image(url=f"attachment://{prof['name']}_avatar.png")
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Download Failed", description=str(e)[:200], color=0xFF0000)
            )
    
    async def cmd_whitelist(self, interaction: discord.Interaction, user: str):
        """Manage whitelist"""
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
            if await self.db.remove_whitelist(target):
                await interaction.followup.send(
                    embed=discord.Embed(title=f"✅ Removed {target}", color=0x00FF00)
                )
            else:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Cannot Remove Owner", color=0xFF0000)
                )
        else:
            if await self.db.add_whitelist(target):
                await interaction.followup.send(
                    embed=discord.Embed(title=f"✅ Added {target}", color=0x00FF00)
                )
            else:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Already Whitelisted", color=0xFFA500)
                )
    
    async def cmd_search(self, interaction: discord.Interaction, username: str):
        """Search by username"""
        if not self.db.is_whitelisted(str(interaction.user.id)):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        users = [DetectedUser(username, None, 1.0, "search")]
        verified = await self.roblox.verify_users(users)
        
        if verified:
            best = verified[0]
            embed = self._make_result_embed(
                best['profile'], 
                users[0], 
                0.1, 0.1, 0.1, 0.3,
                {'engines_used': ['direct_search']}
            )
            view = ResultView(best['profile'], self, str(interaction.user.id))
            await interaction.followup.send(embed=embed, view=view)
        else:
            similar = await self.roblox.search_similar(username)
            embed = discord.Embed(title="❌ Not Found", description=f"`@{username}` not found.", color=0xFF0000)
            if similar:
                embed.add_field(
                    name="Similar Users",
                    value='\n'.join([f"• {s.get('displayName', s['name'])} (@{s['name']})" for s in similar[:5]]),
                    inline=False
                )
            await interaction.followup.send(embed=embed)
    
    async def cmd_stats(self, interaction: discord.Interaction):
        """Show user stats"""
        stats = await self.db.get_stats(str(interaction.user.id))
        total = stats.get('total', 0)
        success = stats.get('success', 0)
        rate = (success / total * 100) if total > 0 else 0
        
        embed = discord.Embed(title="📊 Your Statistics", color=0x00D4AA)
        embed.add_field(name="🔍 Total Scans", value=str(total), inline=True)
        embed.add_field(name="✅ Successful", value=str(success), inline=True)
        embed.add_field(name="📈 Success Rate", value=f"{rate:.1f}%", inline=True)
        
        favs = stats.get('favorites', [])
        if favs:
            embed.add_field(
                name="⭐ Favorites",
                value='\n'.join([f"• @{u}" for u in favs[:5]]),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        """Ping command"""
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"`{round(self.latency * 1000)}ms`", inline=True)
        embed.add_field(name="Whitelisted", value=f"`{len(self.db.whitelist)}`", inline=True)
        embed.add_field(name="Cache", value=f"`{self.cache.stats()}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_cache(self, interaction: discord.Interaction):
        """Cache stats (owner only)"""
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message("⛔ Owner only", ephemeral=True)
            return
        
        stats = self.cache.stats()
        embed = discord.Embed(title="📈 Cache Statistics", description=stats, color=0x00D4AA)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _update_stats(self, uid: str, username: str):
        """Update user statistics"""
        stats = await self.db.get_stats(uid)
        stats['total'] = stats.get('total', 0) + 1
        stats['success'] = stats.get('success', 0) + 1
        if username not in stats.get('favorites', []):
            stats['favorites'] = [username] + stats.get('favorites', [])[:9]
        await self.db.save_stats(uid, stats)

# ═══════════════════════════════════════════════════════════
# RESULT VIEW
# ═══════════════════════════════════════════════════════════
class ResultView(discord.ui.View):
    def __init__(self, profile: Dict, bot: OmegaBot, user_id: str):
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
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="⭐")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Save to favorites"""
        stats = await self.bot.db.get_stats(self.user_id)
        
        if self.profile['name'] in stats.get('favorites', []):
            await interaction.response.send_message(
                embed=discord.Embed(title="⭐ Already Saved", color=0xFFA500),
                ephemeral=True
            )
            return
        
        stats['favorites'] = [self.profile['name']] + stats.get('favorites', [])[:9]
        await self.bot.db.save_stats(self.user_id, stats)
        await interaction.response.send_message(
            embed=discord.Embed(title=f"⭐ Saved @{self.profile['name']}!", color=0x00FF00),
            ephemeral=True
        )
    
    @discord.ui.button(label="Download", style=discord.ButtonStyle.primary, emoji="📥")
    async def download(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Quick download"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get avatar
            avatar_data = None
            if self.profile.get('thumbnailUrl'):
                async with self.bot.roblox.session.get(self.profile['thumbnailUrl']) as resp:
                    if resp.status == 200:
                        avatar_data = await resp.read()
            
            # Save
            filename = await self.bot.db.save_download(self.user_id, self.profile, avatar_data or b'')
            
            embed = discord.Embed(
                title="📥 Downloaded",
                description=f"Saved as `{filename}`",
                color=0x00D4AA
            )
            
            if avatar_data:
                file = discord.File(io.BytesIO(avatar_data), filename=f"{self.profile['name']}_avatar.png")
                await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=str(e)[:100], color=0xFF0000),
                ephemeral=True
            )

# ═══════════════════════════════════════════════════════════
# HEALTH SERVER
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text='ULTIMATE OMEGA OK'))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080))).start()

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
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
