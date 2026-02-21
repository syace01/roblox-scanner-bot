""" 🎯 TRUE OMEGA - ULTIMATE ROBLOX SCANNER BOT """
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
import aiohttp
import difflib
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
TOKEN = os.getenv('DISCORD_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://ptb.discord.com/api/webhooks/1474073290183282952/JTVRmKnXqqka8IqE0ZpWAtTvsMLd2tfpxbU93KGHWu-gDzQQwktjBf6QTmhPvy-zFZ1_')

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN not set!")
    sys.exit(1)

print("=" * 60)
print("🎯 TRUE OMEGA - ULTIMATE ROBLOX SCANNER")
print("=" * 60)

# ═══════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════
try:
    import discord
    from discord import app_commands
    from discord.ui import Button, View
    print("✅ Discord.py imported")
except Exception as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
    print("✅ yt-dlp available")
except:
    YTDLP_AVAILABLE = False
    print("⚠️ yt-dlp not available")

try:
    import numpy as np
    NP_AVAILABLE = True
except:
    NP_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except:
    CV2_AVAILABLE = False

try:
    import easyocr
    EASYOCR_AVAILABLE = True
    print("✅ EasyOCR available")
except:
    EASYOCR_AVAILABLE = False
    print("⚠️ EasyOCR not available")

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    PIL_AVAILABLE = True
    print("✅ Pillow available")
except:
    PIL_AVAILABLE = False

# Thread pool for CPU tasks
ocr_executor = ThreadPoolExecutor(max_workers=4)

# ═══════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════
@dataclass
class ScanResult:
    success: bool
    profile: Optional[Dict]
    confidence: float
    reasons: List[str]
    alternatives: List[Dict]
    scan_time: float
    ocr_engines_used: int
    cached: bool = False

@dataclass
class UserStats:
    user_id: str
    total_scans: int = 0
    successful_scans: int = 0
    last_scan: Optional[str] = None
    favorite_users: List[str] = None
    
    def __post_init__(self):
        if self.favorite_users is None:
            self.favorite_users = []

# ═══════════════════════════════════════════════════════════
# WEBHOOK LOGGER
# ═══════════════════════════════════════════════════════════
class WebhookLogger:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.queue: List[Dict] = []
        self._flush_task: Optional[asyncio.Task] = None
    
    async def setup(self):
        self.session = aiohttp.ClientSession()
        self._flush_task = asyncio.create_task(self._flush_loop())
    
    async def _flush_loop(self):
        while True:
            await asyncio.sleep(5)
            if self.queue and self.session:
                await self._send_batch()
    
    async def _send_batch(self):
        if not self.queue:
            return
        batch = self.queue[:10]
        self.queue = self.queue[10:]
        
        for item in batch:
            try:
                async with self.session.post(self.webhook_url, json=item) as resp:
                    if resp.status not in [200, 204]:
                        print(f"Webhook failed: {resp.status}")
            except Exception as e:
                print(f"Webhook error: {e}")
    
    async def log(self, content: str = None, embed: discord.Embed = None, username: str = "TRUE OMEGA"):
        payload = {
            "username": username,
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"
        }
        if content:
            payload["content"] = content
        if embed:
            payload["embeds"] = [embed.to_dict()]
        
        self.queue.append(payload)
        if len(self.queue) >= 5:
            await self._send_batch()
    
    async def log_scan(self, user: discord.User, profile: Dict, confidence: float, guild_name: str):
        embed = discord.Embed(
            title=f"🔍 Scan: @{profile['name']}",
            description=f"**User:** {user.name} (`{user.id}`)\n**Location:** {guild_name}\n**Confidence:** `{confidence:.0%}`",
            color=0x00D4AA if confidence > 0.8 else 0xFFA500,
            timestamp=datetime.now()
        )
        embed.add_field(name="🆔 Roblox ID", value=f"`{profile['id']}`", inline=True)
        embed.add_field(name="📛 Display", value=profile.get('displayName', 'N/A'), inline=True)
        await self.log(embed=embed)

