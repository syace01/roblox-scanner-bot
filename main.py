"""
🎯 TRUE OMEGA ULTIMATE v3.1 - Fixed hanging issues
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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
import threading

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════
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
    OCR_TIMEOUT = int(os.getenv('OCR_TIMEOUT', '10'))
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
    confidence: float
    source: str

@dataclass
class ScanResult:
    success: bool
    detected_users: List[DetectedUser]
    scan_time: float = 0.0
    engines_used: List[str] = field(default_factory=list)
    error: str = ""

# ═══════════════════════════════════════════════════════════
# FAST OCR - No blocking init
# ═══════════════════════════════════════════════════════════
class FastOCR:
    def __init__(self):
        self.session = None
        self.easyocr_reader = None
        self._easyocr_ready = False
        self._init_lock = asyncio.Lock()
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "TrueOmegaBot/3.1"}
        )
        # Start EasyOCR init in background without blocking
        if EASYOCR_AVAILABLE:
            asyncio.create_task(self._init_easyocr_background())
    
    async def _init_easyocr_background(self):
        """Initialize EasyOCR in background without blocking"""
        try:
            logger.info("🔄 Initializing EasyOCR in background...")
            # Run in thread pool to not block event loop
            loop = asyncio.get_event_loop()
            
            def _init():
                return easyocr.Reader(['en'], gpu=False, verbose=False)
            
            # Use shorter timeout for init
            self.easyocr_reader = await asyncio.wait_for(
                loop.run_in_executor(None, _init),
                timeout=30.0
            )
            self._easyocr_ready = True
            logger.info("✅ EasyOCR ready")
        except Exception as e:
            logger.error(f"EasyOCR init failed: {e}")
    
    async def scan(self, image_data: bytes, hint: str = None) -> ScanResult:
        start = time.time()
        engines_used = []
        
        # Use only fast engines first, EasyOCR only if ready
        tasks = []
        
        # Tesseract (fastest)
        if TESSERACT_AVAILABLE:
            tasks.append(self._tesseract(image_data))
        
        # OCR.space (if configured)
        if Config.OCR_SPACE_KEY:
            tasks.append(self._ocrspace(image_data))
        
        # EasyOCR only if ready
        if self._easyocr_ready and self.easyocr_reader:
            tasks.append(self._easyocr(image_data))
        
        # Wait for results with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=Config.OCR_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("OCR timeout - using partial results")
            results = []
        
        # Process results
        texts = []
        for result in results:
            if isinstance(result, Exception):
                continue
            text, engine = result
            if text:
                texts.append(text)
                engines_used.append(engine)
        
        if not texts:
            return ScanResult(success=False, detected_users=[], error="No OCR results", scan_time=time.time()-start)
        
        # Extract users
        combined = '\n'.join(texts)
        users = self._extract_users(combined, hint)
        
        return ScanResult(
            success=len(users) > 0,
            detected_users=users,
            scan_time=time.time() - start,
            engines_used=engines_used
        )
    
    async def _tesseract(self, image_data: bytes):
        if not TESSERACT_AVAILABLE:
            return "", "tesseract"
        
        try:
            def _run():
                img = Image.open(io.BytesIO(image_data))
                return pytesseract.image_to_string(img, config='--psm 6')
            
            loop = asyncio.get_event_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=8.0
            )
            return text, "tesseract"
        except Exception as e:
            logger.debug(f"Tesseract error: {e}")
            return "", "tesseract"
    
    async def _easyocr(self, image_data: bytes):
        if not self.easyocr_reader or not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return "", "easyocr"
        
        try:
            def _run():
                nparr = np.frombuffer(image_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                results = self.easyocr_reader.readtext(img)
                return '\n'.join([r[1] for r in results])
            
            loop = asyncio.get_event_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=10.0
            )
            return text, "easyocr"
        except Exception as e:
            logger.debug(f"EasyOCR error: {e}")
            return "", "easyocr"
    
    async def _ocrspace(self, image_data: bytes):
        if not Config.OCR_SPACE_KEY:
            return "", "ocrspace"
        
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
                data=data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                if result.get('OCRExitCode') == 1:
                    parsed = result.get('ParsedResults', [{}])[0]
                    return parsed.get('ParsedText', ''), "ocrspace"
                return "", "ocrspace"
        except Exception as e:
            logger.debug(f"OCR.space error: {e}")
            return "", "ocrspace"
    
    def _extract_users(self, text: str, hint: str = None) -> List[DetectedUser]:
        users = []
        
        # Find @mentions
        for match in re.finditer(r'[@＠﹫]([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            username = match.group(1)
            conf = 0.90
            if hint and username.lower() == hint.lower().lstrip('@'):
                conf = 1.0
            users.append(DetectedUser(username=username, confidence=conf, source='@mention'))
        
        # Find URLs
        for match in re.finditer(r'roblox\.com/users/(\d+)', text, re.I):
            users.append(DetectedUser(username=f"ID:{match.group(1)}", confidence=0.98, source='url'))
        
        # Deduplicate
        seen = set()
        unique = []
        for u in sorted(users, key=lambda x: x.confidence, reverse=True):
            if u.username.lower() not in seen:
                seen.add(u.username.lower())
                unique.append(u)
        
        return unique

# ═══════════════════════════════════════════════════════════
# ROBLOX API
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: AsyncCache):
        self.session = None
        self.cache = cache
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8),
            headers={"User-Agent": "Mozilla/5.0"}
        )
    
    async def verify_users(self, users: List[DetectedUser]) -> List[Dict]:
        verified = []
        
        for user in users[:3]:  # Max 3
            # Check cache
            cached = await self.cache.get(f"user:{user.username.lower()}")
            if cached:
                verified.append({'profile': cached, 'score': user.confidence})
                continue
            
            # Fetch with timeout
            try:
                profile = await asyncio.wait_for(
                    self._fetch_user(user.username),
                    timeout=5.0
                )
                if profile:
                    verified.append({'profile': profile, 'score': user.confidence})
                    await self.cache.set(f"user:{user.username.lower()}", profile, ttl=600)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout fetching {user.username}")
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch_user(self, username: str):
        try:
            # Username lookup
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [username], "excludeBannedUsers": False},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                
                if not data.get('data'):
                    return None
                
                user_id = data['data'][0]['id']
                
                # Get profile
                async with self.session.get(
                    f'https://users.roblox.com/v1/users/{user_id}',
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp2:
                    if resp2.status != 200:
                        return None
                    profile = await resp2.json()
                    
                    # Get avatar
                    try:
                        async with self.session.get(
                            f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png',
                            timeout=aiohttp.ClientTimeout(total=3)
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (user_id TEXT PRIMARY KEY)
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (user_id TEXT PRIMARY KEY, data JSONB)
            """)
    
    async def _load_whitelist(self):
        self._whitelist = {Config.OWNER_ID}
        
        # From DB
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT user_id FROM whitelist")
                    for row in rows:
                        self._whitelist.add(str(row['user_id']))
            except Exception as e:
                logger.error(f"DB whitelist load: {e}")
        
        # From JSON
        try:
            path = os.path.join(self.json_path, "whitelist.json")
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    self._whitelist.update(str(u) for u in data.get('users', []))
        except Exception as e:
            logger.error(f"JSON whitelist load: {e}")
        
        logger.info(f"✅ Whitelist loaded: {len(self._whitelist)} users")
    
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
        
        # Save to JSON
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
        
        # JSON fallback
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
        self.ocr = FastOCR()
        self.roblox = RobloxAPI(self.cache)
        self.cooldowns = {}
        
    async def setup_hook(self):
        logger.info("🔧 Starting bot...")
        
        await self.db.setup()
        await self.ocr.setup()
        await self.roblox.setup()
        
        self._register_commands()
        await self._sync_commands()
        
        logger.info("✅ Bot ready!")
    
    def _register_commands(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username")
        @app_commands.describe(image="Screenshot", hint="Optional hint")
        @app_commands.default_permissions()
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self._scan(interaction, image, hint)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (owner only)")
        @app_commands.describe(user="User ID")
        @app_commands.default_permissions()
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self._whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search user")
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
        
        # Check whitelist
        if not self.db.is_whitelisted(user_id):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ Not Whitelisted", color=0xFF0000),
                ephemeral=True
            )
            return
        
        # Check cooldown
        now = time.time()
        if user_id in self.cooldowns and now < self.cooldowns[user_id]:
            await interaction.response.send_message(
                embed=discord.Embed(title="⏰ Cooldown", description=f"Wait {int(self.cooldowns[user_id] - now)}s", color=0xFFA500),
                ephemeral=True
            )
            return
        
        self.cooldowns[user_id] = now + 6  # 6 second cooldown
        
        # Check file size
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ File too large", color=0xFF0000),
                ephemeral=True
            )
            return
        
        # DEFER IMMEDIATELY - This is critical
        await interaction.response.defer(thinking=True)
        
        # Set a maximum total scan time
        try:
            result = await asyncio.wait_for(
                self._do_scan(interaction, image, hint),
                timeout=45.0  # Max 45 seconds total
            )
        except asyncio.TimeoutError:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⏱️ Scan Timeout",
                    description="The scan took too long. Try again with a clearer image.",
                    color=0xFF0000
                )
            )
    
    async def _do_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
        """Actual scan logic with individual timeouts"""
        user_id = str(interaction.user.id)
        
        # Download with timeout
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image.url, timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
        except asyncio.TimeoutError:
            await interaction.followup.send(embed=discord.Embed(title="❌ Download timeout", color=0xFF0000))
            return
        
        # OCR
        result = await self.ocr.scan(img_data, hint)
        
        if not result.success:
            embed = discord.Embed(title="❌ No username found", color=0xFF6B6B)
            if result.error:
                embed.description = result.error
            await interaction.followup.send(embed=embed)
            return
        
        # Verify
        verified = await self.roblox.verify_users(result.detected_users)
        
        if not verified:
            embed = discord.Embed(
                title="❌ User not found",
                description=f"`@{result.detected_users[0].username}` doesn't exist",
                color=0xFF6B6B
            )
            await interaction.followup.send(embed=embed)
            return
        
        # Success
        best = verified[0]
        profile = best['profile']
        
        embed = discord.Embed(
            title=f"{profile.get('displayName', profile['name'])}",
            url=f"https://roblox.com/users/{profile['id']}/profile",
            color=0x00FF00,
            timestamp=datetime.utcnow()
        )
        embed.description = f"**@{profile['name']}** | `{best['score']:.0%}`"
        embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
        embed.add_field(name="⚡ Time", value=f"{result.scan_time:.2f}s", inline=True)
        embed.set_image(url=image.url)
        embed.set_footer(text=f"Engines: {', '.join(result.engines_used)}")
        
        if profile.get('thumbnailUrl'):
            embed.set_thumbnail(url=profile['thumbnailUrl'])
        
        # Save stats
        stats = await self.db.get_stats(user_id)
        stats['total_scans'] = stats.get('total_scans', 0) + 1
        stats['successful_scans'] = stats.get('successful_scans', 0) + 1
        if profile['name'] not in stats.get('favorite_users', []):
            stats['favorite_users'] = [profile['name']] + stats.get('favorite_users', [])[:9]
        await self.db.save_stats(user_id, stats)
        
        await interaction.followup.send(embed=embed)
    
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
        
        users = [DetectedUser(username=username, confidence=1.0, source="direct")]
        verified = await self.roblox.verify_users(users)
        
        if verified:
            p = verified[0]['profile']
            embed = discord.Embed(title=p.get('displayName', p['name']), url=f"https://roblox.com/users/{p['id']}/profile", color=0x00FF00)
            embed.description = f"@{p['name']}"
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=discord.Embed(title="❌ Not found", color=0xFF0000))
    
    async def _stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(str(interaction.user.id))
        embed = discord.Embed(title="📊 Stats", color=0x00D4AA)
        embed.add_field(name="Scans", value=str(stats.get('total_scans', 0)), inline=True)
        embed.add_field(name="Success", value=str(stats.get('successful_scans', 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
        embed.add_field(name="Whitelist", value=str(len(self.db._whitelist)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
