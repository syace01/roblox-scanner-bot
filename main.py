"""
🚀 TRUE OMEGA v8.0 - MILITARY GRADE SCANNER
Pure speed. Maximum accuracy. Zero bloat.
"""

import os
import sys
import asyncio
import json
import time
import re
import io
import hashlib
import warnings
from datetime import datetime
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from collections import defaultdict
import logging

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("omega")

# Auto-install
def install():
    missing = []
    try: import discord
    except: missing.append('discord.py')
    try: import aiohttp
    except: missing.append('aiohttp')
    try: from PIL import Image
    except: missing.append('Pillow')
    try: import numpy as np
    except: missing.append('numpy')
    try: import cv2
    except: missing.append('opencv-python-headless')
    try: import pytesseract
    except: missing.append('pytesseract')
    try: import easyocr
    except: missing.append('easyocr')
    
    if missing:
        print(f"Installing: {missing}")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)
        os.execl(sys.executable, sys.executable, *sys.argv)

install()

import aiohttp
from aiohttp import TCPConnector
import discord
from discord import app_commands
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import cv2

# Config
class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    OWNER_ID = str(os.getenv('OWNER_ID', '1382137288502542339'))
    OCR_TIMEOUT = 3
    API_TIMEOUT = 2
    MAX_FILE_SIZE = 100 * 1024 * 1024
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,19}$')
    FALSE_POSITIVES = {'roblox', 'profile', 'username', 'display', 'user', 'avatar', 
                      'friends', 'home', 'settings', 'catalog', 'inventory', 'trades',
                      'groups', 'messages', 'premium', 'create', 'money', 'robux',
                      'search', 'menu', 'notifications', 'chat', 'character', 'animations',
                      'clothing', 'accessories', 'game', 'play', 'favorite', 'joined',
                      'place', 'visits', 'playing', 'favorites', 'updated', 'created',
                      'badge', 'badges', 'pass', 'gamepass', 'shirt', 'pants', 'tshirt'}

@dataclass
class DetectedUser:
    username: str
    confidence: float
    source: str
    engine: str

@dataclass  
class VideoInfo:
    url: str
    title: str
    duration: str
    uploader: str
    thumbnail: Optional[str]
    filesize: Optional[int]