# ═══════════════════════════════════════════════════════════
# PROFILE CACHE
# ═══════════════════════════════════════════════════════════
class ProfileCache:
    def __init__(self, ttl: int = 300):
        self.cache: Dict[str, Tuple[Dict, float]] = {}
        self.ttl = ttl
    
    def get(self, key: str) -> Optional[Dict]:
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return data
            del self.cache[key]
        return None
    
    def set(self, key: str, value: Dict):
        self.cache[key] = (value, time.time())
    
    def clear_old(self):
        now = time.time()
        to_delete = [k for k, (_, ts) in self.cache.items() if now - ts > self.ttl]
        for k in to_delete:
            del self.cache[k]

# ═══════════════════════════════════════════════════════════
# OCR SCANNER
# ═══════════════════════════════════════════════════════════
class UltraOCR:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.easyocr_reader = None
        self.cache = ProfileCache(ttl=600)
        
        if EASYOCR_AVAILABLE:
            try:
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                print("✅ EasyOCR initialized")
            except Exception as e:
                print(f"⚠️ EasyOCR init failed: {e}")
    
    async def setup(self):
        self.session = aiohttp.ClientSession()
    
    def preprocess(self, image_data: bytes, method: str) -> bytes:
        if not PIL_AVAILABLE:
            return image_data
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            w, h = img.size
            if w < 400 or h < 200:
                img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
            elif w < 800 or h < 400:
                img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
            
            if method == "contrast":
                img = ImageEnhance.Contrast(img).enhance(2.5)
                img = ImageEnhance.Sharpness(img).enhance(2.0)
            elif method == "bw":
                img = ImageOps.grayscale(img)
                img = img.point(lambda x: 0 if x < 120 else 255, '1').convert('RGB')
            elif method == "sharp":
                img = img.filter(ImageFilter.SHARPEN)
                img = ImageEnhance.Contrast(img).enhance(2.0)
            elif method == "invert":
                img = ImageOps.invert(img)
                img = ImageEnhance.Contrast(img).enhance(2.0)
            
            buf = io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            return buf.getvalue()
        except Exception as e:
            print(f"Preprocess error: {e}")
            return image_data
    
    async def scan(self, image_data: bytes, hint: Optional[str] = None) -> ScanResult:
        start = time.time()
        
        # Parallel preprocessing
        preprocessed = await asyncio.gather(*[
            asyncio.get_event_loop().run_in_executor(None, self.preprocess, image_data, m)
            for m in ["contrast", "bw", "sharp"]
        ])
        preprocessed.insert(0, image_data)  # Raw
        
        # Parallel OCR
        ocr_tasks = []
        if OCR_SPACE_KEY:
            for i, img in enumerate(preprocessed[:3]):
                ocr_tasks.append(self._ocr_space(img, f"space_{i}"))
        if self.easyocr_reader:
            ocr_tasks.append(self._easyocr(preprocessed[0], "easyocr"))
        
        ocr_results = await asyncio.gather(*ocr_tasks, return_exceptions=True)
        texts = [r[1] for r in ocr_results if isinstance(r, tuple) and r[1]]
        
        if not texts:
            return ScanResult(False, None, 0, [], [], time.time()-start, 0)
        
        combined = self._merge_texts(texts)
        users = self._extract_users(combined, hint)
        
        if not users:
            return ScanResult(False, None, 0, [], [], time.time()-start, len(texts))
        
        verified = await self._verify_users(users, combined, hint)
        elapsed = time.time() - start
        
        if verified:
            best = verified[0]
            return ScanResult(
                True, best['profile'], best['score'], best['reasons'],
                verified[1:4], elapsed, len(texts)
            )
        
        return ScanResult(False, None, 0, [], [], elapsed, len(texts))
    
    async def _ocr_space(self, image_data: bytes, name: str) -> Tuple[str, str]:
        try:
            b64 = base64.b64encode(image_data).decode()
            data = {
                'apikey': OCR_SPACE_KEY,
                'base64Image': f'data:image/png;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true',
            }
            async with self.session.post('https://api.ocr.space/parse/image', data=data, timeout=15) as resp:
                result = await resp.json()
            text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
            return (name, text)
        except:
            return (name, "")
    
    async def _easyocr(self, image_data: bytes, name: str) -> Tuple[str, str]:
        if not self.easyocr_reader or not NP_AVAILABLE:
            return (name, "")
        try:
            import cv2
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(ocr_executor, self.easyocr_reader.readtext, img),
                timeout=12
            )
            return (name, '\n'.join([r[1] for r in result]))
        except:
            return (name, "")
    
    def _merge_texts(self, texts: List[str]) -> str:
        seen = set()
        lines = []
        for text in texts:
            for line in text.split('\n'):
                clean = line.strip()
                if len(clean) > 1:
                    norm = re.sub(r'[^\w@]', '', clean).lower()
                    if norm and norm not in seen:
                        seen.add(norm)
                        lines.append(clean)
        return '\n'.join(lines)
    
    def _extract_users(self, text: str, hint: Optional[str]) -> List[Dict]:
        users = []
        lines = text.split('\n')
        text_lower = text.lower()
        
        EXCLUDE = {'roblox', 'profile', 'home', 'games', 'friends', 'inventory', 
                   'avatar', 'shop', 'create', 'about', 'chat', 'trade', 'premium',
                   'settings', 'search', 'menu', 'play', 'join', 'exit', 'back',
                   'online', 'offline', 'studio', 'catalog', 'develop', 'groups',
                   'messages', 'notifications', 'the', 'and', 'for', 'you', 'are',
                   'connection', 'match', 'confidence', 'verification', 'status',
                   'created', 'user', 'id', 'about', 'other', 'matches', 'banned',
                   'active', 'today', 'font', 'proof', 'scanning', 'omega', 'true',
                   'display', 'username', 'scan', 'click', 'add', 'remove'}
        
        # @username patterns
        for i, line in enumerate(lines):
            for match in re.findall(r'[@＠﹫]([A-Za-z0-9_]{3,20})\b', line):
                if match.lower() in EXCLUDE:
                    continue
                conf = 0.85
                display = None
                
                parts = re.split(r'[@＠﹫]', line)
                if len(parts) > 1:
                    before = re.sub(r'[^\w\s]', '', parts[0]).strip()
                    if before and before.lower() not in EXCLUDE:
                        display, conf = before, 0.95
                
                if not display and i > 0:
                    prev = re.sub(r'[^\w\s]', '', lines[i-1]).strip()
                    if prev and prev.lower() not in EXCLUDE and len(prev) < 25:
                        display, conf = prev, 0.9
                
                users.append({'username': match, 'display': display, 'conf': conf, 'source': '@'})
        
        # URLs
        for uid in re.findall(r'roblox\.com/users/(\d+)', text, re.I):
            users.insert(0, {'username': f'ID:{uid}', 'id': uid, 'conf': 0.98, 'source': 'url'})
        
        # Display @ User pairs
        for line in lines:
            m = re.search(r'^([A-Z][a-zA-Z\s]{1,20})\s*[@\s]\s*([a-z][a-z0-9_]{2,19})\b', line)
            if m:
                d, u = m.groups()
                if d.lower() not in EXCLUDE and u.lower() not in EXCLUDE:
                    existing = next((x for x in users if x['username'].lower() == u.lower()), None)
                    if existing:
                        existing.update({'display': d, 'conf': 0.98, 'source': 'pair'})
                    else:
                        users.append({'username': u, 'display': d, 'conf': 0.98, 'source': 'pair'})
        
        # Pattern matches
        for name in set(re.findall(r'\b([a-z][a-z0-9_]{2,19})\b', text_lower)):
            if name not in EXCLUDE and not any(x['username'].lower() == name for x in users):
                near_at = f'@{name}' in text_lower
                users.append({'username': name, 'display': None, 'conf': 0.6 if near_at else 0.45, 'source': 'pat'})
        
        # Hint boost
        if hint:
            h = hint.strip().lower().replace('@', '')
            if re.match(r'^[a-z0-9_]{3,20}$', h) and h not in EXCLUDE:
                existing = next((x for x in users if x['username'].lower() == h), None)
                if existing:
                    existing.update({'conf': 1.0, 'source': 'hint'})
                else:
                    users.insert(0, {'username': h, 'display': None, 'conf': 1.0, 'source': 'hint'})
        
        seen = set()
        unique = []
        for u in sorted(users, key=lambda x: x['conf'], reverse=True):
            key = u['username'].lower()
            if key not in seen:
                seen.add(key)
                unique.append(u)
        return unique
    
    async def _verify_users(self, potentials: List[Dict], full_text: str, hint: Optional[str]) -> List[Dict]:
        verified = []
        full_lower = full_text.lower()
        
        for p in potentials[:6]:
            username = p['username']
            if username.startswith('ID:'):
                continue
            
            cache_key = f"user:{username.lower()}"
            cached = self.cache.get(cache_key)
            
            if cached:
                score, reasons = self._calc_score(p, cached, full_lower, hint)
                verified.append({'profile': cached, 'score': score, 'reasons': reasons, 'cached': True})
                continue
            
            try:
                async with self.session.post(
                    'https://users.roblox.com/v1/usernames/users',
                    json={"usernames": [username], "excludeBannedUsers": False},
                    timeout=8
                ) as resp:
                    if resp.status != 200:
                        continue
                    r = await resp.json()
                    
                    if not r.get('data'):
                        similar = await self._fuzzy_search(username)
                        if similar:
                            r = {"data": [similar]}
                        else:
                            continue
                    
                    info = r['data'][0]
                    
                    async with self.session.get(f'https://users.roblox.com/v1/users/{info["id"]}', timeout=8) as resp:
                        if resp.status != 200:
                            continue
                        profile = await resp.json()
                
                self.cache.set(cache_key, profile)
                score, reasons = self._calc_score(p, profile, full_lower, hint)
                verified.append({'profile': profile, 'score': score, 'reasons': reasons})
                
                if score >= 0.95:
                    break
                    
            except:
                continue
        
        return sorted(verified, key=lambda x: x['score'], reverse=True)
    
    def _calc_score(self, ocr: Dict, profile: Dict, full_lower: str, hint: Optional[str]) -> Tuple[float, List[str]]:
        score = ocr['conf']
        reasons = [f"{ocr['source']}({ocr['conf']:.0%})"]
        
        prof_disp = profile.get('displayName', '')
        ocr_disp = ocr.get('display')
        
        if ocr_disp and prof_disp:
            sim = difflib.SequenceMatcher(None, ocr_disp.lower(), prof_disp.lower()).ratio()
            if sim > 0.8:
                score = min(score + 0.15, 1.0)
                reasons.append(f"disp:{sim:.0%}")
        
        if prof_disp and prof_disp.lower() in full_lower:
            score = min(score + 0.1, 1.0)
            reasons.append("disp✓")
        
        if hint and profile['name'].lower() == hint.lower().replace('@', ''):
            score = 1.0
            reasons.append("🎯HINT")
        
        return min(score, 1.0), reasons
    
    async def _fuzzy_search(self, username: str) -> Optional[Dict]:
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=3',
                timeout=8
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for u in data.get('data', []):
                        sim = difflib.SequenceMatcher(None, username.lower(), u['name'].lower()).ratio()
                        if sim > 0.75:
                            return u
        except:
            pass
        return None

