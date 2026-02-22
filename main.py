"""
🎯 TRUE OMEGA ULTIMATE v3.0 - Next-Gen Roblox Scanner
Fixed whitelist system
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
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote, unquote
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Tuple, Any, Set, Callable
from enum import Enum, auto
from functools import wraps
import numpy as np

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════
class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[35m',
        'RESET': '\033[0m'
    }
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)

logger = logging.getLogger("true_omega")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColoredFormatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(handler)

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
    
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '52428800'))
    OCR_TIMEOUT = int(os.getenv('OCR_TIMEOUT', '15'))
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT', '15'))
    CACHE_TTL = int(os.getenv('CACHE_TTL', '300'))
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', '8'))
    
    @classmethod
    def validate(cls):
        if not cls.TOKEN:
            logger.error("❌ DISCORD_TOKEN not set!")
            sys.exit(1)
        logger.info(f"✅ Config validated | Owner: {cls.OWNER_ID}")

Config.validate()

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════
import aiohttp
import discord
from discord import app_commands
from discord.ui import Button, View, Select

try:
    import asyncpg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
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
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

logger.info(f"🔧 Available: PIL={PIL_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# ASYNC CACHE
# ═══════════════════════════════════════════════════════════
class AsyncCache:
    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.maxsize = maxsize
        self.ttl = ttl
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key in self.cache:
                value, expiry = self.cache[key]
                if time.time() < expiry:
                    return value
                del self.cache[key]
            return None
    
    async def set(self, key: str, value: Any, ttl: int = None):
        ttl = ttl or self.ttl
        async with self._lock:
            if len(self.cache) >= self.maxsize:
                oldest = min(self.cache.items(), key=lambda x: x[1][1])
                del self.cache[oldest[0]]
            self.cache[key] = (value, time.time() + ttl)
    
    async def delete(self, key: str):
        async with self._lock:
            if key in self.cache:
                del self.cache[key]

# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════
@dataclass
class DetectedUser:
    username: str
    display_name: Optional[str]
    confidence: float
    source: str
    context: str = ""

@dataclass
class ScanResult:
    success: bool
    detected_users: List[DetectedUser]
    verified_profile: Optional[Dict] = None
    alternatives: List[Dict] = field(default_factory=list)
    scan_time: float = 0.0
    engines_used: List[str] = field(default_factory=list)
    raw_text: str = ""

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
        return (self.successful_scans / self.total_scans * 100) if self.total_scans > 0 else 0.0

# ═══════════════════════════════════════════════════════════
# SMART PREPROCESSOR
# ═══════════════════════════════════════════════════════════
class SmartPreprocessor:
    def __init__(self):
        self.quality_presets = {
            "low": {"scale": 1, "denoise": False},
            "medium": {"scale": 2, "denoise": True},
            "high": {"scale": 3, "denoise": True, "contrast": True},
        }
    
    def preprocess(self, image_data: bytes, quality: str = "high") -> List[Tuple[str, bytes]]:
        if not PIL_AVAILABLE:
            return [("original", image_data)]
        
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            w, h = img.size
            preset = self.quality_presets.get(quality, self.quality_presets["high"])
            results = [("original", image_data)]
            
            # Scale if needed
            if preset.get("scale", 1) > 1:
                scale = preset["scale"]
                img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
            
            # High contrast version
            v1 = img.copy()
            v1 = ImageEnhance.Contrast(v1).enhance(2.5)
            v1 = ImageEnhance.Sharpness(v1).enhance(2.0)
            results.append(("high_contrast", self._to_bytes(v1)))
            
            # Binary version
            v2 = img.copy()
            v2 = ImageOps.grayscale(v2)
            v2 = v2.point(lambda x: 0 if x < 128 else 255, '1').convert('RGB')
            results.append(("binary", self._to_bytes(v2)))
            
            # Denoised
            if preset.get("denoise"):
                v3 = img.copy()
                v3 = v3.filter(ImageFilter.MedianFilter(size=3))
                v3 = ImageEnhance.Contrast(v3).enhance(1.5)
                results.append(("denoised", self._to_bytes(v3)))
            
            return results
            
        except Exception as e:
            logger.error(f"Preprocessing failed: {e}")
            return [("original", image_data)]
    
    def _to_bytes(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        return buf.getvalue()

# ═══════════════════════════════════════════════════════════
# MULTI-ENGINE OCR
# ═══════════════════════════════════════════════════════════
class MultiEngineOCR:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.easyocr_reader = None
        self.preprocessor = SmartPreprocessor()
        self.executor = __import__('concurrent').futures.ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)
        
        if EASYOCR_AVAILABLE:
            asyncio.create_task(self._init_easyocr())
    
    async def _init_easyocr(self):
        try:
            self.easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            logger.info("✅ EasyOCR initialized")
        except Exception as e:
            logger.error(f"EasyOCR init failed: {e}")
    
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "TrueOmegaBot/3.0"}
        )
    
    async def scan(self, image_data: bytes, hint: Optional[str] = None) -> ScanResult:
        start_time = time.time()
        
        # Preprocess
        preprocessed = self.preprocessor.preprocess(image_data)
        
        # Run OCR engines in parallel
        tasks = []
        
        # Tesseract on first 3 versions
        for method, img_data in preprocessed[:3]:
            tasks.append(self._run_tesseract(img_data, method))
        
        # EasyOCR
        if self.easyocr_reader:
            tasks.append(self._run_easyocr(preprocessed[0][1]))
        
        # OCR.space
        if Config.OCR_SPACE_KEY:
            tasks.append(self._run_ocrspace(preprocessed[0][1]))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Fuse results
        fused_text, engines = self._fuse_results(results)
        
        # Extract users
        detected = self._extract_usernames(fused_text, hint)
        
        return ScanResult(
            success=len(detected) > 0,
            detected_users=detected,
            scan_time=time.time() - start_time,
            engines_used=engines,
            raw_text=fused_text[:500]
        )
    
    async def _run_tesseract(self, image_data: bytes, method: str) -> Tuple[str, str, float]:
        if not TESSERACT_AVAILABLE:
            return "", method, 0.0
        
        try:
            def _tess():
                img = Image.open(io.BytesIO(image_data))
                config = '--psm 6 --oem 3'
                return pytesseract.image_to_string(img, config=config)
            
            loop = asyncio.get_event_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(self.executor, _tess),
                timeout=Config.OCR_TIMEOUT
            )
            return text, f"tesseract_{method}", 0.8 if text else 0.0
            
        except Exception as e:
            return "", method, 0.0
    
    async def _run_easyocr(self, image_data: bytes) -> Tuple[str, str, float]:
        if not self.easyocr_reader or not CV2_AVAILABLE:
            return "", "easyocr", 0.0
        
        try:
            def _easy():
                nparr = np.frombuffer(image_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                results = self.easyocr_reader.readtext(img)
                return '\n'.join([r[1] for r in results])
            
            loop = asyncio.get_event_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(self.executor, _easy),
                timeout=Config.OCR_TIMEOUT
            )
            return text, "easyocr", 0.9 if text else 0.0
            
        except Exception as e:
            return "", "easyocr", 0.0
    
    async def _run_ocrspace(self, image_data: bytes) -> Tuple[str, str, float]:
        if not Config.OCR_SPACE_KEY:
            return "", "ocrspace", 0.0
        
        try:
            b64 = base64.b64encode(image_data).decode()
            data = {
                'apikey': Config.OCR_SPACE_KEY,
                'base64Image': f'data:image/png;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true'
            }
            
            async with self.session.post(
                'https://api.ocr.space/parse/image',
                data=data
            ) as resp:
                result = await resp.json()
                if result.get('OCRExitCode') == 1:
                    parsed = result.get('ParsedResults', [{}])[0]
                    text = parsed.get('ParsedText', '')
                    return text, "ocrspace", 0.85 if text else 0.0
                return "", "ocrspace", 0.0
                
        except Exception as e:
            return "", "ocrspace", 0.0
    
    def _fuse_results(self, results: List) -> Tuple[str, List[str]]:
        texts = []
        engines = []
        
        for result in results:
            if isinstance(result, Exception):
                continue
            text, engine, conf = result
            if text and len(text.strip()) > 3:
                texts.append(text)
                engines.append(engine)
        
        if not texts:
            return "", []
        
        # Deduplicate lines
        seen = set()
        all_lines = []
        for text in texts:
            for line in text.split('\n'):
                clean = re.sub(r'[^\w@]', '', line).lower()
                if clean and clean not in seen and len(clean) >= 3:
                    seen.add(clean)
                    all_lines.append(line)
        
        return '\n'.join(all_lines), engines
    
    def _extract_usernames(self, text: str, hint: Optional[str] = None) -> List[DetectedUser]:
        users = []
        lines = text.split('\n')
        
        # Patterns
        patterns = [
            (r'[@＠﹫]([a-z][a-z0-9_]{2,19})\b', 'at_mention', 0.90),
            (r'roblox\.com/users/(\d+)', 'url_id', 0.98),
            (r'\b([a-z][a-z0-9_]{2,19})\b', 'standalone', 0.60),
        ]
        
        for i, line in enumerate(lines):
            for pattern, source, conf in patterns:
                for match in re.finditer(pattern, line, re.IGNORECASE):
                    if source == 'url_id':
                        username = f"ID:{match.group(1)}"
                    else:
                        username = match.group(1).lstrip('@')
                    
                    if not self._is_valid_username(username):
                        continue
                    
                    # Boost confidence if hint matches
                    if hint and username.lower() == hint.lower().lstrip('@'):
                        conf = 1.0
                        source = 'hint_match'
                    
                    users.append(DetectedUser(
                        username=username,
                        display_name=None,
                        confidence=conf,
                        source=source,
                        context=line.strip()[:100]
                    ))
        
        # Deduplicate
        seen = {}
        for user in sorted(users, key=lambda x: x.confidence, reverse=True):
            key = user.username.lower()
            if key not in seen:
                seen[key] = user
        
        return list(seen.values())
    
    def _is_valid_username(self, username: str) -> bool:
        if not username or len(username) < 3 or len(username) > 20:
            return False
        
        exclude = {
            'roblox', 'profile', 'home', 'games', 'friends', 'inventory',
            'avatar', 'shop', 'create', 'about', 'chat', 'trade', 'premium',
            'settings', 'search', 'menu', 'play', 'join', 'exit', 'back',
            'online', 'offline', 'studio', 'catalog', 'develop', 'groups',
            'the', 'and', 'for', 'you', 'are', 'user', 'name', 'display'
        }
        
        if username.lower() in exclude:
            return False
        
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', username):
            return False
        
        return True

# ═══════════════════════════════════════════════════════════
# ROBLOX API
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: AsyncCache):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = cache
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "Mozilla/5.0"}
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        verified = []
        
        for user in users[:5]:  # Max 5
            # Check cache
            cache_key = f"user:{user.username.lower()}"
            cached = await self.cache.get(cache_key)
            
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
                verified.append({
                    'profile': profile,
                    'detected': user,
                    'score': user.confidence,
                    'cached': False
                })
                await self.cache.set(cache_key, profile, ttl=600)
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, username: str) -> Optional[Dict]:
        try:
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
                
                user_id = data['data'][0]['id']
                
                # Get full profile
                async with self.session.get(
                    f'https://users.roblox.com/v1/users/{user_id}'
                ) as resp2:
                    if resp2.status != 200:
                        return None
                    profile = await resp2.json()
                    
                    # Get avatar
                    try:
                        async with self.session.get(
                            f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png'
                        ) as resp3:
                            if resp3.status == 200:
                                thumb = await resp3.json()
                                if thumb.get('data'):
                                    profile['thumbnailUrl'] = thumb['data'][0].get('imageUrl')
                    except:
                        pass
                    
                    return profile
                    
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    async def search_similar(self, username: str) -> List[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5'
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
        self.pool: Optional[asyncpg.Pool] = None
        self.json_path = "data"
        self._whitelist: Set[str] = set()
        os.makedirs(self.json_path, exist_ok=True)
        
    async def setup(self):
        if DB_AVAILABLE and Config.DATABASE_URL:
            try:
                self.pool = await asyncpg.create_pool(
                    Config.DATABASE_URL,
                    min_size=2, max_size=10
                )
                await self._init_tables()
                logger.info("✅ PostgreSQL connected")
            except Exception as e:
                logger.error(f"❌ PostgreSQL failed: {e}")
        
        # Load whitelist from file/DB
        await self._load_whitelist()
    
    async def _init_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    user_id TEXT PRIMARY KEY,
                    added_by TEXT,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id TEXT PRIMARY KEY,
                    data JSONB DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
    
    async def _load_whitelist(self):
        """Load whitelist from database or JSON"""
        self._whitelist = {Config.OWNER_ID}  # Always include owner
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT user_id FROM whitelist")
                    for row in rows:
                        self._whitelist.add(str(row['user_id']))
                logger.info(f"✅ Loaded {len(self._whitelist)} whitelisted users from DB")
            except Exception as e:
                logger.error(f"DB whitelist load failed: {e}")
        
        # Also try JSON backup
        try:
            path = os.path.join(self.json_path, "whitelist.json")
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    self._whitelist.update(str(u) for u in data.get('users', []))
                logger.info(f"✅ Loaded whitelist from JSON, total: {len(self._whitelist)}")
        except Exception as e:
            logger.error(f"JSON whitelist load failed: {e}")
    
    async def add_to_whitelist(self, user_id: str, added_by: str) -> bool:
        user_id = str(user_id)
        if user_id in self._whitelist:
            return False
        
        self._whitelist.add(user_id)
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO whitelist (user_id, added_by) VALUES ($1, $2)
                        ON CONFLICT (user_id) DO NOTHING
                    """, user_id, added_by)
            except Exception as e:
                logger.error(f"DB whitelist add failed: {e}")
        
        # Always save to JSON as backup
        try:
            path = os.path.join(self.json_path, "whitelist.json")
            data = {'users': list(self._whitelist)}
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"JSON whitelist save failed: {e}")
        
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
            except Exception as e:
                logger.error(f"DB whitelist remove failed: {e}")
        
        # Update JSON
        try:
            path = os.path.join(self.json_path, "whitelist.json")
            data = {'users': list(self._whitelist)}
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"JSON whitelist save failed: {e}")
        
        return True
    
    def is_whitelisted(self, user_id: str) -> bool:
        return str(user_id) in self._whitelist
    
    def get_whitelist(self) -> Set[str]:
        return self._whitelist.copy()
    
    async def get_user_stats(self, user_id: str) -> UserStats:
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT data FROM user_stats WHERE user_id = $1", user_id
                    )
                    if row:
                        data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
                        return UserStats(user_id=user_id, **data)
            except Exception as e:
                logger.error(f"DB stats error: {e}")
        
        # JSON fallback
        try:
            path = os.path.join(self.json_path, f"{user_id}.json")
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    return UserStats(user_id=user_id, **data)
        except:
            pass
        
        return UserStats(user_id=user_id)
    
    async def save_user_stats(self, stats: UserStats):
        data = {
            'total_scans': stats.total_scans,
            'successful_scans': stats.successful_scans,
            'failed_scans': stats.failed_scans,
            'last_scan': stats.last_scan.isoformat() if stats.last_scan else None,
            'favorite_users': stats.favorite_users
        }
        
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO user_stats (user_id, data, updated_at)
                        VALUES ($1, $2, NOW())
                        ON CONFLICT (user_id) DO UPDATE SET
                            data = EXCLUDED.data,
                            updated_at = NOW()
                    """, stats.user_id, json.dumps(data))
            except Exception as e:
                logger.error(f"DB save error: {e}")
        
        # JSON backup
        try:
            path = os.path.join(self.json_path, f"{stats.user_id}.json")
            with open(path, 'w') as f:
                json.dump(data, f, default=str)
        except Exception as e:
            logger.error(f"JSON save error: {e}")

# ═══════════════════════════════════════════════════════════
# DISCORD BOT
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
        
        self.db = DatabaseManager()
        self.cache = AsyncCache(maxsize=2000, ttl=300)
        self.ocr = MultiEngineOCR()
        self.roblox = RobloxAPI(self.cache)
        
        self.user_cooldowns: Dict[str, float] = {}
        self.cooldown_seconds = 60.0 / Config.RATE_LIMIT_PER_MINUTE
        
    async def setup_hook(self):
        logger.info("🔧 Initializing...")
        
        await self.db.setup()
        await self.ocr.setup()
        await self.roblox.setup()
        
        self._register_commands()
        await self._sync_commands()
        
        logger.info(f"✅ Bot ready! Whitelisted: {len(self.db.get_whitelist())} users")
    
    def _register_commands(self):
        @self.tree.command(name="scan", description="🔍 Scan Roblox username from image")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        @app_commands.default_permissions()
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self._handle_scan(interaction, image, hint)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (Owner only)")
        @app_commands.describe(user="User ID to add/remove")
        @app_commands.default_permissions()
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self._handle_whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search Roblox user")
        @app_commands.describe(username="Username to search")
        @app_commands.default_permissions()
        async def search_cmd(interaction: discord.Interaction, username: str):
            await self._handle_search(interaction, username)
        
        @self.tree.command(name="stats", description="📊 Your statistics")
        @app_commands.default_permissions()
        async def stats_cmd(interaction: discord.Interaction):
            await self._handle_stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Bot status")
        @app_commands.default_permissions()
        async def ping_cmd(interaction: discord.Interaction):
            await self._handle_ping(interaction)
        
        @self.tree.command(name="help", description="❓ Help")
        @app_commands.default_permissions()
        async def help_cmd(interaction: discord.Interaction):
            await self._handle_help(interaction)
    
    async def _sync_commands(self):
        for attempt in range(3):
            try:
                synced = await self.tree.sync()
                logger.info(f"✅ Synced {len(synced)} commands")
                return
            except discord.HTTPException as e:
                if e.status == 429:
                    await asyncio.sleep(5)
                else:
                    raise
    
    async def _check_whitelist(self, user_id: str) -> bool:
        """Check if user is whitelisted"""
        return self.db.is_whitelisted(user_id)
    
    async def _handle_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
        user_id = str(interaction.user.id)
        
        # Check whitelist
        if not await self._check_whitelist(user_id):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⛔ Access Denied",
                    description="You're not whitelisted. Contact the bot owner.",
                    color=0xFF0000
                ),
                ephemeral=True
            )
            return
        
        # Check cooldown
        now = time.time()
        if user_id in self.user_cooldowns and now < self.user_cooldowns[user_id]:
            remaining = int(self.user_cooldowns[user_id] - now)
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⏰ Cooldown",
                    description=f"Wait {remaining}s",
                    color=0xFFA500
                ),
                ephemeral=True
            )
            return
        
        self.user_cooldowns[user_id] = now + self.cooldown_seconds
        
        # Validate image
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ File Too Large", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Download
            async with aiohttp.ClientSession() as session:
                async with session.get(image.url, timeout=10) as resp:
                    if resp.status != 200:
                        raise Exception("Download failed")
                    img_data = await resp.read()
            
            # OCR
            result = await self.ocr.scan(img_data, hint)
            
            if not result.success:
                embed = discord.Embed(
                    title="❌ No Username Found",
                    description="Could not detect a valid Roblox username.",
                    color=0xFF6B6B
                )
                if result.raw_text:
                    embed.add_field(name="Detected Text", value=f"```{result.raw_text[:300]}```", inline=False)
                await interaction.followup.send(embed=embed)
                return
            
            # Verify
            verified = await self.roblox.verify_users(result.detected_users)
            
            if not verified:
                embed = discord.Embed(
                    title="❌ User Not Found",
                    description=f"`@{result.detected_users[0].username}` doesn't exist.",
                    color=0xFF6B6B
                )
                # Search similar
                similar = await self.roblox.search_similar(result.detected_users[0].username)
                if similar:
                    embed.add_field(
                        name="Did you mean?",
                        value="\n".join(f"• @{s['name']}" for s in similar[:3]),
                        inline=False
                    )
                await interaction.followup.send(embed=embed)
                return
            
            # Success
            best = verified[0]
            profile = best['profile']
            detected = best['detected']
            
            embed = self._create_embed(profile, detected, result.scan_time, best['score'])
            embed.set_image(url=image.url)
            
            view = ResultView(profile, self, user_id)
            await interaction.followup.send(embed=embed, view=view)
            
            # Save stats
            stats = await self.db.get_user_stats(user_id)
            stats.total_scans += 1
            stats.successful_scans += 1
            if profile['name'] not in stats.favorite_users:
                stats.favorite_users.insert(0, profile['name'])
                stats.favorite_users = stats.favorite_users[:10]
            stats.last_scan = datetime.utcnow()
            await self.db.save_user_stats(stats)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
            )
    
    def _create_embed(self, profile: Dict, detected: DetectedUser, scan_time: float, score: float) -> discord.Embed:
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
        embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
        
        created = str(profile.get('created', 'Unknown'))[:10]
        embed.add_field(name="📅 Created", value=created, inline=True)
        embed.add_field(name="⚡ Scan Time", value=f"{scan_time:.2f}s", inline=True)
        
        if profile.get('description'):
            desc = profile['description'][:200]
            if len(profile['description']) > 200:
                desc += "..."
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        if profile.get('thumbnailUrl'):
            embed.set_thumbnail(url=profile['thumbnailUrl'])
        
        embed.set_footer(text="TRUE OMEGA v3.0")
        return embed
    
    async def _handle_whitelist(self, interaction: discord.Interaction, user: str):
        """Handle whitelist management"""
        # Only owner can use this
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Owner Only", color=0xFF0000),
                ephemeral=True
            )
            return
        
        # Parse user ID
        target = re.sub(r'[<@!>]', '', user).strip()
        if not target.isdigit():
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Invalid User ID", color=0xFF0000),
                ephemeral=True
            )
            return
        
        target = str(target)
        
        await interaction.response.defer(ephemeral=True)
        
        # Check current status
        is_whitelisted = self.db.is_whitelisted(target)
        
        if is_whitelisted:
            # Remove from whitelist
            if target == Config.OWNER_ID:
                await interaction.followup.send(
                    embed=discord.Embed(title="⛔ Cannot remove owner", color=0xFF0000),
                    ephemeral=True
                )
                return
            
            success = await self.db.remove_from_whitelist(target)
            if success:
                embed = discord.Embed(
                    title="✅ Removed from Whitelist",
                    description=f"User ID: `{target}`",
                    color=0x00FF00
                )
            else:
                embed = discord.Embed(title="❌ Failed to remove", color=0xFF0000)
        else:
            # Add to whitelist
            success = await self.db.add_to_whitelist(target, str(interaction.user.id))
            if success:
                # Try to get user info
                try:
                    user_obj = await self.fetch_user(int(target))
                    name = f"@{user_obj.name}" if user_obj else target
                except:
                    name = target
                
                embed = discord.Embed(
                    title="✅ Added to Whitelist",
                    description=f"{name} (`{target}`)",
                    color=0x00FF00
                )
            else:
                embed = discord.Embed(title="❌ Already whitelisted", color=0xFFA500)
        
        # Show current count
        embed.set_footer(text=f"Total whitelisted: {len(self.db.get_whitelist())}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _handle_search(self, interaction: discord.Interaction, username: str):
        if not self.db.is_whitelisted(str(interaction.user.id)):
            await interaction.response.send_message("⛔ Not whitelisted!", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        detected = DetectedUser(username=username, display_name=None, confidence=1.0, source="direct")
        verified = await self.roblox.verify_users([detected])
        
        if verified:
            best = verified[0]
            embed = self._create_embed(best['profile'], detected, 0.1, 1.0)
            view = ResultView(best['profile'], self, str(interaction.user.id))
            await interaction.followup.send(embed=embed, view=view)
        else:
            similar = await self.roblox.search_similar(username)
            embed = discord.Embed(
                title=f"🔎 Results for '{username}'",
                color=0x00D4AA
            )
            for s in similar[:5]:
                embed.add_field(
                    name=f"{s.get('displayName', s['name'])} (@{s['name']})",
                    value=f"[View](https://roblox.com/users/{s['id']}/profile)",
                    inline=False
                )
            await interaction.followup.send(embed=embed)
    
    async def _handle_stats(self, interaction: discord.Interaction):
        stats = await self.db.get_user_stats(str(interaction.user.id))
        
        embed = discord.Embed(
            title=f"📊 {interaction.user.name}'s Stats",
            color=0x00D4AA
        )
        embed.add_field(name="Total", value=str(stats.total_scans), inline=True)
        embed.add_field(name="Success", value=f"{stats.success_rate:.1f}%", inline=True)
        embed.add_field(name="Successful", value=str(stats.successful_scans), inline=True)
        
        if stats.favorite_users:
            embed.add_field(
                name="⭐ Favorites",
                value="\n".join(f"• @{u}" for u in stats.favorite_users[:5]),
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _handle_ping(self, interaction: discord.Interaction):
        latency = round(self.latency * 1000)
        uptime = timedelta(seconds=int(time.time() - self.start_time))
        
        embed = discord.Embed(title="🏓 Pong!", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
        embed.add_field(name="Uptime", value=str(uptime), inline=True)
        embed.add_field(name="Whitelisted", value=str(len(self.db.get_whitelist())), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _handle_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎯 TRUE OMEGA v3.0",
            description="Next-gen Roblox scanner",
            color=0x00D4AA
        )
        commands = [
            ("/scan <image> [hint]", "Scan screenshot for usernames"),
            ("/search <username>", "Direct user lookup"),
            ("/whitelist <user_id>", "Manage whitelist (owner only)"),
            ("/stats", "Your statistics"),
            ("/ping", "Bot status"),
        ]
        for name, desc in commands:
            embed.add_field(name=name, value=desc, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════════
class ResultView(discord.ui.View):
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
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="⭐")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        stats = await self.bot.db.get_user_stats(self.user_id)
        
        if self.profile['name'] in stats.favorite_users:
            await interaction.response.send_message("Already saved!", ephemeral=True)
            return
        
        stats.favorite_users.insert(0, self.profile['name'])
        stats.favorite_users = stats.favorite_users[:10]
        await self.bot.db.save_user_stats(stats)
        
        await interaction.response.send_message(f"⭐ Saved @{self.profile['name']}!", ephemeral=True)

# ═══════════════════════════════════════════════════════════
# HEALTH CHECK & MAIN
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text='OK'))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080)))
    await site.start()

async def main():
    health_task = asyncio.create_task(health_server())
    bot = TrueOmegaBot()
    
    try:
        await bot.start(Config.TOKEN)
    finally:
        await bot.close()
        health_task.cancel()

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"Fatal: {e}")
            time.sleep(10)