# ═══════════════════════════════════════════════════════════
# MILITARY GRADE OCR - PARALLEL MULTI-ENGINE
# ═══════════════════════════════════════════════════════════
class MilitaryOCR:
    def __init__(self):
        self.easyocr_reader = None
        self.executor = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=8)
        self.patterns = {
            'at': re.compile(r'[@＠]([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'url': re.compile(r'roblox\.com/users/(\d+)', re.I),
            'user': re.compile(r'\b([a-zA-Z][a-zA-Z0-9_]{2,19})\b'),
            'label': re.compile(r'(?:username|user|name)\s*[:=]\s*[@＠]?([a-zA-Z][\w]{2,19})', re.I)
        }
        
    async def init(self):
        try:
            import easyocr
            loop = asyncio.get_event_loop()
            self.easyocr_reader = await loop.run_in_executor(
                self.executor,
                lambda: easyocr.Reader(['en'], gpu=False, verbose=False)
            )
            logger.info("✅ EasyOCR ready")
        except Exception as e:
            logger.warning(f"EasyOCR: {e}")

    async def scan(self, image_data: bytes, hint: str = None) -> Tuple[bool, List[DetectedUser], Dict]:
        start = time.perf_counter()
        
        # Parallel preprocessing
        variants = await self._preprocess(image_data)
        
        # Parallel OCR - all engines at once
        tasks = [
            self._tesseract(variants[0][0]),
            self._tesseract(variants[1][0]) if len(variants) > 1 else asyncio.sleep(0),
            self._easyocr(variants[0][0]) if self.easyocr_reader else asyncio.sleep(0),
        ]
        
        results = await asyncio.gather(*tasks)
        texts = [r for r in results if r]
        
        if not texts:
            return False, [], {"time": time.perf_counter() - start}
        
        # Fuse results
        fused = '\n'.join(texts)
        
        # Extract users
        users = self._extract(fused, hint, texts)
        
        if not users:
            return False, [], {"time": time.perf_counter() - start}
        
        # Vote
        voted = self._vote(users, hint)
        
        return len(voted) > 0, voted, {
            "time": time.perf_counter() - start,
            "engines": len(texts),
            "users": len(voted)
        }

    async def _preprocess(self, image_data: bytes) -> List[Tuple[bytes, str]]:
        def process():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return [(image_data, "original")]
            
            variants = []
            h, w = img.shape[:2]
            
            # Original
            _, buf = cv2.imencode('.png', img)
            variants.append((buf.tobytes(), "original"))
            
            # CLAHE - best for text
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            l = clahe.apply(l)
            enhanced = cv2.merge([l, a, b])
            enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
            _, buf = cv2.imencode('.png', enhanced)
            variants.append((buf.tobytes(), "clahe"))
            
            # Upscale if small
            if w < 1000:
                scaled = cv2.resize(img, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
                _, buf = cv2.imencode('.png', scaled)
                variants.append((buf.tobytes(), "upscaled"))
            
            return variants
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, process)

    async def _tesseract(self, image_data: bytes) -> str:
        def run():
            img = Image.open(io.BytesIO(image_data))
            import pytesseract
            return pytesseract.image_to_string(img, config='--psm 6 --oem 3')
        
        try:
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, run),
                timeout=Config.OCR_TIMEOUT
            )
        except:
            return ""

    async def _easyocr(self, image_data: bytes) -> str:
        def run():
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            results = self.easyocr_reader.readtext(img, detail=0)
            return ' '.join(results)
        
        try:
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, run),
                timeout=Config.OCR_TIMEOUT
            )
        except:
            return ""

    def _extract(self, text: str, hint: str, sources: List[str]) -> List[DetectedUser]:
        users = []
        lines = text.split('\n')
        lower = text.lower()
        has_context = any(w in lower for w in ['roblox', 'profile', '@', 'username'])
        
        # @username - highest priority
        for m in self.patterns['at'].finditer(text):
            u = m.group(1)
            if self._valid(u):
                conf = 1.0 if (hint and u.lower() == hint.lower().lstrip('@')) else 0.98
                users.append(DetectedUser(u, conf, '@mention', 'tesseract'))
        
        # URL
        for m in self.patterns['url'].finditer(text):
            users.append(DetectedUser(f"ID:{m.group(1)}", 0.99, 'url', 'tesseract'))
        
        # Labeled
        for m in self.patterns['label'].finditer(text):
            u = m.group(1)
            if self._valid(u):
                users.append(DetectedUser(u, 0.95, 'label', 'tesseract'))
        
        # Contextual
        for i, line in enumerate(lines):
            line_lower = line.lower()
            surrounding = ' '.join(lines[max(0,i-1):min(len(lines), i+2)]).lower()
            has_line_context = has_context or any(w in surrounding for w in ['roblox', '@', 'profile'])
            
            for m in self.patterns['user'].finditer(line):
                u = m.group(1)
                if not self._valid(u) or u.lower() in Config.FALSE_POSITIVES:
                    continue
                
                conf = 0.75 if has_line_context else 0.55
                
                # Boosts
                if any(w in surrounding for w in ['roblox', 'profile', '@']):
                    conf += 0.1
                if hint and u.lower() == hint.lower().lstrip('@'):
                    conf = 1.0
                if u[0].isupper() and not u.isupper():
                    conf += 0.05
                
                users.append(DetectedUser(u, min(conf, 0.95), 'context', 'tesseract'))
        
        return users

    def _valid(self, username: str) -> bool:
        return bool(username and Config.USERNAME_REGEX.match(username))

    def _vote(self, users: List[DetectedUser], hint: str) -> List[DetectedUser]:
        if not users:
            return []
        
        # Group by username
        groups = defaultdict(list)
        for u in users:
            groups[u.username.lower()].append(u)
        
        voted = []
        for username, group in groups.items():
            best = max(group, key=lambda x: x.confidence)
            conf = best.confidence
            
            # Boost for multiple detections
            if len(group) > 1:
                conf = min(conf + 0.05, 1.0)
            
            # Hint boost
            if hint and username == hint.lower().lstrip('@'):
                conf = 1.0
            
            voted.append(DetectedUser(best.username, conf, best.source, 'fusion'))
        
        # Sort and dedupe
        voted.sort(key=lambda x: x.confidence, reverse=True)
        seen = set()
        filtered = []
        for u in voted:
            if u.username.lower() not in seen:
                seen.add(u.username.lower())
                filtered.append(u)
        
        return filtered[:3]

