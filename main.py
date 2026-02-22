"""
🎯 TRUE OMEGA ULTIMATE v3.2 - Fixed OCR + Friends Feature
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
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
import logging

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("true_omega")

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '52428800'))
    OCR_TIMEOUT = int(os.getenv('OCR_TIMEOUT', '15'))
    DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT', '15'))
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT', '10'))

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

logger.info(f"🔧 PIL={PIL_AVAILABLE}, Tesseract={TESSERACT_AVAILABLE}, EasyOCR={EASYOCR_AVAILABLE}, CV2={CV2_AVAILABLE}")

# ═══════════════════════════════════════════════════════════
# ASYNC CACHE
# ═══════════════════════════════════════════════════════════
class AsyncCache:
    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self.cache = {}
        self.maxsize = maxsize
        self.ttl = ttl
        self._lock = asyncio.Lock()
    
    async def get(self, key: str):
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

# ═══════════════════════════════════════════════════════════
# IMPROVED OCR - Better username detection
# ═══════════════════════════════════════════════════════════
class ImprovedOCR:
    def __init__(self):
        self.session = None
        self.easyocr_reader = None
        self._easyocr_ready = False
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=25),
            headers={"User-Agent": "TrueOmegaBot/3.2"}
        )
        
        # Init EasyOCR in background
        if EASYOCR_AVAILABLE:
            asyncio.create_task(self._init_easyocr())
    
    async def _init_easyocr(self):
        try:
            import concurrent.futures
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                self.easyocr_reader = await loop.run_in_executor(
                    pool, 
                    lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
                )
            self._easyocr_ready = True
            logger.info("✅ EasyOCR ready")
        except Exception as e:
            logger.error(f"EasyOCR init failed: {e}")
    
    def preprocess(self, image_data: bytes) -> List[bytes]:
        """Generate multiple preprocessed versions"""
        if not PIL_AVAILABLE:
            return [image_data]
        
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            w, h = img.size
            versions = [image_data]  # Original
            
            # Upscale if small (Roblox usernames are often small)
            if w < 800 or h < 400:
                scaled = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                scaled.save(buf, format='PNG')
                versions.append(buf.getvalue())
            
            # High contrast
            contrast = ImageEnhance.Contrast(img).enhance(2.0)
            contrast = ImageEnhance.Sharpness(contrast).enhance(2.0)
            buf = io.BytesIO()
            contrast.save(buf, format='PNG')
            versions.append(buf.getvalue())
            
            # Inverted (for dark mode screenshots)
            inverted = ImageOps.invert(img)
            inverted = ImageEnhance.Contrast(inverted).enhance(2.0)
            buf = io.BytesIO()
            inverted.save(buf, format='PNG')
            versions.append(buf.getvalue())
            
            return versions
            
        except Exception as e:
            logger.error(f"Preprocess error: {e}")
            return [image_data]
    
    async def scan(self, image_data: bytes, hint: str = None) -> ScanResult:
        start = time.time()
        
        # Preprocess
        versions = self.preprocess(image_data)
        
        # Run OCR on all versions
        all_texts = []
        engines_used = []
        
        # Tesseract on all versions
        if TESSERACT_AVAILABLE:
            for i, version in enumerate(versions):
                try:
                    text = await self._tesseract(version)
                    if text:
                        all_texts.append(text)
                        engines_used.append(f"tesseract_v{i}")
                except Exception as e:
                    logger.debug(f"Tesseract v{i} failed: {e}")
        
        # EasyOCR if ready
        if self._easyocr_ready and self.easyocr_reader:
            try:
                text = await self._easyocr(versions[0])
                if text:
                    all_texts.append(text)
                    engines_used.append("easyocr")
            except Exception as e:
                logger.debug(f"EasyOCR failed: {e}")
        
        # OCR.space
        if Config.OCR_SPACE_KEY:
            try:
                text = await self._ocrspace(versions[0])
                if text:
                    all_texts.append(text)
                    engines_used.append("ocrspace")
            except Exception as e:
                logger.debug(f"OCR.space failed: {e}")
        
        if not all_texts:
            return ScanResult(success=False, detected_users=[], raw_text="")
        
        # Combine all texts
        combined = '\n'.join(all_texts)
        
        # Extract usernames with improved patterns
        users = self._extract_usernames(combined, hint)
        
        return ScanResult(
            success=len(users) > 0,
            detected_users=users,
            raw_text=combined[:1000],
            scan_time=time.time() - start,
            engines_used=engines_used
        )
    
    async def _tesseract(self, image_data: bytes) -> str:
        def _run():
            img = Image.open(io.BytesIO(image_data))
            # Optimized config for username detection
            config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@'
            return pytesseract.image_to_string(img, config=config)
        
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=10.0
        )
    
    async def _easyocr(self, image_data: bytes) -> str:
        if not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return ""
        
        def _run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, paragraph=True)
            return '\n'.join([r[1] for r in results])
        
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=12.0
        )
    
    async def _ocrspace(self, image_data: bytes) -> str:
        b64 = base64.b64encode(image_data).decode()
        data = {
            'apikey': Config.OCR_SPACE_KEY,
            'base64Image': f'data:image/png;base64,{b64}',
            'OCREngine': '2',
            'scale': 'true',
            'detectOrientation': 'true'
        }
        
        async with self.session.post(
            'https://api.ocr.space/parse/image',
            data=data,
            timeout=aiohttp.ClientTimeout(total=12)
        ) as resp:
            result = await resp.json()
            if result.get('OCRExitCode') == 1:
                parsed = result.get('ParsedResults', [{}])[0]
                return parsed.get('ParsedText', '')
            return ""
    
    def _extract_usernames(self, text: str, hint: str = None) -> List[DetectedUser]:
        """Improved username extraction with multiple patterns"""
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
        
        # Pattern 2: Display Name @ Username format (Roblox profile style)
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
        
        # Pattern 4: "username" with Roblox context nearby
        for i, line in enumerate(lines):
            line_lower = line.lower()
            # Check if line has Roblox context
            has_context = any(word in line_lower for word in ['roblox', 'profile', '@', 'user', 'display'])
            
            for match in re.finditer(r'\b([a-z][a-z0-9_]{2,19})\b', line):
                username = match.group(1)
                
                # Skip common words
                if username.lower() in {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 'friends', 'following', 'followers'}:
                    continue
                
                # Higher confidence if @ nearby or in context line
                conf = 0.70 if has_context else 0.50
                
                # Check surrounding lines for context
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
# ROBLOX API - With Friends Support
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: AsyncCache):
        self.session = None
        self.cache = cache
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
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
                verified.append({'profile': profile, 'detected': user, 'score': user.confidence})
                await self.cache.set(f"user:{user.username.lower()}", profile, ttl=600)
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, username: str) -> Optional[Dict]:
        try:
            # Handle ID: prefix
            if username.startswith("ID:"):
                user_id = int(username.split(":")[1])
                return await self._fetch_by_id(user_id)
            
            # Username lookup
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [username], "excludeBannedUsers": False},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                
                if not data.get('data'):
                    return None
                
                user_id = data['data'][0]['id']
                return await self._fetch_by_id(user_id)
                
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return None
    
    async def _fetch_by_id(self, user_id: int) -> Optional[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/{user_id}',
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                profile = await resp.json()
                
                # Get avatar
                try:
                    async with self.session.get(
                        f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png',
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp2:
                        if resp2.status == 200:
                            thumb = await resp2.json()
                            if thumb.get('data'):
                                profile['thumbnailUrl'] = thumb['data'][0].get('imageUrl')
                except:
                    pass
                
                return profile
        except Exception as e:
            logger.error(f"Fetch by ID error: {e}")
            return None
    
    async def get_friends(self, user_id: int) -> List[Dict]:
        """Get user's friends with avatars"""
        try:
            # Get friends list
            async with self.session.get(
                f'https://friends.roblox.com/v1/users/{user_id}/friends',
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return []
                
                data = await resp.json()
                friends = data.get('data', [])
                
                if not friends:
                    return []
                
                # Get avatars for all friends (batch request)
                friend_ids = [str(f['id']) for f in friends[:50]]  # Max 50 friends
                
                try:
                    async with self.session.post(
                        'https://thumbnails.roblox.com/v1/batch',
                        json={
                            "requests": [
                                {
                                    "requestId": f"{fid}:undefined:150x150:png:regular",
                                    "type": "AvatarHeadShot",
                                    "targetId": int(fid),
                                    "size": "150x150",
                                    "format": "png"
                                } for fid in friend_ids
                            ]
                        },
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp2:
                        if resp2.status == 200:
                            thumbs = await resp2.json()
                            thumb_map = {}
                            for t in thumbs.get('data', []):
                                fid = t.get('requestId', '').split(':')[0]
                                thumb_map[fid] = t.get('imageUrl')
                            
                            # Add thumbnails to friends
                            for friend in friends:
                                friend['thumbnailUrl'] = thumb_map.get(str(friend['id']))
                except Exception as e:
                    logger.error(f"Friend thumbnails error: {e}")
                
                return friends[:25]  # Return top 25
                
        except Exception as e:
            logger.error(f"Get friends error: {e}")
            return []
    
    async def search_similar(self, username: str) -> List[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5',
                timeout=aiohttp.ClientTimeout(total=8)
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
            except Exception as e:
                logger.error(f"DB failed: {e}")
        
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
    
    async def get_stats(self, user_id: str):
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT data FROM user_stats WHERE user_id = $1", user_id)
                    if row:
                        return json.loads(row['data']) if isinstance(row['data'], str) else row['data']
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
    
    async def save_stats(self, user_id: str, data: dict):
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO user_stats (user_id, data) VALUES ($1, $2)
                        ON CONFLICT (user_id) DO UPDATE SET data = $2
                    """, user_id, json.dumps(data))
            except:
                pass
        
        try:
            with open(os.path.join(self.json_path, f"{user_id}.json"), 'w') as f:
                json.dump(data, f, default=str)
        except:
            pass

# ═══════════════════════════════════════════════════════════
# BOT
# ═══════════════════════════════════════════════════════════
class TrueOmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = DatabaseManager()
        self.cache = AsyncCache()
        self.ocr = ImprovedOCR()
        self.roblox = RobloxAPI(self.cache)
        self.cooldowns = {}
        
    async def setup_hook(self):
        logger.info("🔧 Starting...")
        
        await self.db.setup()
        await self.ocr.setup()
        await self.roblox.setup()
        
        self._register_commands()
        await self._sync_commands()
        
        logger.info("✅ Bot ready!")
    
    def _register_commands(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username")
        @app_commands.describe(image="Screenshot", hint="Optional username hint")
        @app_commands.default_permissions()
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self._scan(interaction, image, hint)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (owner only)")
        @app_commands.describe(user="User ID")
        @app_commands.default_permissions()
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self._whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search user by username")
        @app_commands.describe(username="Username")
        @app_commands.default_permissions()
        async def search_cmd(interaction: discord.Interaction, username: str):
            await self._search(interaction, username)
        
        @self.tree.command(name="stats", description="📊 Your stats")
        @app_commands.default_permissions()
        async def stats_cmd(interaction: discord.Interaction):
            await self._stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Status")
        @app_commands.default_permissions()
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
        
        # Cooldown check
        now = time.time()
        if user_id in self.cooldowns and now < self.cooldowns[user_id]:
            await interaction.response.send_message(
                embed=discord.Embed(title="⏰ Cooldown", description=f"Wait {int(self.cooldowns[user_id] - now)}s", color=0xFFA500),
                ephemeral=True
            )
            return
        
        self.cooldowns[user_id] = now + 6
        
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ File too large", color=0xFF0000),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Download with timeout
            async with aiohttp.ClientSession() as session:
                async with session.get(image.url, timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
            
            # OCR
            result = await self.ocr.scan(img_data, hint)
            
            if not result.success:
                # Show what was detected for debugging
                embed = discord.Embed(
                    title="❌ No Username Found",
                    description="Could not detect a valid Roblox username.",
                    color=0xFF6B6B
                )
                if result.raw_text:
                    # Show detected text but filter out noise
                    clean_text = '\n'.join([
                        line for line in result.raw_text.split('\n') 
                        if len(line.strip()) > 2 and not line.strip().isdigit()
                    ][:20])  # Limit lines
                    if clean_text:
                        embed.add_field(
                            name="📝 Detected Text (debug)",
                            value=f"```{clean_text[:800]}```",
                            inline=False
                        )
                embed.add_field(
                    name="💡 Tips",
                    value="• Make sure the @username is clearly visible\n• Try using the `hint` parameter with the username\n• Ensure the image isn't too blurry or dark",
                    inline=False
                )
                embed.set_footer(text=f"Engines tried: {', '.join(result.engines_used) or 'none'}")
                await interaction.followup.send(embed=embed)
                return
            
            # Verify users
            verified = await self.roblox.verify_users(result.detected_users)
            
            if not verified:
                # Try to suggest similar
                similar = await self.roblox.search_similar(result.detected_users[0].username)
                
                embed = discord.Embed(
                    title="❌ User Not Found",
                    description=f"`@{result.detected_users[0].username}` doesn't exist on Roblox.",
                    color=0xFF6B6B
                )
                if similar:
                    embed.add_field(
                        name="🔍 Did you mean?",
                        value='\n'.join(f"• [@{s['name']}](https://roblox.com/users/{s['id']}/profile)" for s in similar[:5]),
                        inline=False
                    )
                await interaction.followup.send(embed=embed)
                return
            
            # SUCCESS - Show result with friends button
            best = verified[0]
            profile = best['profile']
            detected = best['detected']
            
            embed = self._create_profile_embed(profile, detected, result.scan_time, best['score'])
            embed.set_image(url=image.url)
            
            # Create view with friends button
            view = ResultView(profile, self, user_id)
            
            await interaction.followup.send(embed=embed, view=view)
            
            # Save stats
            stats = await self.db.get_stats(user_id)
            stats['total_scans'] = stats.get('total_scans', 0) + 1
            stats['successful_scans'] = stats.get('successful_scans', 0) + 1
            if profile['name'] not in stats.get('favorite_users', []):
                stats['favorite_users'] = [profile['name']] + stats.get('favorite_users', [])[:9]
            await self.db.save_stats(user_id, stats)
            
        except Exception as e:
            logger.error(f"Scan error: {traceback.format_exc()}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
            )
    
    def _create_profile_embed(self, profile: Dict, detected: DetectedUser, scan_time: float, score: float) -> discord.Embed:
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
            embed.add_field(name="📝 Display Name", value=detected.display_name, inline=True)
        
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
        
        embed.set_footer(text="TRUE OMEGA v3.2 | Click 'View Friends' below")
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
        embed = discord.Embed(title="📊 Stats", color=0x00D4AA)
        embed.add_field(name="Total Scans", value=str(stats.get('total_scans', 0)), inline=True)
        embed.add_field(name="Success Rate", value=f"{(stats.get('successful_scans', 0) / max(stats.get('total_scans', 1), 1) * 100):.1f}%", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
        embed.add_field(name="Whitelisted", value=str(len(self.db._whitelist)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# UI COMPONENTS - With Friends Feature
# ═══════════════════════════════════════════════════════════
class ResultView(discord.ui.View):
    def __init__(self, profile: Dict, bot: TrueOmegaBot, user_id: str):
        super().__init__(timeout=300)
        self.profile = profile
        self.bot = bot
        self.user_id = user_id
        
        # Profile link
        self.add_item(discord.ui.Button(
            label="View Profile",
            style=discord.ButtonStyle.link,
            url=f"https://roblox.com/users/{profile['id']}/profile",
            emoji="🔗"
        ))
    
    @discord.ui.button(label="View Friends", style=discord.ButtonStyle.primary, emoji="👥")
    async def view_friends(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        
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
            
            # Create friends list embed
            embed = discord.Embed(
                title=f"👥 {self.profile.get('displayName', self.profile['name'])}'s Friends",
                description=f"Showing {len(friends)} friends",
                color=0x00D4AA
            )
            
            # Add friends as fields (max 25)
            for friend in friends[:25]:
                name = friend.get('displayName') or friend['name']
                username = friend['name']
                friend_id = friend['id']
                
                value = f"[@{username}](https://roblox.com/users/{friend_id}/profile)"
                
                # Add online status if available
                if friend.get('isOnline'):
                    value += " 🟢"
                
                embed.add_field(
                    name=f"{name}",
                    value=value,
                    inline=True
                )
            
            # If there are thumbnails, we could send them separately or use a different view
            # For now, just show the list
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
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
            await interaction.response.send_message("Already saved!", ephemeral=True)
            return
        
        stats['favorite_users'] = [self.profile['name']] + stats.get('favorite_users', [])[:9]
        await self.bot.db.save_stats(self.user_id, stats)
        
        await interaction.response.send_message(f"⭐ Saved @{self.profile['name']}!", ephemeral=True)

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def health():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text='OK'))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080))).start()

async def main():
    asyncio.create_task(health())
    bot = TrueOmegaBot()
    
    try:
        await bot.start(Config.TOKEN)
    finally:
        await bot.close()

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"Fatal: {e}")
            time.sleep(10)
