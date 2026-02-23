"""
🚀 TRUE OMEGA v5.1 - ULTIMATE SCANNER + VIDEO DOWNLOADER
Features: Ensemble OCR, Video Download (Medal, Streamable, etc.), Beautiful Webhooks
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
from datetime import datetime
from urllib.parse import quote, urlparse
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
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # TIMEOUTS
    DOWNLOAD_TIMEOUT = 30  # Increased for video downloads
    OCR_TIMEOUT = 6
    API_TIMEOUT = 5
    VIDEO_TIMEOUT = 120  # 2 minutes for video processing
    
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB for videos
    RATE_LIMIT = 20
    
    # OCR ENGINE PRIORITIES
    OCR_ENGINES = ['easyocr', 'tesseract', 'ocrspace']
    
    # USERNAME VALIDATION
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$')
    
    # VIDEO DOMAINS SUPPORTED
    VIDEO_DOMAINS = [
        'medal.tv', 'streamable.com', 'youtube.com', 'youtu.be',
        'twitter.com', 'x.com', 'reddit.com', 'tiktok.com',
        'instagram.com', 'facebook.com', 'twitch.tv'
    ]

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
        if key in self.cache and time.time() < self.expiry.get(key, 0):
            self._hits += 1
            return self.cache[key]
        
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

@dataclass
class VideoInfo:
    url: str
    title: str
    duration: str
    uploader: str
    thumbnail: Optional[str]
    filesize: Optional[int]

# ═══════════════════════════════════════════════════════════
# ADVANCED IMAGE PREPROCESSING PIPELINE
# ═══════════════════════════════════════════════════════════
class ImagePreprocessor:
    """Advanced preprocessing for maximum OCR accuracy"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)
    
    async def preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        if not CV2_AVAILABLE or not PIL_AVAILABLE:
            return await self._basic_preprocess(image_data)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._advanced_preprocess, image_data)
    
    def _advanced_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        versions = []
        
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return self._pil_fallback(image_data)
        
        original = img.copy()
        h, w = img.shape[:2]
        
        # 1. Original
        versions.append(self._encode_cv2(original, "original"))
        
        # 2. Grayscale + CLAHE
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)
        versions.append(self._encode_cv2(gray_clahe, "gray_clahe", is_gray=True))
        
        # 3. Denoised
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)
        versions.append(self._encode_cv2(denoised, "denoised", is_gray=True))
        
        # 4. Upscaled
        if w < 800:
            scaled = cv2.resize(gray, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
            versions.append(self._encode_cv2(scaled, "upscaled", is_gray=True))
        
        # 5. Binarized
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        versions.append(self._encode_cv2(binary, "binary", is_gray=True))
        
        # 6. Deskewed
        try:
            deskewed = self._deskew(gray)
            versions.append(self._encode_cv2(deskewed, "deskewed", is_gray=True))
        except Exception as e:
            logger.debug(f"Deskew failed: {e}")
        
        # 7. Sharpened
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(gray, -1, kernel)
        versions.append(self._encode_cv2(sharpened, "sharpened", is_gray=True))
        
        # 8. Morphological
        kernel = np.ones((2, 2), np.uint8)
        morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        versions.append(self._encode_cv2(morph, "morphological", is_gray=True))
        
        return versions
    
    def _deskew(self, gray_img: np.ndarray) -> np.ndarray:
        gray_inv = cv2.bitwise_not(gray_img)
        thresh = cv2.threshold(gray_inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        
        coords = np.column_stack(np.where(thresh > 0))
        angle = cv2.minAreaRect(coords)[-1]
        
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        
        if abs(angle) < 0.5:
            return gray_img
        
        (h, w) = gray_img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(gray_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rotated
    
    def _encode_cv2(self, img: np.ndarray, name: str, is_gray: bool = False) -> Tuple[bytes, str, Dict]:
        if is_gray:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        _, buf = cv2.imencode('.png', img)
        return (buf.tobytes(), name, {"size": img.shape[:2]})
    
    def _pil_fallback(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        img = Image.open(io.BytesIO(image_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        versions = []
        
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        versions.append((buf.getvalue(), "original", {}))
        
        enhanced = ImageEnhance.Contrast(img).enhance(2.0)
        buf = io.BytesIO()
        enhanced.save(buf, format='PNG')
        versions.append((buf.getvalue(), "contrast", {}))
        
        sharpened = img.filter(ImageFilter.SHARPEN)
        buf = io.BytesIO()
        sharpened.save(buf, format='PNG')
        versions.append((buf.getvalue(), "sharpened", {}))
        
        return versions
    
    async def _basic_preprocess(self, image_data: bytes) -> List[Tuple[bytes, str, Dict]]:
        return [(image_data, "original", {})]

# ═══════════════════════════════════════════════════════════
# ENSEMBLE OCR MANAGER
# ═══════════════════════════════════════════════════════════
class EnsembleOCR:
    def __init__(self, cache: UltraCache):
        self.easyocr_reader = None
        self.easy_ready = False
        self.preprocessor = ImagePreprocessor()
        self.executor = ThreadPoolExecutor(max_workers=6)
        self.cache = cache
        self.ocr_space_available = bool(Config.OCR_SPACE_KEY)
        
    async def init_easyocr(self):
        if EASYOCR_AVAILABLE and not self.easy_ready:
            try:
                loop = asyncio.get_event_loop()
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
        start_time = time.time()
        
        versions = await self.preprocessor.preprocess(image_data)
        
        tasks = []
        
        if self.easy_ready:
            for img, name, _ in versions[:3]:
                tasks.append(self._run_easyocr(img, name))
        
        if TESSERACT_AVAILABLE:
            for img, name, _ in versions:
                tasks.append(self._run_tesseract(img, name))
        
        if self.ocr_space_available:
            tasks.append(self._run_ocrspace(image_data))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        results = [r for r in results if isinstance(r, OCRResult)]
        
        if not results:
            return False, [], "", {"error": "All OCR engines failed"}
        
        all_texts = [r.text for r in results]
        combined_text = '\n'.join(all_texts)
        
        all_users = []
        for result in results:
            users = self._extract_users(result.text, hint, result.engine)
            for u in users:
                u.engine = result.engine
                all_users.append(u)
        
        voted_users = self._vote_users(all_users)
        voted_users.sort(key=lambda x: x.confidence, reverse=True)
        
        metadata = {
            "engines_used": [r.engine for r in results],
            "versions_processed": len(versions),
            "processing_time": time.time() - start_time,
            "raw_texts": len(all_texts)
        }
        
        return len(voted_users) > 0, voted_users, combined_text, metadata
    
    async def _run_easyocr(self, image_data: bytes, version_name: str) -> OCRResult:
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
        text, conf = await asyncio.wait_for(
            loop.run_in_executor(self.executor, _run),
            timeout=Config.OCR_TIMEOUT
        )
        
        return OCRResult(text, f"tesseract_{version_name}", conf, time.time() - start)
    
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
        users = []
        lines = text.split('\n')
        
        # @username
        for m in re.finditer(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            u = m.group(1)
            if self._validate_username(u):
                conf = 0.95
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                users.append(DetectedUser(u, None, conf, '@mention', engine, text[m.start():m.end()]))
        
        # DisplayName @username
        for m in re.finditer(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠]\s*([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            d, u = m.groups()
            d = d.strip()
            if self._validate_username(u) and len(d) > 2:
                users.append(DetectedUser(u, d, 0.98, 'display@user', engine, text[m.start():m.end()]))
        
        # roblox.com/users/ID/profile
        for m in re.finditer(r'roblox\.com/users/(\d+)', text, re.I):
            uid = m.group(1)
            users.append(DetectedUser(f"ID:{uid}", None, 0.99, 'url', engine, text[m.start():m.end()]))
        
        # Contextual username
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
                surr = ' '.join(lines[max(0,i-2):min(len(lines), i+3)]).lower()
                if any(x in surr for x in ['roblox', '@', 'profile', 'username']):
                    conf = min(conf + 0.15, 0.90)
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                
                users.append(DetectedUser(u, None, conf, 'context', engine, line))
        
        return users
    
    def _validate_username(self, username: str) -> bool:
        if not username:
            return False
        return bool(Config.USERNAME_REGEX.match(username))
    
    def _vote_users(self, users: List[DetectedUser]) -> List[DetectedUser]:
        if not users:
            return []
        
        groups = {}
        for u in users:
            key = u.username.lower()
            if key not in groups:
                groups[key] = []
            groups[key].append(u)
        
        voted = []
        for username, group in groups.items():
            engines = set(u.engine for u in group)
            engine_count = len(engines)
            
            best_conf = max(u.confidence for u in group)
            display_names = [u.display_name for u in group if u.display_name]
            best_display = display_names[0] if display_names else None
            
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
# VIDEO DOWNLOADER - YT-DLP POWERED (FIXED)
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    """Download videos from Medal, Streamable, YouTube, etc. using yt-dlp"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.download_path = "downloads/videos"
        os.makedirs(self.download_path, exist_ok=True)
    
    def _run_yt_dlp(self, url: str, output_path: str) -> Tuple[bool, str, Optional[VideoInfo]]:
        """Run yt-dlp to download video"""
        try:
            # First, get info
            info_cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-download',
                url
            ]
            
            result = subprocess.run(
                info_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, f"Failed to get video info: {result.stderr}", None
            
            try:
                info = json.loads(result.stdout.strip().split('\n')[0])
            except:
                return False, "Failed to parse video info", None
            
            video_info = VideoInfo(
                url=url,
                title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            # Download video
            download_cmd = [
                'yt-dlp',
                '-f', 'best[ext=mp4]/best',  # Best quality MP4 or best available
                '--merge-output-format', 'mp4',
                '-o', output_path,
                '--no-playlist',
                '--newline',
                url
            ]
            
            result = subprocess.run(
                download_cmd,
                capture_output=True,
                text=True,
                timeout=Config.VIDEO_TIMEOUT
            )
            
            if result.returncode != 0:
                return False, f"Download failed: {result.stderr}", video_info
            
            if os.path.exists(output_path):
                return True, "Success", video_info
            else:
                return False, "Output file not created", video_info
                
        except subprocess.TimeoutExpired:
            return False, "Download timeout", None
        except Exception as e:
            return False, str(e), None
    
    def _format_duration(self, seconds: Optional[Union[int, float]]) -> str:
        """Format seconds to readable duration - FIXED for float values"""
        if not seconds:
            return "Unknown"
        
        # Convert to int to handle float values from yt-dlp
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
        """
        Download video from URL
        Returns: (success, message, file_path, video_info)
        """
        # Validate URL
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')
        
        if not any(d in domain for d in Config.VIDEO_DOMAINS):
            return False, f"Unsupported domain. Supported: {', '.join(Config.VIDEO_DOMAINS)}", None, None
        
        # Generate filename
        video_id = hashlib.md5(url.encode()).hexdigest()[:8]
        output_path = os.path.join(self.download_path, f"{video_id}.mp4")
        
        # Check if already downloaded
        if os.path.exists(output_path):
            # Get info from cache or re-fetch
            return True, "Already downloaded (cached)", output_path, None
        
        # Run download in thread pool
        loop = asyncio.get_event_loop()
        success, message, info = await loop.run_in_executor(
            self.executor,
            self._run_yt_dlp,
            url,
            output_path
        )
        
        if success:
            return True, message, output_path, info
        else:
            return False, message, None, info
    
    async def get_info(self, url: str) -> Tuple[bool, Optional[VideoInfo]]:
        """Get video info without downloading"""
        try:
            cmd = ['yt-dlp', '--dump-json', '--no-download', url]
            loop = asyncio.get_event_loop()
            
            result = await loop.run_in_executor(
                self.executor,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
            
            if result.returncode != 0:
                return False, None
            
            info = json.loads(result.stdout.strip().split('\n')[0])
            
            video_info = VideoInfo(
                url=url,
                title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            return True, video_info
            
        except Exception as e:
            logger.error(f"Get info error: {e}")
            return False, None

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
                continue
            
            profile = await self._fetch_user(user.username)
            if profile:
                await self.cache.set(f"u:{user.username.lower()}", profile, 600)
                verified.append({
                    'profile': profile,
                    'detected': user,
                    'score': user.confidence,
                    'cached': False
                })
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, username: str) -> Optional[Dict]:
        try:
            if username.startswith("ID:"):
                return await self._fetch_by_id(int(username.split(":")[1]))
            
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
    def __init__(self):
        self.url = Config.WEBHOOK_URL
        self.session = None
    
    async def setup(self):
        if self.url:
            self.session = aiohttp.ClientSession()
            logger.info("✅ Webhook manager ready")
    
    async def send_scan_result(self, user: discord.User, profile: Dict, detected: DetectedUser, image_url: str, processing_time: float):
        if not self.url or not self.session:
            return
        
        try:
            if detected.confidence >= 0.95:
                color = 0x00FF00
                status = "✅ CERTAIN"
            elif detected.confidence >= 0.80:
                color = 0x55FF55
                status = "✓ HIGH"
            elif detected.confidence >= 0.60:
                color = 0xFFAA00
                status = "⚠ MEDIUM"
            else:
                color = 0xFF5555
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
                    {"name": "🆔 User ID", "value": f"`{profile['id']}`", "inline": True},
                    {"name": "📊 Confidence", "value": f"`{detected.confidence:.0%}` {status}", "inline": True},
                    {"name": "🔎 Detection Source", "value": f"`{detected.source}`", "inline": True},
                    {"name": "⚡ Processing Time", "value": f"`{processing_time:.2f}s`", "inline": True},
                    {"name": "🤖 Detection Engine", "value": f"`{detected.engine}`", "inline": True},
                    {"name": "📅 Account Created", "value": f"`{str(profile.get('created', 'Unknown'))[:10]}`", "inline": True}
                ],
                "footer": {
                    "text": "TRUE OMEGA v5.1 ULTIMATE | Video Downloader + Scanner",
                    "icon_url": "https://i.imgur.com/4M34hi2.png"
                }
            }
            
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
    
    async def send_video_download(self, user: discord.User, video_info: VideoInfo, file_path: str):
        """Send video download notification to webhook"""
        if not self.url or not self.session:
            return
        
        try:
            embed = {
                "title": f"📥 Video Downloaded: {video_info.title[:100]}",
                "description": f"**{video_info.uploader}** • {video_info.duration}",
                "url": video_info.url,
                "color": 0x00D4AA,
                "timestamp": datetime.utcnow().isoformat(),
                "thumbnail": {
                    "url": video_info.thumbnail or "https://i.imgur.com/4M34hi2.png"
                },
                "author": {
                    "name": f"Downloaded by {user.name}",
                    "icon_url": str(user.display_avatar.url) if user.display_avatar else None
                },
                "fields": [
                    {"name": "👤 Uploader", "value": video_info.uploader, "inline": True},
                    {"name": "⏱️ Duration", "value": video_info.duration, "inline": True},
                    {"name": "📁 File Size", "value": self._format_size(video_info.filesize), "inline": True}
                ],
                "footer": {
                    "text": "TRUE OMEGA Video Downloader",
                    "icon_url": "https://i.imgur.com/4M34hi2.png"
                }
            }
            
            payload = {
                "username": "TRUE OMEGA Downloader",
                "avatar_url": "https://i.imgur.com/4M34hi2.png",
                "embeds": [embed]
            }
            
            async with self.session.post(self.url, json=payload) as resp:
                if resp.status not in (200, 204):
                    logger.warning(f"Webhook failed: {resp.status}")
                    
        except Exception as e:
            logger.error(f"Webhook error: {e}")
    
    def _format_size(self, size_bytes: Optional[int]) -> str:
        if not size_bytes:
            return "Unknown"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
    
    async def send_error(self, error: str, user: discord.User = None):
        if not self.url or not self.session:
            return
        
        try:
            embed = {
                "title": "❌ Error",
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
        os.makedirs("downloads/videos", exist_ok=True)
        
    async def setup(self):
        if DB_AVAILABLE and Config.DATABASE_URL:
            try:
                self.pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=1, max_size=5)
                async with self.pool.acquire() as conn:
                    await conn.execute("CREATE TABLE IF NOT EXISTS whitelist (user_id TEXT PRIMARY KEY)")
                    await conn.execute("CREATE TABLE IF NOT EXISTS stats (user_id TEXT PRIMARY KEY, data JSONB)")
                    await conn.execute("CREATE TABLE IF NOT EXISTS downloads (id SERIAL PRIMARY KEY, user_id TEXT, url TEXT, title TEXT, timestamp TIMESTAMP)")
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
        return {'total': 0, 'success': 0, 'favorites': [], 'videos_downloaded': 0}
    
    async def save_stats(self, uid: str, data: Dict):
        try:
            with open(f"data/{uid}.json", 'w') as f:
                json.dump(data, f)
        except:
            pass
    
    async def log_download(self, uid: str, url: str, title: str):
        """Log video download"""
        try:
            if self.pool:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO downloads (user_id, url, title, timestamp) VALUES ($1, $2, $3, NOW())",
                        uid, url, title[:200]
                    )
        except Exception as e:
            logger.debug(f"Log download error: {e}")

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
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan | /download")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.cache = UltraCache()
        self.limiter = RateLimiter(Config.RATE_LIMIT, 60)
        self.video_limiter = RateLimiter(5, 60)  # Stricter for videos
        self.ocr = EnsembleOCR(self.cache)
        self.roblox = None
        self.video_downloader = VideoDownloader()
        self.webhook = WebhookManager()
        self.scan_sem = asyncio.Semaphore(50)
        
    async def setup_hook(self):
        logger.info("🔧 Starting ULTIMATE OMEGA v5.1...")
        await self.cache.setup()
        await self.db.setup()
        await self.webhook.setup()
        self.roblox = RobloxAPI(self.cache)
        await self.roblox.setup()
        await self.ocr.init_easyocr()
        self._register_cmds()
        await self._sync()
        logger.info("✅ ULTIMATE OMEGA v5.1 Ready!")
    
    def _register_cmds(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username (ULTIMATE)")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download video from Medal, Streamable, YouTube, etc.")
        @app_commands.describe(
            url="Video URL to download",
            info_only="Just show info, don't download (optional)"
        )
        async def download(interaction: discord.Interaction, url: str, info_only: bool = False):
            await self.cmd_download(interaction, url, info_only)
        
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
                embed=discord.Embed(title="❌ File Too Large", description="Max 25MB for images", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        async with self.scan_sem:
            try:
                dl_start = time.time()
                async with self.roblox.session.get(image.url, timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download Failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
                dl_time = time.time() - dl_start
                
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
                
                api_start = time.time()
                verified = await self.roblox.verify_users(users)
                api_time = time.time() - api_start
                
                if not verified:
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
                
                best = verified[0]
                prof = best['profile']
                det = best['detected']
                total_time = time.time() - start_time
                
                embed = self._make_result_embed(prof, det, dl_time, ocr_time, api_time, total_time, meta)
                embed.set_image(url=image.url)
                
                view = ResultView(prof, self, uid)
                await interaction.followup.send(embed=embed, view=view)
                
                await self.webhook.send_scan_result(
                    interaction.user, prof, det, image.url, total_time
                )
                
                await self._update_stats(uid, prof['name'])
                
            except Exception as e:
                logger.error(f"Scan error: {traceback.format_exc()}")
                await self.webhook.send_error(str(e), interaction.user)
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
                )
    
    def _make_result_embed(self, prof: Dict, det: DetectedUser, dl_t: float, ocr_t: float, api_t: float, total_t: float, meta: Dict) -> discord.Embed:
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
        
        embed.add_field(name="🎯 Confidence", value=f"`{score:.0%}`", inline=True)
        embed.add_field(name="🔍 Source", value=f"`{det.source}`", inline=True)
        embed.add_field(name="🤖 Engine", value=f"`{det.engine}`", inline=True)
        
        embed.add_field(name="🆔 User ID", value=f"`{prof['id']}`", inline=True)
        embed.add_field(name="📅 Created", value=f"`{str(prof.get('created', 'Unknown'))[:10]}`", inline=True)
        embed.add_field(name="✅ Verified", value=f"{'✓' if not det.engine == 'ensemble' else '⚡'}", inline=True)
        
        perf_text = f"⬇️ `{dl_t:.2f}s` | 🔍 `{ocr_t:.2f}s` | 🌐 `{api_t:.2f}s` | ⚡ `{total_t:.2f}s`"
        embed.add_field(name="⚡ Performance", value=perf_text, inline=False)
        
        if meta.get('engines_used'):
            engines = ', '.join(meta['engines_used'][:3])
            embed.add_field(name="🧠 OCR Engines", value=f"`{engines}`", inline=True)
        
        if prof.get('description'):
            desc = prof['description'][:150] + "..." if len(prof['description']) > 150 else prof['description']
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        if prof.get('thumbnailUrl'):
            embed.set_thumbnail(url=prof['thumbnailUrl'])
        
        embed.set_footer(text="TRUE OMEGA v5.1 ULTIMATE | Video Downloader + Scanner")
        return embed
    
    async def cmd_download(self, interaction: discord.Interaction, url: str, info_only: bool):
        """Download video from URL using yt-dlp - FIXED"""
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
                # Just get info
                success, info = await self.video_downloader.get_info(url)
                if not success:
                    await interaction.followup.send(
                        embed=discord.Embed(title="❌ Failed to get video info", color=0xFF0000)
                    )
                    return
                
                embed = discord.Embed(
                    title=f"📹 {info.title[:100]}",
                    url=url,
                    description=f"**{info.uploader}** • {info.duration}",
                    color=0x00D4AA
                )
                if info.thumbnail:
                    embed.set_thumbnail(url=info.thumbnail)
                embed.add_field(name="⏱️ Duration", value=info.duration, inline=True)
                embed.add_field(name="👤 Uploader", value=info.uploader, inline=True)
                embed.add_field(name="📁 Estimated Size", value=self._format_size(info.filesize), inline=True)
                embed.set_footer(text="Use /download without info_only to download")
                
                await interaction.followup.send(embed=embed)
            else:
                # Actually download
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
                
                # Check file size
                file_size = os.path.getsize(file_path)
                if file_size > Config.MAX_FILE_SIZE:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            title="❌ File Too Large",
                            description=f"Video is {self._format_size(file_size)}, max is {self._format_size(Config.MAX_FILE_SIZE)}",
                            color=0xFF0000
                        )
                    )
                    return
                
                # Send file
                file = discord.File(file_path, filename=os.path.basename(file_path))
                
                embed = discord.Embed(
                    title=f"📥 Downloaded: {info.title[:100] if info else 'Video'}",
                    description=f"**{info.uploader if info else 'Unknown'}** • {info.duration if info else 'Unknown'}",
                    color=0x00FF00
                )
                if info and info.thumbnail:
                    embed.set_thumbnail(url=info.thumbnail)
                
                await interaction.followup.send(embed=embed, file=file)
                
                # Log and webhook
                if info:
                    await self.db.log_download(uid, url, info.title)
                    await self.webhook.send_video_download(interaction.user, info, file_path)
                    
                    # Update stats
                    stats = await self.db.get_stats(uid)
                    stats['videos_downloaded'] = stats.get('videos_downloaded', 0) + 1
                    await self.db.save_stats(uid, stats)
                
        except Exception as e:
            logger.error(f"Download error: {traceback.format_exc()}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
            )
    
    def _format_size(self, size_bytes: Optional[Union[int, float]]) -> str:
        """Format file size to human readable - FIXED for float values"""
        if not size_bytes:
            return "Unknown"
        
        try:
            size_bytes = float(size_bytes)
        except (ValueError, TypeError):
            return "Unknown"
        
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
    
    async def cmd_whitelist(self, interaction: discord.Interaction, user: str):
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
        stats = await self.db.get_stats(str(interaction.user.id))
        total = stats.get('total', 0)
        success = stats.get('success', 0)
        videos = stats.get('videos_downloaded', 0)
        rate = (success / total * 100) if total > 0 else 0
        
        embed = discord.Embed(title="📊 Your Statistics", color=0x00D4AA)
        embed.add_field(name="🔍 Total Scans", value=str(total), inline=True)
        embed.add_field(name="✅ Successful", value=str(success), inline=True)
        embed.add_field(name="📈 Success Rate", value=f"{rate:.1f}%", inline=True)
        embed.add_field(name="📥 Videos Downloaded", value=str(videos), inline=True)
        
        favs = stats.get('favorites', [])
        if favs:
            embed.add_field(
                name="⭐ Favorites",
                value='\n'.join([f"• @{u}" for u in favs[:5]]),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"`{round(self.latency * 1000)}ms`", inline=True)
        embed.add_field(name="Whitelisted", value=f"`{len(self.db.whitelist)}`", inline=True)
        embed.add_field(name="Cache", value=f"`{self.cache.stats()}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_cache(self, interaction: discord.Interaction):
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message("⛔ Owner only", ephemeral=True)
            return
        
        stats = self.cache.stats()
        embed = discord.Embed(title="📈 Cache Statistics", description=stats, color=0x00D4AA)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _update_stats(self, uid: str, username: str):
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
        
        self.add_item(discord.ui.Button(
            label="View Profile",
            style=discord.ButtonStyle.link,
            url=f"https://roblox.com/users/{profile['id']}/profile",
            emoji="🔗"
        ))
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="⭐")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
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

# ═══════════════════════════════════════════════════════════
# HEALTH SERVER
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text='ULTIMATE OMEGA v5.1 OK'))
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