# ═══════════════════════════════════════════════════════════
# HYPER ROBLOX API
# ═══════════════════════════════════════════════════════════
class HyperAPI:
    def __init__(self):
        self.session = None
        self.cache = {}
        
    async def setup(self):
        self.session = aiohttp.ClientSession(
            connector=TCPConnector(limit=100, limit_per_host=50),
            timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT),
            headers={"Accept": "application/json", "Accept-Encoding": "gzip"}
        )
    
    async def verify(self, users: List[DetectedUser]) -> List[Dict]:
        if not users:
            return []
        
        # Check cache
        to_fetch = []
        verified = []
        
        for u in users[:5]:
            cached = self.cache.get(u.username.lower())
            if cached:
                verified.append({'profile': cached, 'detected': u, 'score': u.confidence})
            else:
                to_fetch.append(u)
        
        # Fetch parallel
        if to_fetch:
            tasks = [self._fetch(u) for u in to_fetch]
            results = await asyncio.gather(*tasks)
            
            for u, profile in zip(to_fetch, results):
                if profile:
                    self.cache[u.username.lower()] = profile
                    verified.append({'profile': profile, 'detected': u, 'score': u.confidence})
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fetch(self, user: DetectedUser):
        try:
            if user.username.startswith("ID:"):
                uid = int(user.username.split(":")[1])
                async with self.session.get(f'https://users.roblox.com/v1/users/{uid}') as r:
                    if r.status == 200:
                        p = await r.json()
                        p['thumbnailUrl'] = await self._avatar(uid)
                        return p
                return None
            
            # Username lookup
            async with self.session.post(
                'https://users.roblox.com/v1/usernames/users',
                json={"usernames": [user.username], "excludeBannedUsers": False}
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                if not data.get('data'):
                    return None
                uid = data['data'][0]['id']
                
                async with self.session.get(f'https://users.roblox.com/v1/users/{uid}') as r2:
                    if r2.status == 200:
                        p = await r2.json()
                        p['thumbnailUrl'] = await self._avatar(uid)
                        return p
        except Exception as e:
            logger.debug(f"Fetch error: {e}")
        return None
    
    async def _avatar(self, uid: int):
        try:
            async with self.session.get(
                f'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={uid}&size=150x150&format=Png'
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get('data'):
                        return data['data'][0].get('imageUrl')
        except:
            pass
        return None

# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    def __init__(self):
        self.path = "downloads/videos"
        os.makedirs(self.path, exist_ok=True)
        self.executor = __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=2)
    
    def _fmt_duration(self, s):
        if not s: return "Unknown"
        try:
            s = int(float(s))
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        except:
            return "Unknown"
    
    async def download(self, url: str):
        domain = urlparse(url).netloc.lower().replace('www.', '')
        allowed = ['medal.tv', 'streamable.com', 'youtube.com', 'youtu.be',
                  'twitter.com', 'x.com', 'reddit.com', 'tiktok.com',
                  'instagram.com', 'facebook.com', 'twitch.tv']
        if not any(d in domain for d in allowed):
            return False, "Unsupported", None, None
        
        vid = hashlib.md5(url.encode()).hexdigest()[:8]
        out = os.path.join(self.path, f"{vid}.mp4")
        
        if os.path.exists(out):
            return True, "Cached", out, None
        
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(self.executor, self._run, url, out),
                timeout=120
            )
        except asyncio.TimeoutError:
            return False, "Timeout", None, None
    
    def _run(self, url, out):
        import subprocess
        try:
            # Info
            r = subprocess.run(['yt-dlp', '--dump-json', '--no-download', url],
                             capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return False, "Info failed", None, None
            
            info = json.loads(r.stdout.strip().split('\n')[0])
            vi = VideoInfo(
                url=url, title=info.get('title', 'Unknown'),
                duration=self._fmt_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            # Download
            r = subprocess.run(['yt-dlp', '-f', 'best[ext=mp4]/best', '--merge-output-format', 'mp4',
                              '-o', out, '--no-playlist', url],
                             capture_output=True, text=True, timeout=120)
            
            return os.path.exists(out), "Success" if os.path.exists(out) else "Failed", out, vi
            
        except Exception as e:
            return False, str(e), None, None
    
    async def info(self, url: str):
        loop = asyncio.get_event_loop()
        try:
            r = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    lambda: __import__('subprocess').run(['yt-dlp', '--dump-json', '--no-download', url],
                                                        capture_output=True, text=True, timeout=15)
                ), timeout=20
            )
            if r.returncode != 0:
                return False, None
            
            info = json.loads(r.stdout.strip().split('\n')[0])
            return True, VideoInfo(
                url=url, title=info.get('title', 'Unknown'),
                duration=self._fmt_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
        except:
            return False, None

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
class Database:
    def __init__(self):
        self.whitelist = set()
        os.makedirs("data", exist_ok=True)
        os.makedirs("downloads/videos", exist_ok=True)
        
    def setup(self):
        self.whitelist = {Config.OWNER_ID}
        try:
            if os.path.exists("data/whitelist.json"):
                with open("data/whitelist.json") as f:
                    self.whitelist.update(str(u) for u in json.load(f).get('users', []))
        except:
            pass
        logger.info(f"Whitelist: {len(self.whitelist)}")
    
    def is_whitelisted(self, uid: str) -> bool:
        return str(uid) in self.whitelist
    
    def get_stats(self, uid: str) -> Dict:
        try:
            with open(f"data/{uid}.json") as f:
                return json.load(f)
        except:
            return {'total': 0, 'success': 0, 'videos_downloaded': 0}
    
    def save_stats(self, uid: str, data: Dict):
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
        self.requests = {}
    
    async def check(self, key: str):
        now = time.time()
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
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.db = Database()
        self.limiter = RateLimiter(100, 60)
        self.video_limiter = RateLimiter(10, 60)
        self.ocr = None
        self.api = None
        self.video = VideoDownloader()
        
    async def setup_hook(self):
        logger.info("🔧 Starting MILITARY OMEGA v8.0...")
        
        self.db.setup()
        
        self.api = HyperAPI()
        await self.api.setup()
        
        self.ocr = MilitaryOCR()
        await self.ocr.init()
        
        # Commands
        @self.tree.command(name="scan", description="🔍 MILITARY SCAN - Maximum accuracy")
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
        
        await self.tree.sync()
        logger.info("✅ MILITARY OMEGA v8.0 READY")
    
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
            # Download image
            async with aiohttp.ClientSession() as s:
                async with s.get(image.url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status != 200:
                        await interaction.followup.send("❌ Download failed")
                        return
                    img = await r.read()
            
            # MILITARY SCAN
            success, users, meta = await self.ocr.scan(img, hint)
            
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
            verified = await self.api.verify(users)
            
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
            total = time.perf_counter() - start
            
            color = 0x00FF00 if det.confidence >= 0.95 else 0x55FF55 if det.confidence >= 0.80 else 0xFFAA00
            
            embed = discord.Embed(
                title=f"{prof.get('displayName', prof['name'])}",
                url=f"https://roblox.com/users/{prof['id']}/profile",
                description=f"**@{prof['name']}** • `{det.confidence:.0%}` confidence",
                color=color,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="🎯 Confidence", value=f"`{det.confidence:.0%}`", inline=True)
            embed.add_field(name="🔍 Source", value=f"`{det.source}`", inline=True)
            embed.add_field(name="⚡ Speed", value=f"`{total:.2f}s`", inline=True)
            embed.add_field(name="🆔 User ID", value=f"`{prof['id']}`", inline=True)
            embed.add_field(name="🧠 Engines", value=f"`{meta.get('engines', 1)}`", inline=True)
            embed.add_field(name="📊 Candidates", value=f"`{len(users)}`", inline=True)
            
            if prof.get('thumbnailUrl'):
                embed.set_thumbnail(url=prof['thumbnailUrl'])
            embed.set_image(url=image.url)
            embed.set_footer(text="MILITARY OMEGA v8.0")
            
            await interaction.followup.send(embed=embed)
            
            # Stats
            stats = self.db.get_stats(uid)
            stats['total'] += 1
            stats['success'] += 1
            self.db.save_stats(uid, stats)
            
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
                ok, info = await self.video.info(url)
                if not ok:
                    await interaction.followup.send("❌ Failed")
                    return
                
                embed = discord.Embed(
                    title=f"📹 {info.title[:100]}",
                    description=f"**{info.uploader}** • {info.duration}",
                    color=0x00D4AA
                )
                await interaction.followup.send(embed=embed)
            else:
                ok, msg, path, info = await self.video.download(url)
                if not ok or not path:
                    await interaction.followup.send(f"❌ {msg}")
                    return
                
                size = os.path.getsize(path)
                if size > Config.MAX_FILE_SIZE:
                    await interaction.followup.send("❌ Too large")
                    return
                
                file = discord.File(path, filename=os.path.basename(path))
                embed = discord.Embed(title=f"📥 {info.title[:100] if info else 'Video'}", color=0x00FF00)
                await interaction.followup.send(embed=embed, file=file)
                
                stats = self.db.get_stats(uid)
                stats['videos_downloaded'] = stats.get('videos_downloaded', 0) + 1
                self.db.save_stats(uid, stats)
        except Exception as e:
            logger.error(f"Download error: {e}")
            await interaction.followup.send("❌ Error")
    
    async def cmd_stats(self, interaction: discord.Interaction):
        stats = self.db.get_stats(str(interaction.user.id))
        embed = discord.Embed(title="📊 Statistics", color=0x00D4AA)
        embed.add_field(name="Scans", value=str(stats['total']), inline=True)
        embed.add_field(name="Success", value=str(stats['success']), inline=True)
        embed.add_field(name="Videos", value=str(stats.get('videos_downloaded', 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def cmd_ping(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏓 Pong", color=0x00D4AA)
        embed.add_field(name="Latency", value=f"`{round(self.latency * 1000)}ms`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════
# HEALTH SERVER
# ═══════════════════════════════════════════════════════════
async def health_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8080))).start()

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def main():
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
