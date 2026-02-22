"""
🚀 TRUE OMEGA v4.2 - FULLY WORKING VERSION
Fixed friends parsing, faster OCR, proper error handling
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
from datetime import datetime
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Tuple
from concurrent.futures import ThreadPoolExecutor
import logging

warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("omega")

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', '')
    REDIS_URL = os.getenv('REDIS_URL', '')
    
    # FAST TIMEOUTS
    DOWNLOAD_TIMEOUT = 6
    OCR_TIMEOUT = 5
    API_TIMEOUT = 5
    FRIENDS_TIMEOUT = 10
    
    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
    RATE_LIMIT = 15

Config.validate = lambda: logger.info(f"✅ Config loaded | Owner: {Config.OWNER_ID}") or None if Config.TOKEN else logger.error("❌ No DISCORD_TOKEN") or sys.exit(1)
Config.validate()

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════
import aiohttp
from aiohttp import TCPConnector
import discord
from discord import app_commands

try:
    from PIL import Image, ImageEnhance, ImageOps
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
# CACHE
# ═══════════════════════════════════════════════════════════
class SimpleCache:
    def __init__(self, maxsize=5000):
        self.cache = {}
        self.expiry = {}
        self.maxsize = maxsize
        self._lock = asyncio.Lock()
        self.redis = None
        
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
            return self.cache[key]
        if self.redis:
            try:
                data = await self.redis.get(f"o:{key}")
                if data:
                    val = json.loads(data)
                    self.cache[key] = val
                    self.expiry[key] = time.time() + 300
                    return val
            except:
                pass
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
class FriendData:
    id: int
    name: str  # This is the USERNAME from Roblox API
    display_name: str
    is_online: bool

# ═══════════════════════════════════════════════════════════
# OCR - FAST VERSION
# ═══════════════════════════════════════════════════════════
class OCRManager:
    def __init__(self):
        self.easyocr_reader = None
        self.easy_ready = False
        self.executor = ThreadPoolExecutor(max_workers=2)
        
    async def init_easyocr(self):
        if EASYOCR_AVAILABLE and not self.easy_ready:
            try:
                loop = asyncio.get_event_loop()
                self.easyocr_reader = await loop.run_in_executor(
                    None, lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
                )
                self.easy_ready = True
                logger.info("✅ EasyOCR ready")
            except Exception as e:
                logger.error(f"EasyOCR init: {e}")
    
    async def scan(self, image_data: bytes, hint: str = None) -> Tuple[bool, List[DetectedUser], str, List[str]]:
        start = time.time()
        all_texts = []
        engines = []
        
        # Preprocess
        versions = await self._preprocess(image_data)
        
        # Run Tesseract on all versions
        if TESSERACT_AVAILABLE:
            for img, name in versions:
                try:
                    text = await self._tesseract(img)
                    if text.strip():
                        all_texts.append(text)
                        engines.append(f"tess_{name}")
                except:
                    pass
        
        # Run EasyOCR
        if self.easy_ready:
            try:
                text = await self._easyocr(versions[0][0])
                if text.strip():
                    all_texts.append(text)
                    engines.append("easyocr")
            except:
                pass
        
        if not all_texts:
            return False, [], "", []
        
        combined = '\n'.join(all_texts)
        users = self._extract(combined, hint)
        
        return len(users) > 0, users, combined[:1000], engines
    
    async def _preprocess(self, image_data: bytes) -> List[Tuple[bytes, str]]:
        if not PIL_AVAILABLE:
            return [(image_data, "orig")]
        
        def _proc():
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            w, h = img.size
            
            results = []
            # Original
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            results.append((buf.getvalue(), "orig"))
            
            # Upscale if small
            if w < 500:
                scaled = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                scaled.save(buf, format='PNG')
                results.append((buf.getvalue(), "2x"))
            
            # Contrast
            contrast = ImageEnhance.Contrast(img).enhance(2.0)
            buf = io.BytesIO()
            contrast.save(buf, format='PNG')
            results.append((buf.getvalue(), "contrast"))
            
            return results
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, _proc)
    
    async def _tesseract(self, image_data: bytes) -> str:
        def _run():
            img = Image.open(io.BytesIO(image_data))
            config = '--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@'
            return pytesseract.image_to_string(img, config=config)
        
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(loop.run_in_executor(self.executor, _run), timeout=Config.OCR_TIMEOUT)
    
    async def _easyocr(self, image_data: bytes) -> str:
        if not CV2_AVAILABLE:
            return ""
        
        def _run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, paragraph=True)
            return '\n'.join([r[1] for r in results])
        
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(loop.run_in_executor(self.executor, _run), timeout=Config.OCR_TIMEOUT + 2)
    
    def _extract(self, text: str, hint: str) -> List[DetectedUser]:
        users = []
        lines = text.split('\n')
        
        # @username
        for m in re.finditer(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b', text):
            u = m.group(1)
            conf = 1.0 if hint and u.lower() == hint.lower().lstrip('@') else 0.95
            users.append(DetectedUser(u, None, conf, '@mention'))
        
        # Display @ username
        for m in re.finditer(r'([A-Za-z][A-Za-z0-9_\s]{0,20})\s*[@＠]\s*([a-z][a-z0-9_]{2,19})\b', text):
            d, u = m.groups()
            d = d.strip()
            if d and len(d) > 2:
                users.append(DetectedUser(u, d, 0.98, 'display@user'))
        
        # roblox.com/users/ID
        for m in re.finditer(r'roblox\.com/users/(\d+)', text, re.I):
            users.append(DetectedUser(f"ID:{m.group(1)}", None, 0.99, 'url'))
        
        # Context username
        for i, line in enumerate(lines):
            low = line.lower()
            has_ctx = any(w in low for w in ['roblox', 'profile', '@', 'user'])
            for m in re.finditer(r'\b([a-z][a-z0-9_]{2,19})\b', line):
                u = m.group(1)
                if u.lower() in {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 'friends', 'home'}:
                    continue
                conf = 0.65 if has_ctx else 0.45
                surr = ' '.join(lines[max(0,i-1):min(len(lines), i+2)]).lower()
                if any(x in surr for x in ['roblox', '@', 'profile']):
                    conf = min(conf + 0.15, 0.90)
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                users.append(DetectedUser(u, None, conf, 'context'))
        
        # Deduplicate
        seen = {}
        for u in sorted(users, key=lambda x: x.confidence, reverse=True):
            k = u.username.lower()
            if k not in seen:
                seen[k] = u
        
        return list(seen.values())

# ═══════════════════════════════════════════════════════════
# ROBLOX API - FIXED PARSING
# ═══════════════════════════════════════════════════════════
class RobloxAPI:
    def __init__(self, cache: SimpleCache):
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
                verified.append({'profile': cached, 'detected': user, 'score': user.confidence})
                continue
            
            profile = await self._fetch_user(user.username)
            if profile:
                await self.cache.set(f"u:{user.username.lower()}", profile, 600)
                verified.append({'profile': profile, 'detected': user, 'score': user.confidence})
        
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
    
    async def get_friends(self, user_id: int) -> List[FriendData]:
        """Get friends - FIXED to properly parse Roblox API response"""
        cached = await self.cache.get(f"f:{user_id}")
        if cached:
            return [FriendData(**f) for f in cached]
        
        try:
            async with self.session.get(
                f'https://friends.roblox.com/v1/users/{user_id}/friends',
                timeout=aiohttp.ClientTimeout(total=Config.FRIENDS_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Friends API returned {resp.status}")
                    return []
                
                data = await resp.json()
                friends_list = data.get('data', [])
                
                if not friends_list:
                    logger.info("No friends found or private list")
                    return []
                
                logger.info(f"Got {len(friends_list)} friends from API")
                
                # Parse friends - Roblox API returns 'name' as username
                friends = []
                for f in friends_list[:50]:  # Limit to 50
                    friend_id = f.get('id')
                    # IMPORTANT: Roblox uses 'name' for username, not 'username'
                    username = f.get('name') or f.get('username')
                    display = f.get('displayName') or username
                    is_online = f.get('isOnline', False)
                    
                    if friend_id and username:
                        friends.append(FriendData(
                            id=friend_id,
                            name=username,  # This is the actual username
                            display_name=display,
                            is_online=is_online
                        ))
                
                # Cache
                cache_data = [{'id': f.id, 'name': f.name, 'display_name': f.display_name, 'is_online': f.is_online} for f in friends]
                await self.cache.set(f"f:{user_id}", cache_data, 300)
                
                return friends
                
        except Exception as e:
            logger.error(f"Get friends error: {e}")
            return []
    
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
# DATABASE
# ═══════════════════════════════════════════════════════════
class Database:
    def __init__(self):
        self.pool = None
        self.whitelist: Set[str] = set()
        os.makedirs("data", exist_ok=True)
        
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

# ═══════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════
class RateLimiter:
    def __init__(self, max_req: int, window: int):
        self.max_req = max_req
        self.window = window
        self.requests: Dict[str, List[float]] = {}
        self.lock = asyncio.Lock()
    
    async def check(self, key: str) -> Tuple[bool, float]:
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
# BOT
# ═══════════════════════════════════════════════════════════
class OmegaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default(), activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan"))
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.cache = SimpleCache()
        self.limiter = RateLimiter(Config.RATE_LIMIT, 60)
        self.ocr = OCRManager()
        self.roblox = None
        self.scan_sem = asyncio.Semaphore(50)
        
    async def setup_hook(self):
        logger.info("🔧 Starting...")
        await self.cache.setup()
        await self.db.setup()
        self.roblox = RobloxAPI(self.cache)
        await self.roblox.setup()
        await self.ocr.init_easyocr()
        self._register_cmds()
        await self._sync()
        logger.info("✅ Ready!")
    
    def _register_cmds(self):
        @self.tree.command(name="scan", description="🔍 Scan image for Roblox username")
        @app_commands.describe(image="Screenshot", hint="Optional hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (owner)")
        @app_commands.describe(user="User ID")
        async def whitelist(interaction: discord.Interaction, user: str):
            await self.cmd_whitelist(interaction, user)
        
        @self.tree.command(name="search", description="🔎 Search by username")
        @app_commands.describe(username="Username")
        async def search(interaction: discord.Interaction, username: str):
            await self.cmd_search(interaction, username)
        
        @self.tree.command(name="stats", description="📊 Your stats")
        async def stats(interaction: discord.Interaction):
            await self.cmd_stats(interaction)
        
        @self.tree.command(name="ping", description="🏓 Status")
        async def ping(interaction: discord.Interaction):
            await self.cmd_ping(interaction)
    
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
        uid = str(interaction.user.id)
        
        if not self.db.is_whitelisted(uid):
            await interaction.response.send_message(embed=discord.Embed(title="⛔ Not Whitelisted", color=0xFF0000), ephemeral=True)
            return
        
        allowed, retry = await self.limiter.check(uid)
        if not allowed:
            await interaction.response.send_message(embed=discord.Embed(title="⏰ Cooldown", description=f"Wait {int(retry)}s", color=0xFFA500), ephemeral=True)
            return
        
        if image.size > Config.MAX_FILE_SIZE:
            await interaction.response.send_message(embed=discord.Embed(title="❌ File too large", color=0xFF0000), ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        async with self.scan_sem:
            try:
                # Download
                dl_start = time.time()
                async with self.roblox.session.get(image.url, timeout=aiohttp.ClientTimeout(total=Config.DOWNLOAD_TIMEOUT)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(embed=discord.Embed(title="❌ Download failed", color=0xFF0000))
                        return
                    img_data = await resp.read()
                dl_time = time.time() - dl_start
                
                # OCR
                success, users, raw, engines = await self.ocr.scan(img_data, hint)
                
                if not success:
                    embed = discord.Embed(title="❌ No Username Found", description="Could not detect username.", color=0xFF6B6B)
                    if raw:
                        lines = [l.strip() for l in raw.split('\n') if len(l.strip()) > 2][:10]
                        if lines:
                            embed.add_field(name="Detected text", value=f"```{'\n'.join(lines)[:800]}```", inline=False)
                    embed.add_field(name="Tips", value="• Use `hint` parameter\n• Ensure @username is visible\n• Try clearer image", inline=False)
                    await interaction.followup.send(embed=embed)
                    return
                
                # Verify
                verified = await self.roblox.verify_users(users)
                
                if not verified:
                    similar = await self.roblox.search_similar(users[0].username)
                    embed = discord.Embed(title="❌ User Not Found", description=f"`@{users[0].username}` not found.", color=0xFF6B6B)
                    if similar:
                        embed.add_field(name="Did you mean?", value='\n'.join(f"• {s.get('displayName', s['name'])} (@{s['name']})" for s in similar[:5]), inline=False)
                    await interaction.followup.send(embed=embed)
                    return
                
                # Success
                best = verified[0]
                prof = best['profile']
                det = best['detected']
                
                embed = self.make_profile_embed(prof, det, dl_time)
                embed.set_image(url=image.url)
                
                view = ResultView(prof, self, uid)
                await interaction.followup.send(embed=embed, view=view)
                
                # Stats
                stats = await self.db.get_stats(uid)
                stats['total'] = stats.get('total', 0) + 1
                stats['success'] = stats.get('success', 0) + 1
                if prof['name'] not in stats.get('favorites', []):
                    stats['favorites'] = [prof['name']] + stats.get('favorites', [])[:9]
                await self.db.save_stats(uid, stats)
                
            except Exception as e:
                logger.error(f"Scan error: {traceback.format_exc()}")
                await interaction.followup.send(embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000))
    
    def make_profile_embed(self, prof: Dict, det: DetectedUser, dl_time: float) -> discord.Embed:
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
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.description = f"**@{prof['name']}** | `{score:.0%} {status}`"
        
        if det.display_name and det.display_name != prof['name']:
            embed.add_field(name="📝 Detected Display", value=det.display_name, inline=True)
        
        embed.add_field(name="🆔 User ID", value=f"`{prof['id']}`", inline=True)
        embed.add_field(name="📅 Created", value=str(prof.get('created', 'Unknown'))[:10], inline=True)
        embed.add_field(name="⚡ Speed", value=f"DL: `{dl_time:.2f}s`", inline=True)
        
        if prof.get('description'):
            desc = prof['description'][:200]
            if len(prof['description']) > 200:
                desc += "..."
            embed.add_field(name="📝 About", value=desc, inline=False)
        
        if prof.get('thumbnailUrl'):
            embed.set_thumbnail(url=prof['thumbnailUrl'])
        
        embed.set_footer(text="TRUE OMEGA | Click buttons below")
        return embed
    
    async def cmd_whitelist(self, interaction: discord.Interaction, user: str):
        if str(interaction.user.id) != Config.OWNER_ID:
            await interaction.response.send_message(embed=discord.Embed(title="⛔ Owner only", color=0xFF0000), ephemeral=True)
            return
        
        target = re.sub(r'[<@!>]', '', user).strip()
        if not target.isdigit():
            await interaction.response.send_message(embed=discord.Embed(title="❌ Invalid ID", color=0xFF0000), ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        if self.db.is_whitelisted(target):
            if await self.db.remove_whitelist(target):
                await interaction.followup.send(embed=discord.Embed(title=f"✅ Removed {target}", color=0x00FF00))
            else:
                await interaction.followup.send(embed=discord.Embed(title="❌ Cannot remove owner", color=0xFF0000))
        else:
            if await self.db.add_whitelist(target):
                await interaction.followup.send(embed=discord.Embed(title=f"✅ Added {target}", color=0x00FF00))
            else:
                await interaction.followup.send(embed=discord.Embed(title="❌ Already whitelisted", color=0xFFA500))
    
    async def cmd_search(self, interaction: discord.Interaction, username: str):
        if not self.db.is_whitelisted(str(interaction.user.id)):
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        users = [DetectedUser(username, None, 1.0, "direct")]
        verified = await self.roblox.verify_users(users)
        
        if verified:
            best = verified[0]
            embed = self.make_profile_embed(best['profile'], users[0], 0.1)
            view = ResultView(best['profile'], self, str(interaction.user.id))
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=discord.Embed(title="❌ Not found", color=0xFF0000))
    
    async def cmd_stats(self, interaction: discord.Interaction):
        stats = await self.db.get_stats(str(interaction.user.id))
        total = stats.get('total', 0)
        success = stats.get('success', 0)
        rate = (success / total * 100) if total > 0 else 0
        
        embed = discord.Embed(title="📊 Your Stats", color=0x00D4AA)
        embed.add_field(name="Total Scans", value=str(total), inline=True)
        embed.add_field(name="Successful", value=str(success), inline=True)
        embed.add_field(name="Success Rate", value=f"{rate:.1f}%", inline=True)
        
        favs = stats.get('favorites', [])
        if favs:
            embed.add_field(name="⭐ Favorites", value='\n'.join(f"• @{u}" for u in favs[:5]), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"{round(self.latency * 1000)}ms", inline=True)
        embed.add_field(name="Whitelisted", value=str(len(self.db.whitelist)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# FRIENDS VIEW - FIXED AND WORKING
# ═══════════════════════════════════════════════════════════
class FriendsView(discord.ui.View):
    def __init__(self, friends: List[FriendData], profile_name: str, page: int = 0):
        super().__init__(timeout=180)
        self.friends = friends
        self.profile_name = profile_name
        self.page = page
        self.per_page = 12
        self._update_buttons()
    
    def _update_buttons(self):
        self.clear_items()
        total_pages = max(1, (len(self.friends) + self.per_page - 1) // self.per_page)
        
        if self.page > 0:
            btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary)
            btn.callback = self._prev
            self.add_item(btn)
        
        self.add_item(discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.gray, disabled=True))
        
        if self.page < total_pages - 1:
            btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            btn.callback = self._next
            self.add_item(btn)
    
    async def _prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)
    
    async def _next(self, interaction: discord.Interaction):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)
    
    def _make_embed(self) -> discord.Embed:
        start = self.page * self.per_page
        end = min(start + self.per_page, len(self.friends))
        page_friends = self.friends[start:end]
        
        embed = discord.Embed(
            title=f"👥 {self.profile_name}'s Friends",
            description=f"**{len(self.friends)}** total friends | Showing **{start + 1}-{end}**",
            color=0x00D4AA
        )
        
        if not page_friends:
            embed.add_field(name="No friends", value="This user has no friends.", inline=False)
            return embed
        
        # Build friend list - each friend on its own line
        lines = []
        for f in page_friends:
            status = "🟢" if f.is_online else "⚫"
            # Show display name if different from username
            if f.display_name and f.display_name != f.name:
                line = f"{status} **{f.display_name}** `@{f.name}`"
            else:
                line = f"{status} **@{f.name}**"
            lines.append(line)
        
        # Split into fields of 6 friends each (Discord embed limit)
        chunk_size = 6
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            field_name = f"Friends {start + i + 1}-{min(start + i + chunk_size, end)}"
            embed.add_field(name=field_name, value='\n'.join(chunk), inline=False)
        
        embed.set_footer(text="🟢 = Online | Click Prev/Next to navigate")
        return embed

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
            
            view = FriendsView(friends, self.profile.get('displayName', self.profile['name']))
            embed = view._make_embed()
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Friends error: {traceback.format_exc()}")
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description=f"Could not load friends: {str(e)[:100]}", color=0xFF0000),
                ephemeral=True
            )
    
    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="⭐")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        stats = await self.bot.db.get_stats(self.user_id)
        
        if self.profile['name'] in stats.get('favorites', []):
            await interaction.response.send_message(embed=discord.Embed(title="⭐ Already saved", color=0xFFA500), ephemeral=True)
            return
        
        stats['favorites'] = [self.profile['name']] + stats.get('favorites', [])[:9]
        await self.bot.db.save_stats(self.user_id, stats)
        await interaction.response.send_message(embed=discord.Embed(title=f"⭐ Saved @{self.profile['name']}!", color=0x00FF00), ephemeral=True)

# ═══════════════════════════════════════════════════════════
# HEALTH SERVER
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text='OK'))
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
