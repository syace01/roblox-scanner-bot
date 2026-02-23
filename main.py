"""
🚀 TRUE OMEGA v6.1 - STABLE HYPER SCANNER + VIDEO DOWNLOADER
Fixed: Graceful fallback, no hard dependencies, proper error handling
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
from collections import defaultdict
import logging

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("omega")

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    DOWNLOAD_TIMEOUT = 15
    OCR_TIMEOUT = 5
    API_TIMEOUT = 5
    VIDEO_TIMEOUT = 120
    
    MAX_FILE_SIZE = 100 * 1024 * 1024
    RATE_LIMIT = 50
    
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$')
    
    VIDEO_DOMAINS = [
        'medal.tv', 'streamable.com', 'youtube.com', 'youtu.be',
        'twitter.com', 'x.com', 'reddit.com', 'tiktok.com',
        'instagram.com', 'facebook.com', 'twitch.tv'
    ]

Config.validate = lambda: logger.info(f"✅ Config loaded | Owner: {Config.OWNER_ID}") or None if Config.TOKEN else logger.error("❌ No DISCORD_TOKEN") or sys.exit(1)
Config.validate()

# ═══════════════════════════════════════════════════════════
# IMPORTS WITH GRACEFUL FALLBACK
# ═══════════════════════════════════════════════════════════
import aiohttp
from aiohttp import TCPConnector, FormData
import discord
from discord import app_commands

# PIL - Required
try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.error("❌ PIL not available - Scanner will not work")

# Tesseract - Optional
try:
    import pytesseract
    from pytesseract import Output
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("⚠️ Tesseract not available")

# EasyOCR - Optional (GPU heavy, might crash)
EASYOCR_AVAILABLE = False
easyocr_reader = None
try:
    import easyocr
    # Don't initialize here - do it lazily
    EASYOCR_AVAILABLE = True
    logger.info("✅ EasyOCR available (will initialize on first use)")
except ImportError:
    logger.warning("⚠️ EasyOCR not available")

# OpenCV - Optional but recommended
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("⚠️ OpenCV not available")

# Database - Optional
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
# SIMPLE CACHE
# ═══════════════════════════════════════════════════════════
class SimpleCache:
    def __init__(self, maxsize=10000):
        self._cache = {}
        self._expiry = {}
        self.maxsize = maxsize
        self._hits = 0
        self._misses = 0
        self.redis = None
        
    async def setup(self):
        if REDIS_AVAILABLE and Config.REDIS_URL:
            try:
                self.redis = await redis.from_url(Config.REDIS_URL, decode_responses=True)
                await self.redis.ping()
                logger.info("✅ Redis connected")
            except Exception as e:
                logger.warning(f"Redis failed: {e}")
    
    async def get(self, key: str):
        now = time.time()
        
        if key in self._cache and now < self._expiry.get(key, 0):
            self._hits += 1
            return self._cache[key]
        
        if self.redis:
            try:
                data = await self.redis.get(f"o:{key}")
                if data:
                    val = json.loads(data)
                    self._cache[key] = val
                    self._expiry[key] = now + 300
                    self._hits += 1
                    return val
            except:
                pass
        
        self._misses += 1
        return None
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        now = time.time()
        self._cache[key] = value
        self._expiry[key] = now + min(ttl, 600)
        
        # Simple eviction
        if len(self._cache) > self.maxsize:
            # Remove 10% oldest
            sorted_items = sorted(self._expiry.items(), key=lambda x: x[1])
            for k, _ in sorted_items[:self.maxsize // 10]:
                self._cache.pop(k, None)
                self._expiry.pop(k, None)
        
        if self.redis:
            try:
                await self.redis.setex(f"o:{key}", ttl, json.dumps(value))
            except:
                pass
    
    def stats(self):
        total = self._hits + self._misses
        rate = (self._hits / total * 100) if total > 0 else 0
        return f"{self._hits} hits, {self._misses} misses ({rate:.1f}%)"

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

@dataclass
class VideoInfo:
    url: str
    title: str
    duration: str
    uploader: str
    thumbnail: Optional[str]
    filesize: Optional[int]

# ═══════════════════════════════════════════════════════════
# STABLE OCR - FAILSAFE DESIGN
# ═══════════════════════════════════════════════════════════
class StableOCR:
    """OCR that always works - falls back gracefully"""
    
    def __init__(self, cache: SimpleCache):
        self.cache = cache
        self.easyocr_reader = None
        self.easyocr_ready = False
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.ocr_space_available = bool(Config.OCR_SPACE_KEY)
        self._username_patterns = self._compile_patterns()
        
    def _compile_patterns(self) -> Dict[str, re.Pattern]:
        return {
            'mention': re.compile(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'display_user': re.compile(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠]\s*([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'roblox_url': re.compile(r'roblox\.com/users/(\d+)', re.I),
            'username': re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'display_name': re.compile(r'Display\s*Name\s*:?\s*([A-Za-z][A-Za-z0-9_\s]{2,20})', re.I),
        }
    
    async def init_engines(self):
        """Initialize EasyOCR lazily and safely"""
        if EASYOCR_AVAILABLE and not self.easyocr_ready:
            try:
                loop = asyncio.get_event_loop()
                # Try GPU first, fallback to CPU
                try:
                    self.easyocr_reader = await asyncio.wait_for(
                        loop.run_in_executor(
                            self.executor,
                            lambda: __import__('easyocr').Reader(['en'], gpu=True, verbose=False)
                        ),
                        timeout=30
                    )
                    logger.info("✅ EasyOCR GPU ready")
                except Exception:
                    self.easyocr_reader = await asyncio.wait_for(
                        loop.run_in_executor(
                            self.executor,
                            lambda: __import__('easyocr').Reader(['en'], gpu=False, verbose=False)
                        ),
                        timeout=30
                    )
                    logger.info("✅ EasyOCR CPU ready")
                self.easyocr_ready = True
            except Exception as e:
                logger.warning(f"⚠️ EasyOCR init failed: {e}")
                self.easyocr_ready = False
    
    async def scan(self, image_data: bytes, hint: str = None) -> Tuple[bool, List[DetectedUser], str, Dict]:
        """Scan with multiple engines, return best result"""
        start_time = time.time()
        
        # Check cache
        cache_key = hashlib.md5(image_data).hexdigest()
        cached = await self.cache.get(f"ocr:{cache_key}")
        if cached:
            users = [DetectedUser(**u) for u in cached.get('users', [])]
            return len(users) > 0, users, cached.get('text', ''), {"cached": True, "time": 0}
        
        if not PIL_AVAILABLE:
            return False, [], "", {"error": "PIL not available"}
        
        # Preprocess
        versions = await self._preprocess(image_data)
        
        # Run OCR engines with timeouts
        results = []
        
        # 1. EasyOCR (if available)
        if self.easyocr_ready:
            try:
                result = await asyncio.wait_for(
                    self._run_easyocr(versions[0][0]),
                    timeout=Config.OCR_TIMEOUT
                )
                if result and result.text.strip():
                    results.append(result)
            except Exception as e:
                logger.debug(f"EasyOCR failed: {e}")
        
        # 2. Tesseract (if available)
        if TESSERACT_AVAILABLE:
            try:
                result = await asyncio.wait_for(
                    self._run_tesseract(versions[0][0]),
                    timeout=Config.OCR_TIMEOUT
                )
                if result and result.text.strip():
                    results.append(result)
            except Exception as e:
                logger.debug(f"Tesseract failed: {e}")
        
        # 3. OCR.space (if available)
        if self.ocr_space_available and len(results) < 2:
            try:
                result = await asyncio.wait_for(
                    self._run_ocrspace(image_data),
                    timeout=Config.OCR_TIMEOUT + 3
                )
                if result and result.text.strip():
                    results.append(result)
            except Exception as e:
                logger.debug(f"OCR.space failed: {e}")
        
        if not results:
            return False, [], "", {"error": "All OCR engines failed", "time": time.time() - start_time}
        
        # Extract users from all results
        all_users = []
        for result in results:
            users = self._extract_users(result, hint)
            all_users.extend(users)
        
        # Vote and deduplicate
        voted = self._vote_users(all_users, hint)
        
        # Cache
        if voted:
            await self.cache.set(f"ocr:{cache_key}", {
                'users': [{'username': u.username, 'display_name': u.display_name,
                          'confidence': u.confidence, 'source': u.source,
                          'engine': u.engine, 'raw_text': u.raw_text} for u in voted],
                'text': '\n'.join(r.text for r in results)
            }, 3600)
        
        total_time = time.time() - start_time
        return len(voted) > 0, voted, '\n'.join(r.text for r in results), {
            "engines_used": [r.engine for r in results],
            "time": total_time,
            "users_found": len(voted)
        }
    
    async def _preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        """Simple, fast preprocessing"""
        if not CV2_AVAILABLE:
            # PIL fallback
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            versions = []
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            versions.append((buf.getvalue(), "original", {}))
            
            # Enhance
            enhanced = ImageEnhance.Contrast(img).enhance(2.0)
            buf = io.BytesIO()
            enhanced.save(buf, format='PNG')
            versions.append((buf.getvalue(), "contrast", {}))
            
            return versions
        
        # OpenCV preprocessing
        def _process():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return [(image_data, "original", {})]
            
            versions = []
            h, w = img.shape[:2]
            
            # Original
            _, buf = cv2.imencode('.png', img)
            versions.append((buf.tobytes(), "original", {"size": (h, w)}))
            
            # Grayscale + CLAHE
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            _, buf = cv2.imencode('.png', enhanced)
            versions.append((buf.tobytes(), "enhanced", {"size": enhanced.shape}))
            
            # Upscale if small
            if w < 800:
                scaled = cv2.resize(gray, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
                _, buf = cv2.imencode('.png', scaled)
                versions.append((buf.tobytes(), "upscaled", {"size": scaled.shape}))
            
            return versions
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, _process)
    
    async def _run_easyocr(self, image_data: bytes) -> OCRResult:
        start = time.time()
        
        def _run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, detail=1)
            texts = [r[1] for r in results]
            confs = [r[2] for r in results]
            full_text = ' '.join(texts)
            avg_conf = sum(confs) / len(confs) if confs else 0.5
            return full_text, avg_conf
        
        loop = asyncio.get_event_loop()
        text, conf = await loop.run_in_executor(self.executor, _run)
        return OCRResult(text, "easyocr", conf, time.time() - start)
    
    async def _run_tesseract(self, image_data: bytes) -> OCRResult:
        start = time.time()
        
        def _run():
            img = Image.open(io.BytesIO(image_data))
            config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@'
            text = pytesseract.image_to_string(img, config=config)
            
            data = pytesseract.image_to_data(img, config=config, output_type=Output.DICT)
            confs = [int(c) for c in data['conf'] if int(c) > 0]
            avg_conf = sum(confs) / len(confs) / 100 if confs else 0.5
            
            return text, avg_conf
        
        loop = asyncio.get_event_loop()
        text, conf = await loop.run_in_executor(self.executor, _run)
        return OCRResult(text, "tesseract", conf, time.time() - start)
    
    async def _run_ocrspace(self, image_data: bytes) -> OCRResult:
        start = time.time()
        
        data = FormData()
        data.add_field('file', image_data, filename='image.png', content_type='image/png')
        data.add_field('apikey', Config.OCR_SPACE_KEY)
        data.add_field('OCREngine', '2')
        data.add_field('scale', 'true')
        
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
        
        return OCRResult("", "ocrspace", 0, time.time() - start)
    
    def _extract_users(self, result: OCRResult, hint: str) -> List[DetectedUser]:
        """Extract usernames from OCR text"""
        text = result.text
        users = []
        lines = text.split('\n')
        lower_text = text.lower()
        
        # Pattern 1: @username
        for m in self._username_patterns['mention'].finditer(text):
            u = m.group(1)
            if self._validate_username(u):
                conf = 0.95 if not (hint and u.lower() != hint.lower().lstrip('@')) else 0.98
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                users.append(DetectedUser(u, None, conf, '@mention', result.engine, text[m.start():m.end()]))
        
        # Pattern 2: Display Name @username
        for m in self._username_patterns['display_user'].finditer(text):
            d, u = m.groups()
            d = d.strip()
            if self._validate_username(u) and len(d) > 2:
                users.append(DetectedUser(u, d, 0.97, 'display@user', result.engine, text[m.start():m.end()]))
        
        # Pattern 3: Roblox URL
        for m in self._username_patterns['roblox_url'].finditer(text):
            uid = m.group(1)
            users.append(DetectedUser(f"ID:{uid}", None, 0.99, 'url', result.engine, text[m.start():m.end()]))
        
        # Pattern 4: Contextual
        context_words = ['roblox', 'profile', 'user', 'display', 'name', '@']
        has_context = any(w in lower_text for w in context_words)
        
        for i, line in enumerate(lines):
            line_lower = line.lower()
            line_context = has_context or any(w in line_lower for w in context_words)
            
            for m in self._username_patterns['username'].finditer(line):
                u = m.group(1)
                if not self._validate_username(u):
                    continue
                if u.lower() in {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 'friends', 'home'}:
                    continue
                
                conf = 0.7 if line_context else 0.5
                
                # Context boost
                surrounding = ' '.join(lines[max(0,i-2):min(len(lines), i+3)]).lower()
                if any(w in surrounding for w in context_words):
                    conf += 0.1
                
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                
                users.append(DetectedUser(u, None, min(conf, 0.9), 'context', result.engine, line))
        
        # Pattern 5: Display Name label
        for m in self._username_patterns['display_name'].finditer(text):
            d = m.group(1).strip()
            if len(d) > 2:
                nearby = text[max(0, m.start()-100):min(len(text), m.end()+100)]
                for um in self._username_patterns['username'].finditer(nearby):
                    u = um.group(1)
                    if self._validate_username(u) and u.lower() not in {'roblox', 'profile'}:
                        users.append(DetectedUser(u, d, 0.92, 'display_label', result.engine, text[m.start():m.end()]))
                        break
        
        return users
    
    def _validate_username(self, username: str) -> bool:
        if not username:
            return False
        return bool(Config.USERNAME_REGEX.match(username))
    
    def _vote_users(self, users: List[DetectedUser], hint: str) -> List[DetectedUser]:
        """Smart voting with deduplication"""
        if not users:
            return []
        
        # Group by username
        groups = defaultdict(list)
        for u in users:
            groups[u.username.lower()].append(u)
        
        voted = []
        for username, group in groups.items():
            engines = set(u.engine for u in group)
            best = max(group, key=lambda x: x.confidence)
            
            # Boost for hint match
            hint_boost = 0.15 if (hint and username == hint.lower().lstrip('@')) else 0
            engine_boost = (len(engines) - 1) * 0.05
            
            final_conf = min(best.confidence + hint_boost + engine_boost, 1.0)
            
            display_names = [u.display_name for u in group if u.display_name]
            best_display = display_names[0] if display_names else best.display_name
            
            voted.append(DetectedUser(
                username=best.username,
                display_name=best_display,
                confidence=final_conf,
                source=best.source,
                engine=f"multi_{len(engines)}" if len(engines) > 1 else best.engine,
                raw_text=best.raw_text[:100]
            ))
        
        # Sort by confidence
        voted.sort(key=lambda x: x.confidence, reverse=True)
        
        # Remove similar names
        filtered = []
        for u in voted:
            if not any(self._similar(u.username, f.username) for f in filtered):
                filtered.append(u)
        
        return filtered[:5]
    
    def _similar(self, a: str, b: str) -> bool:
        """Check if names are similar"""
        if a.lower() == b.lower():
            return True
        return False

# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER (STABLE)
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
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
            return False, "Download timeout", None, None
    
    def _run_download(self, url: str, output_path: str) -> Tuple[bool, str, Optional[VideoInfo]]:
        try:
            # Get info
            result = subprocess.run(
                ['yt-dlp', '--dump-json', '--no-download', url],
                capture_output=True, text=True, timeout=20
            )
            
            if result.returncode != 0:
                return False, f"Info failed", None
            
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
            result = subprocess.run(
                ['yt-dlp', '-f', 'best[ext=mp4]/best', '--merge-output-format', 'mp4',
                 '-o', output_path, '--no-playlist', url],
                capture_output=True, text=True, timeout=Config.VIDEO_TIMEOUT
            )
            
            if result.returncode != 0:
                return False, f"Download failed", video_info
            
            return os.path.exists(output_path), "Success", video_info
            
        except Exception as e:
            return False, str(e), None
    
    async def get_info(self, url: str) -> Tuple[bool, Optional[VideoInfo]]:
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    lambda: subprocess.run(['yt-dlp', '--dump-json', '--no-download', url],
                                         capture_output=True, text=True, timeout=20)
                ),
                timeout=25
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
# ROBLOX API (STABLE)
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: SimpleCache):
        self.cache = cache
        self.session = None
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            connector=TCPConnector(limit=50, limit_per_host=20),
            timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        if not users:
            return []
        
        # Check cache first
        to_fetch = []
        verified = []
        
        for user in users[:5]:
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
        
        # Fetch in parallel
        if to_fetch:
            tasks = [self._fetch_user(u) for u in to_fetch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for user, result in zip(to_fetch, results):
                if isinstance(result, dict):
                    await self.cache.set(f"u:{user.username.lower()}", result, 600)
                    verified.append({
                        'profile': result,
                        'detected': user,
                        'score': user.confidence,
                        'cached': False
                    })
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, user: DetectedUser) -> Optional[Dict]:
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
    
    async def _fetch_by_id(self, user_id: int) -> Optional[Dict]:
        try:
            async with self.session.get(f'https://users.roblox.com/v1/users/{user_id}') as resp:
                if resp.status == 200:
                    profile = await resp.json()
                    profile['thumbnailUrl'] = await self._get_avatar(user_id)
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

# ═══════════════════════════════════════════════════════════
# DATABASE (STABLE)
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
# BOT (STABLE)
# ═══════════════════════════════════════════════════════════
class OmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.cache = SimpleCache()
        self.limiter = RateLimiter(Config.RATE_LIMIT, 60)
        self.video_limiter = RateLimiter(5, 60)
        self.ocr = None
        self.roblox = None
        self.video_downloader = VideoDownloader()
        
    async def setup_hook(self):
        logger.info("🔧 Starting TRUE OMEGA v6.1...")
        
        # Setup components with error handling
        try:
            await self.cache.setup()
        except Exception as e:
            logger.warning(f"Cache setup failed: {e}")
        
        try:
            await self.db.setup()
        except Exception as e:
            logger.warning(f"DB setup failed: {e}")
        
        try:
            self.roblox = RobloxAPI(self.cache)
            await self.roblox.setup()
        except Exception as e:
            logger.error(f"Roblox API setup failed: {e}")
            raise
        
        # Initialize OCR (might fail gracefully)
        self.ocr = StableOCR(self.cache)
        try:
            await self.ocr.init_engines()
        except Exception as e:
            logger.warning(f"OCR init failed: {e}")
        
        self._register_cmds()
        
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Command sync failed: {e}")
        
        logger.info("✅ TRUE OMEGA v6.1 Ready!")
    
    def _register_cmds(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username")
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
    
    async def cmd_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        uid = str(interaction.user.id)
        start_time = time.time()
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Not Whitelisted", color=0xFF0000),
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
        
        if image.size > 8 * 1024 * 1024:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ File Too Large", description="Max 8MB", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Download image
            async with aiohttp.ClientSession() as session:
                async with session.get(image.url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download Failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
            
            # OCR Scan
            success, users, raw_text, meta = await self.ocr.scan(img_data, hint)
            
            if not success:
                embed = discord.Embed(
                    title="❌ No Username Found",
                    description="Could not detect any valid Roblox username in this image.",
                    color=0xFF6B6B
                )
                embed.add_field(name="Time", value=f"`{time.time() - start_time:.2f}s`", inline=True)
                if meta.get('error'):
                    embed.add_field(name="Error", value=f"`{meta['error']}`", inline=True)
                await interaction.followup.send(embed=embed)
                return
            
            # Verify with Roblox
            verified = await self.roblox.verify_users(users)
            
            if not verified:
                embed = discord.Embed(
                    title="❌ User Not Found",
                    description=f"Detected `@{users[0].username}` but it doesn't exist on Roblox.",
                    color=0xFF6B6B
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Success
            best = verified[0]
            prof = best['profile']
            det = best['detected']
            total_time = time.time() - start_time
            
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
            embed.add_field(name="🧠 Engines", value=f"`{len(meta.get('engines_used', []))}`", inline=True)
            
            if prof.get('thumbnailUrl'):
                embed.set_thumbnail(url=prof['thumbnailUrl'])
            embed.set_image(url=image.url)
            embed.set_footer(text="TRUE OMEGA v6.1")
            
            await interaction.followup.send(embed=embed)
            
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
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Not Whitelisted", color=0xFF0000),
                ephemeral=True
            )
            return
        
        allowed, retry = await self.video_limiter.check(uid)
        if not allowed:
            await interaction.response.send_message(
                embed=discord.Embed(title="⏰ Rate Limited", description=f"Try again in {int(retry)}s", color=0xFFA500),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            if info_only:
                success, info = await self.video_downloader.get_info(url)
                if not success:
                    await interaction.followup.send(
                        embed=discord.Embed(title="❌ Failed to get info", color=0xFF0000)
                    )
                    return
                
                embed = discord.Embed(
                    title=f"📹 {info.title[:100]}",
                    description=f"**{info.uploader}** • {info.duration}",
                    color=0x00D4AA
                )
                if info.thumbnail:
                    embed.set_thumbnail(url=info.thumbnail)
                await interaction.followup.send(embed=embed)
            else:
                success, message, file_path, info = await self.video_downloader.download(url)
                
                if not success:
                    await interaction.followup.send(
                        embed=discord.Embed(title="❌ Download Failed", description=message, color=0xFF0000)
                    )
                    return
                
                if not file_path or not os.path.exists(file_path):
                    await interaction.followup.send(
                        embed=discord.Embed(title="❌ File not found", color=0xFF0000)
                    )
                    return
                
                file_size = os.path.getsize(file_path)
                if file_size > Config.MAX_FILE_SIZE:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="❌ File Too Large",
                            description=f"{file_size / 1024 / 1024:.1f}MB > {Config.MAX_FILE_SIZE / 1024 / 1024:.0f}MB",
                            color=0xFF0000
                        )
                    )
                    return
                
                file = discord.File(file_path, filename=os.path.basename(file_path))
                embed = discord.Embed(
                    title=f"📥 {info.title[:100] if info else 'Video'}",
                    description=f"**{info.uploader if info else 'Unknown'}** • {info.duration if info else 'Unknown'}",
                    color=0x00FF00
                )
                if info and info.thumbnail:
                    embed.set_thumbnail(url=info.thumbnail)
                
                await interaction.followup.send(embed=embed, file=file)
                
                # Update stats
                stats = await self.db.get_stats(uid)
                stats['videos_downloaded'] = stats.get('videos_downloaded', 0) + 1
                await self.db.save_stats(uid, stats)
                
        except Exception as e:
            logger.error(f"Download error: {traceback.format_exc()}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
            )
    
    async def cmd_stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(str(interaction.user.id))
        embed = discord.Embed(title="📊 Your Statistics", color=0x00D4AA)
        embed.add_field(name="🔍 Total Scans", value=str(stats.get('total', 0)), inline=True)
        embed.add_field(name="✅ Successful", value=str(stats.get('success', 0)), inline=True)
        embed.add_field(name="📥 Videos", value=str(stats.get('videos_downloaded', 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"`{round(self.latency * 1000)}ms`", inline=True)
        embed.add_field(name="Cache", value=f"`{self.cache.stats()}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# HEALTH SERVER (REQUIRED FOR RAILWAY/RENDER)
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    
    async def health_handler(request):
        return web.Response(text="OK", status=200)
    
    app = web.Application()
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()
    logger.info(f"✅ Health server on port {os.getenv('PORT', 8080)}")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def main():
    # Start health server FIRST (required for deployment)
    await health_server()
    
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