# ═══════════════════════════════════════════════════════════
# USER STATS MANAGER
# ═══════════════════════════════════════════════════════════
class StatsManager:
    def __init__(self, filename: str = "user_stats.json"):
        self.filename = filename
        self.stats: Dict[str, UserStats] = {}
        self.load()
    
    def load(self):
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    for uid, s in data.items():
                        self.stats[uid] = UserStats(**s)
        except:
            pass
    
    def save(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump({uid: asdict(s) for uid, s in self.stats.items()}, f)
        except:
            pass
    
    def get(self, user_id: str) -> UserStats:
        if user_id not in self.stats:
            self.stats[user_id] = UserStats(user_id=user_id)
        return self.stats[user_id]
    
    def record_scan(self, user_id: str, success: bool, roblox_name: str):
        s = self.get(user_id)
        s.total_scans += 1
        if success:
            s.successful_scans += 1
            if roblox_name not in s.favorite_users:
                s.favorite_users.insert(0, roblox_name)
                s.favorite_users = s.favorite_users[:10]
        s.last_scan = datetime.now().isoformat()
        self.save()

# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    def __init__(self):
        self.path = tempfile.mkdtemp()
    
    async def download(self, url: str, user_id: str) -> Dict:
        if not YTDLP_AVAILABLE:
            return {"success": False, "error": "yt-dlp not installed"}
        
        dl_id = f"{user_id}_{int(time.time())}"
        output = os.path.join(self.path, f"{dl_id}.%(ext)s")
        
        try:
            loop = asyncio.get_event_loop()
            def dl():
                opts = {
                    'format': 'best[filesize<25M]/bestvideo[filesize<25M]+bestaudio/best',
                    'outtmpl': output,
                    'quiet': True,
                    'max_filesize': 25 * 1024 * 1024,
                    'merge_output_format': 'mp4',
                    'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    files = [f for f in os.listdir(self.path) if f.startswith(dl_id)]
                    if not files:
                        return {"success": False, "error": "No file"}
                    fpath = os.path.join(self.path, files[0])
                    return {
                        "success": True,
                        "file_path": fpath,
                        "title": info.get('title', 'video'),
                        "size": os.path.getsize(fpath)
                    }
            return await asyncio.wait_for(loop.run_in_executor(None, dl), timeout=120)
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}
    
    def cleanup(self, path: str):
        try:
            if os.path.exists(path):
                os.remove(path)
        except:
            pass

# ═══════════════════════════════════════════════════════════
# DISCORD BOT
# ═══════════════════════════════════════════════════════════
class TrueOmegaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.whitelist = {str(OWNER_ID)}
        self.whitelist_file = 'whitelist.json'
        self.webhook = WebhookLogger(WEBHOOK_URL)
        self.scanner = UltraOCR()
        self.downloader = VideoDownloader()
        self.stats = StatsManager()
        self.session: Optional[aiohttp.ClientSession] = None
    
    def save_whitelist(self):
        try:
            with open(self.whitelist_file, 'w') as f:
                json.dump({"users": list(self.whitelist)}, f)
        except:
            pass
    
    async def setup_hook(self):
        print("🔧 Setting up...")
        await self.webhook.setup()
        await self.scanner.setup()
        self.session = self.scanner.session
        
        # Load whitelist
        try:
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, 'r') as f:
                    self.whitelist.update(str(u) for u in json.load(f).get('users', []))
                print(f"✅ Loaded {len(self.whitelist)} whitelisted")
        except:
            pass
        
        # Clear old commands and sync
        print("🔄 Syncing commands...")
        self.tree.clear_commands(guild=None)
        
        # ═══════════════════════════════════════════════════
        # COMMANDS
        # ═══════════════════════════════════════════════════
        
        @self.tree.command(name="scan", description="🔍 Scan Roblox username from image")
        @app_commands.describe(
            image="Screenshot to scan",
            hint="Optional username hint (improves accuracy)"
        )
        async def scan_cmd(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.cmd_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download video to MP4")
        @app_commands.describe(url="Video URL (YouTube, TikTok, etc.)")
        async def download_cmd(interaction: discord.Interaction, url: str):
            await self.cmd_download(interaction, url)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (Owner only)")
        @app_commands.describe(user="User to add/remove")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self.cmd_whitelist(interaction, user)
        
        @self.tree.command(name="stats", description="📊 View your scan statistics")
        async def stats_cmd(interaction: discord.Interaction):
            await self.cmd_stats(interaction)
        
        @self.tree.command(name="search", description="🔎 Search Roblox user by name")
        @app_commands.describe(username="Roblox username to search")
        async def search_cmd(interaction: discord.Interaction, username: str):
            await self.cmd_search(interaction, username)
        
        @self.tree.command(name="help", description="❓ Show bot help")
        async def help_cmd(interaction: discord.Interaction):
            await self.cmd_help(interaction)
        
        # Sync
        for attempt in range(5):
            try:
                synced = await self.tree.sync()
                print(f"✅ Synced {len(synced)} commands")
                break
            except discord.HTTPException as e:
                if e.status == 429:
                    await asyncio.sleep(getattr(e, 'retry_after', 5))
                else:
                    await asyncio.sleep(2)
        
        print("✅ Bot ready!")
    
    # ═══════════════════════════════════════════════════════
    # COMMAND HANDLERS
    # ═══════════════════════════════════════════════════════
    
    async def cmd_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: Optional[str]):
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist and user_id != str(OWNER_ID):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⛔ Access Denied",
                    description="You're not whitelisted. Contact the bot owner.",
                    color=0xFF0000
                ),
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        # Check file size
        if image.size and image.size > 50 * 1024 * 1024:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Error", description="Image too large (max 50MB)", color=0xFF0000)
            )
            return
        
        # Progress embed
        progress = discord.Embed(
            title="🔍 Scanning Image...",
            description="```\n[░░░░░░░░░░] 0%\n```\nDownloading image...",
            color=0xFFA500
        )
        await interaction.followup.send(embed=progress)
        
        try:
            # Download
            async with self.session.get(image.url, timeout=15) as resp:
                if resp.status != 200:
                    raise Exception(f"Download failed: {resp.status}")
                img_data = await resp.read()
            
            # Update progress
            progress.description = "```\n[██░░░░░░░░] 20%\n```\nRunning OCR analysis..."
            await interaction.edit_original_response(embed=progress)
            
            # Scan
            result = await self.scanner.scan(img_data, hint)
            
            # Update stats
            self.stats.record_scan(user_id, result.success, result.profile['name'] if result.profile else "")
            
            if not result.success:
                detected = result.ocr_engines_used
                preview = result.__dict__.get('combined_text', 'No text detected')[:300]
                
                fail_embed = discord.Embed(
                    title="❌ No User Found",
                    description=f"Couldn't verify any Roblox user after scanning with {detected} OCR engines.",
                    color=0xFF0000
                )
                fail_embed.add_field(name="💡 Tips", value="• Try a clearer screenshot\n• Use the `hint` option\n• Make sure @username is visible", inline=False)
                if preview and preview != "No text detected":
                    fail_embed.add_field(name="📝 Detected Text", value=f"```{preview}...```", inline=False)
                fail_embed.set_footer(text=f"⚡ {result.scan_time:.1f}s | TRUE OMEGA")
                await interaction.edit_original_response(embed=fail_embed)
                return
            
            # Success!
            profile = result.profile
            score = result.confidence
            
            # Color based on confidence
            if profile.get('isBanned'):
                color, status_emoji = 0x8B0000, "🔴 BANNED"
            elif score >= 0.9:
                color, status_emoji = 0x00FF00, "✅ Verified"
            elif score >= 0.7:
                color, status_emoji = 0xFFA500, "⚠️ Likely"
            else:
                color, status_emoji = 0xFFFF00, "❓ Uncertain"
            
            embed = discord.Embed(
                title=f"{profile.get('displayName', profile['name'])}",
                url=f"https://roblox.com/users/{profile['id']}/profile",
                color=color,
                timestamp=datetime.now()
            )
            embed.description = f"**@{profile['name']}**\n`Match Confidence: {score:.0%}`"
            
            # Verification details
            embed.add_field(
                name="✅ Verification",
                value="\n".join(f"• {r}" for r in result.reasons[:4]),
                inline=False
            )
            
            # Stats row
            created = str(profile.get('created', 'Unknown'))[:10]
            embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
            embed.add_field(name="📅 Created", value=created, inline=True)
            embed.add_field(name="⚡ Status", value=status_emoji, inline=True)
            
            # Description
            if profile.get('description'):
                desc = profile['description'][:200]
                if len(profile['description']) > 200:
                    desc += "..."
                embed.add_field(name="📝 About", value=desc, inline=False)
            
            # Alternatives
            if result.alternatives:
                alts = []
                for alt in result.alternatives[:2]:
                    p = alt['profile']
                    alts.append(f"[@{p['name']}](https://roblox.com/users/{p['id']}/profile) ({alt['score']:.0%})")
                if alts:
                    embed.add_field(name="🔍 Other Matches", value=" | ".join(alts), inline=False)
            
            embed.set_image(url=image.url)
            cached = "📦" if result.cached else ""
            embed.set_footer(text=f"{cached}⚡ {result.scan_time:.1f}s | {result.ocr_engines_used} engines | TRUE OMEGA")
            
            await interaction.edit_original_response(embed=embed)
            
            # Log to webhook
            guild_name = interaction.guild.name if interaction.guild else "DM"
            await self.webhook.log_scan(interaction.user, profile, score, guild_name)
            
        except Exception as e:
            print(f"Scan error: {e}")
            traceback.print_exc()
            error_embed = discord.Embed(
                title="❌ Scan Failed",
                description=f"Error: `{str(e)[:150]}`\n\nPlease try again.",
                color=0xFF0000
            )
            await interaction.edit_original_response(embed=error_embed)
    
    async def cmd_download(self, interaction: discord.Interaction, url: str):
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist and user_id != str(OWNER_ID):
            await interaction.response.send_message("⛔ Not whitelisted!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            await interaction.followup.send(embed=discord.Embed(title="❌ Invalid URL", color=0xFF0000))
            return
        
        progress = discord.Embed(title="📥 Downloading...", description="Please wait...", color=0xFFA500)
        await interaction.followup.send(embed=progress)
        
        result = await self.downloader.download(url, user_id)
        
        if not result['success']:
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Download Failed",
                description=f"```{result['error'][:200]}```",
                color=0xFF0000
            ))
            return
        
        size_mb = result['size'] / (1024 * 1024)
        if result['size'] > 25 * 1024 * 1024:
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ File Too Large",
                description=f"{size_mb:.1f}MB exceeds Discord's 25MB limit",
                color=0xFF0000
            ))
            self.downloader.cleanup(result['file_path'])
            return
        
        safe = re.sub(r'[^\w\-_.]', '_', result['title'][:50])
        file = discord.File(result['file_path'], filename=f"{safe}.mp4")
        
        embed = discord.Embed(title="✅ Download Complete", color=0x00FF00)
        embed.add_field(name="📹 Title", value=result['title'][:80], inline=False)
        embed.add_field(name="📦 Size", value=f"{size_mb:.1f} MB", inline=True)
        
        await interaction.edit_original_response(embed=embed, attachments=[file])
        self.downloader.cleanup(result['file_path'])
    
    async def cmd_whitelist(self, interaction: discord.Interaction, user: str):
        if str(interaction.user.id) != str(OWNER_ID):
            await interaction.response.send_message("⛔ Owner only!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        target = re.sub(r'[<@!>]', '', user).strip()
        if not target.isdigit():
            await interaction.followup.send("❌ Invalid user ID", ephemeral=True)
            return
        
        try:
            u = await self.fetch_user(int(target))
            name = f"@{u.name}" if u else target
        except:
            name = target
        
        if target in self.whitelist:
            if target == str(OWNER_ID):
                await interaction.followup.send("⛔ Can't remove owner!", ephemeral=True)
                return
            self.whitelist.remove(target)
            self.save_whitelist()
            await self.webhook.log(content=f"❌ Removed **{name}** from whitelist")
            await interaction.followup.send(f"❌ Removed {name}", ephemeral=True)
        else:
            self.whitelist.add(target)
            self.save_whitelist()
            await self.webhook.log(content=f"✅ Added **{name}** to whitelist")
            await interaction.followup.send(f"✅ Added {name}", ephemeral=True)
    
    async def cmd_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        s = self.stats.get(str(interaction.user.id))
        
        embed = discord.Embed(
            title=f"📊 {interaction.user.name}'s Stats",
            color=0x00D4AA,
            timestamp=datetime.now()
        )
        
        success_rate = (s.successful_scans / s.total_scans * 100) if s.total_scans > 0 else 0
        
        embed.add_field(name="🔍 Total Scans", value=str(s.total_scans), inline=True)
        embed.add_field(name="✅ Successful", value=str(s.successful_scans), inline=True)
        embed.add_field(name="📈 Success Rate", value=f"{success_rate:.0f}%", inline=True)
        
        if s.last_scan:
            last = datetime.fromisoformat(s.last_scan)
            embed.add_field(name="🕐 Last Scan", value=last.strftime("%Y-%m-%d %H:%M"), inline=True)
        
        if s.favorite_users:
            embed.add_field(
                name="⭐ Recent Finds",
                value="\n".join(f"• @{u}" for u in s.favorite_users[:5]),
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def cmd_search(self, interaction: discord.Interaction, username: str):
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist and user_id != str(OWNER_ID):
            await interaction.response.send_message("⛔ Not whitelisted!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        progress = discord.Embed(title="🔎 Searching...", description=f"Looking for `@{username}`...", color=0xFFA500)
        await interaction.followup.send(embed=progress)
        
        try:
            # Try exact match
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [username.strip()], "excludeBannedUsers": False},
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        user_info = data['data'][0]
                        
                        async with self.session.get(f"https://users.roblox.com/v1/users/{user_info['id']}", timeout=10) as resp2:
                            profile = await resp2.json()
                        
                        embed = discord.Embed(
                            title=profile.get('displayName', profile['name']),
                            url=f"https://roblox.com/users/{profile['id']}/profile",
                            color=0x00FF00 if not profile.get('isBanned') else 0xFF0000,
                            timestamp=datetime.now()
                        )
                        embed.description = f"**@{profile['name']}**"
                        embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
                        embed.add_field(name="📅 Created", value=str(profile.get('created', 'N/A'))[:10], inline=True)
                        embed.add_field(name="⚡ Status", value="🔴 BANNED" if profile.get('isBanned') else "✅ Active", inline=True)
                        
                        if profile.get('description'):
                            embed.add_field(name="📝 About", value=profile['description'][:200], inline=False)
                        
                        await interaction.edit_original_response(embed=embed)
                        return
            
            # Try search
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5',
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        results = data['data'][:5]
                        embed = discord.Embed(
                            title=f"🔎 Search Results for '{username}'",
                            description="Found these users:",
                            color=0x00D4AA
                        )
                        for r in results:
                            embed.add_field(
                                name=f"{r.get('displayName', r['name'])} (@{r['name']})",
                                value=f"[View Profile](https://roblox.com/users/{r['id']}/profile)",
                                inline=False
                            )
                        await interaction.edit_original_response(embed=embed)
                        return
            
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Not Found",
                description=f"No user found matching `@{username}`",
                color=0xFF0000
            ))
            
        except Exception as e:
            await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Error",
                description=str(e)[:200],
                color=0xFF0000
            ))
    
    async def cmd_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎯 TRUE OMEGA - Help",
            description="Ultimate Roblox Scanner Bot",
            color=0x00D4AA
        )
        
        embed.add_field(
            name="🔍 /scan",
            value="Scan a screenshot to find Roblox users\n`image`: Screenshot\n`hint`: Optional username hint",
            inline=False
        )
        
        embed.add_field(
            name="🔎 /search",
            value="Search for a Roblox user by name\n`username`: Roblox username",
            inline=False
        )
        
        embed.add_field(
            name="📥 /download",
            value="Download videos to MP4\n`url`: Video URL",
            inline=False
        )
        
        embed.add_field(
            name="📊 /stats",
            value="View your scan statistics",
            inline=False
        )
        
        embed.add_field(
            name="💡 Tips",
            value="• Use the `hint` option for better accuracy\n• Clear screenshots work best\n• Make sure @username is visible",
            inline=False
        )
        
        embed.set_footer(text="TRUE OMEGA | Fast & Reliable Roblox Scanner")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def on_ready(self):
        print(f"\n{'='*50}")
        print(f"✅ BOT ONLINE: {self.user}")
        print(f"   Servers: {len(self.guilds)}")
        print(f"   Whitelisted: {len(self.whitelist)} users")
        print(f"{'='*50}\n")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    while True:
        try:
            bot = TrueOmegaBot()
            bot.run(TOKEN, log_handler=None)
            print("⚠️ Bot stopped, restarting in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"Fatal error: {e}")
            traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    main()
