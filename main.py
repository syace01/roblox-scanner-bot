""" 🎯 TRUE OMEGA - FAST FONT-PROOF OCR """
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
import shutil
import subprocess
import aiohttp
import difflib
from datetime import datetime
from urllib.parse import urlparse, quote
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')

OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
TOKEN = os.getenv('DISCORD_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://ptb.discord.com/api/webhooks/1474073290183282952/JTVRmKnXqqka8IqE0ZpWAtTvsMLd2tfpxbU93KGHWu-gDzQQwktjBf6QTmhPvy-zFZ1_')

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN not set!")
    sys.exit(1)

print("=" * 60)
print("🎯 TRUE OMEGA - FAST FONT-PROOF OCR")
print("=" * 60)

try:
    import discord
    from discord import app_commands
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
    print("✅ NumPy available")
except:
    NP_AVAILABLE = False
    print("⚠️ NumPy not available")

try:
    import cv2
    CV2_AVAILABLE = True
    print("✅ OpenCV available")
except:
    CV2_AVAILABLE = False
    print("⚠️ OpenCV not available")

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
    print("⚠️ Pillow not available")

# Thread pool for CPU-intensive OCR
ocr_executor = ThreadPoolExecutor(max_workers=4)

class WebhookLogger:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.session = None
    
    async def setup(self):
        self.session = aiohttp.ClientSession()
    
    async def log(self, content=None, embed=None, username="TRUE OMEGA"):
        if not self.session:
            await self.setup()
        try:
            payload = {"username": username, "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"}
            if content:
                payload["content"] = content
            if embed:
                payload["embeds"] = [embed.to_dict() if isinstance(embed, discord.Embed) else embed]
            async with self.session.post(self.webhook_url, json=payload) as resp:
                pass
        except:
            pass

class UniversalDownloader:
    def __init__(self):
        self.path = tempfile.mkdtemp()
    
    async def download(self, url: str, user_id: str) -> dict:
        if not YTDLP_AVAILABLE:
            return {"success": False, "error": "yt-dlp not installed"}
        dl_id = f"{user_id}_{int(time.time())}"
        output_template = os.path.join(self.path, f"{dl_id}.%(ext)s")
        try:
            loop = asyncio.get_event_loop()
            def dl():
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': output_template,
                    'quiet': True,
                    'no_warnings': True,
                    'max_filesize': 25 * 1024 * 1024,
                    'merge_output_format': 'mp4',
                    'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
                    'geo_bypass': True,
                    'nocheckcertificate': True,
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        downloaded = [f for f in os.listdir(self.path) if f.startswith(dl_id)]
                        if not downloaded:
                            return {"success": False, "error": "No file downloaded"}
                        actual = os.path.join(self.path, downloaded[0])
                        return {"success": True, "file_path": actual, "title": info.get('title', 'video'), "size": os.path.getsize(actual)}
                except Exception as e:
                    return {"success": False, "error": str(e)[:250]}
            return await asyncio.wait_for(loop.run_in_executor(None, dl), timeout=180)
        except Exception as e:
            return {"success": False, "error": str(e)[:250]}
    
    def cleanup(self, file_path: str):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

class FastOCRScanner:
    """Optimized OCR with parallel processing and early exit"""
    
    def __init__(self):
        self.session = None
        self.easyocr_reader = None
        if EASYOCR_AVAILABLE:
            try:
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                print("✅ EasyOCR ready")
            except Exception as e:
                print(f"⚠️ EasyOCR init: {e}")
    
    async def setup(self):
        self.session = aiohttp.ClientSession()
    
    def preprocess_fast(self, image_data: bytes, method: str) -> bytes:
        """Fast preprocessing - no heavy operations"""
        if not PIL_AVAILABLE:
            return image_data
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            if method == "contrast":
                # Fast: just resize and contrast
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.5)
                
            elif method == "bw":
                # Fast: grayscale + threshold
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = ImageOps.grayscale(img)
                img = img.point(lambda x: 0 if x < 128 else 255, '1')
                img = img.convert('RGB')
                
            elif method == "sharp":
                # Fast: sharpen once
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = img.filter(ImageFilter.SHARPEN)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.0)
            
            output = io.BytesIO()
            img.save(output, format='PNG', optimize=True)
            return output.getvalue()
        except:
            return image_data
    
    def opencv_fast(self, image_data: bytes, method: str) -> bytes:
        """Fast OpenCV preprocessing"""
        if not CV2_AVAILABLE or not NP_AVAILABLE:
            return image_data
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
            
            if method == "adaptive":
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                               cv2.THRESH_BINARY, 11, 2)
                img = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
            elif method == "clahe":
                lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                img = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
            
            _, buffer = cv2.imencode('.png', img)
            return buffer.tobytes()
        except:
            return image_data
    
    async def scan_fast(self, image_data: bytes, hint: str = None) -> dict:
        """Fast parallel OCR with early exit on high confidence"""
        results = {"success": False, "users": [], "best_match": None, "ocr_texts": {}, "methods_tried": []}
        all_texts = []
        
        # Create preprocessed versions in parallel
        preprocess_tasks = []
        methods = []
        
        if PIL_AVAILABLE:
            for method in ["contrast", "bw", "sharp"]:
                preprocess_tasks.append(asyncio.get_event_loop().run_in_executor(
                    None, self.preprocess_fast, image_data, method))
                methods.append(f"pil_{method}")
        
        if CV2_AVAILABLE and NP_AVAILABLE:
            for method in ["adaptive", "clahe"]:
                preprocess_tasks.append(asyncio.get_event_loop().run_in_executor(
                    None, self.opencv_fast, image_data, method))
                methods.append(f"cv_{method}")
        
        # Also include raw
        processed_images = [image_data]
        method_names = ["raw"]
        
        if preprocess_tasks:
            processed = await asyncio.gather(*preprocess_tasks)
            for img, name in zip(processed, methods):
                if img != image_data:
                    processed_images.append(img)
                    method_names.append(name)
        
        # Run OCRs in parallel with early cancellation
        ocr_tasks = []
        
        # OCR.Space on multiple versions
        if OCR_SPACE_KEY:
            for img, name in zip(processed_images[:3], method_names[:3]):  # Limit to 3 for speed
                ocr_tasks.append(self._ocr_space_with_name(img, name))
        
        # EasyOCR on best preprocessed version
        if self.easyocr_reader and len(processed_images) > 0:
            ocr_tasks.append(self._easyocr_with_name(processed_images[0], "easyocr"))
        
        # Gather all OCR results
        ocr_results = await asyncio.gather(*ocr_tasks, return_exceptions=True)
        
        for result in ocr_results:
            if isinstance(result, Exception):
                continue
            if result and result[1]:  # (name, text)
                name, text = result
                results["ocr_texts"][name] = text
                results["methods_tried"].append(name)
                all_texts.append(text)
        
        if not all_texts:
            return results
        
        # Combine and extract
        combined = self._combine_texts_fast(all_texts)
        results["combined_text"] = combined
        
        users = self._extract_roblox_users_fast(combined, hint)
        if not users:
            return results
        
        # Verify - early exit if perfect match
        verified = await self._verify_fast(users, combined, hint)
        if verified:
            results["success"] = True
            results["users"] = verified
            results["best_match"] = verified[0]
        
        return results
    
    async def _ocr_space_with_name(self, image_data: bytes, name: str) -> tuple:
        """OCR.Space with timeout"""
        try:
            b64 = base64.b64encode(image_data).decode()
            data = {
                'apikey': OCR_SPACE_KEY,
                'base64Image': f'data:image/png;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true',
            }
            async with self.session.post('https://api.ocr.space/parse/image', data=data, timeout=20) as resp:
                result = await resp.json()
            if result.get('IsErroredOnProcessing'):
                return (name, "")
            text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
            return (name, text)
        except asyncio.TimeoutError:
            return (name, "")
        except:
            return (name, "")
    
    async def _easyocr_with_name(self, image_data: bytes, name: str) -> tuple:
        """EasyOCR in thread pool"""
        if not self.easyocr_reader or not NP_AVAILABLE:
            return (name, "")
        try:
            import cv2
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(ocr_executor, self.easyocr_reader.readtext, img),
                timeout=15
            )
            text = '\n'.join([item[1] for item in result])
            return (name, text)
        except asyncio.TimeoutError:
            return (name, "")
        except:
            return (name, "")
    
    def _combine_texts_fast(self, texts: list) -> str:
        """Fast deduplication"""
        all_lines = []
        seen = set()
        for text in texts:
            for line in text.split('\n'):
                cleaned = line.strip()
                if cleaned and len(cleaned) > 1:
                    norm = re.sub(r'[^\w@]', '', cleaned).lower()
                    if norm and norm not in seen:
                        seen.add(norm)
                        all_lines.append(cleaned)
        return '\n'.join(all_lines)
    
    def _extract_roblox_users_fast(self, text: str, hint: str) -> list:
        """Optimized Roblox username extraction"""
        users = []
        lines = text.split('\n')
        text_lower = text.lower()
        
        # Roblox UI common words to exclude
        exclude = {'roblox', 'profile', 'home', 'games', 'friends', 'inventory', 
                   'avatar', 'shop', 'create', 'about', 'chat', 'trade', 'premium',
                   'settings', 'search', 'menu', 'play', 'join', 'exit', 'back',
                   'online', 'offline', 'away', 'busy', 'studio', 'more', 'catalog',
                   'develop', 'money', 'transactions', 'groups', 'messages', 'notifications',
                   'the', 'and', 'for', 'you', 'are', 'can', 'all', 'any', 'use', 'new',
                   'add', 'edit', 'delete', 'view', 'open', 'close', 'send', 'get', 'go',
                   'connection', 'match', 'confidence', 'verification', 'status', 'created',
                   'user', 'id', 'about', 'other', 'matches', 'banned', 'active', 'today',
                   'font', 'proof', 'scanning', 'omega', 'true'}
        
        # Pattern 1: @username (most common in Roblox)
        for i, line in enumerate(lines):
            # Multiple @ patterns for different fonts
            matches = re.findall(r'[@＠﹫]([A-Za-z0-9_]{3,20})\b', line)
            for username in matches:
                username_lower = username.lower()
                if username_lower in exclude:
                    continue
                    
                conf = 0.85
                display = None
                
                # Check line before @ for display name
                parts = re.split(r'[@＠﹫]', line)
                if len(parts) > 1:
                    before = parts[0].strip()
                    before_clean = re.sub(r'[^\w\s]', '', before).strip()
                    if before_clean and len(before_clean) > 1 and before_clean.lower() not in exclude:
                        display = before_clean
                        conf = 0.95
                
                # Check previous line
                if not display and i > 0:
                    prev = lines[i-1].strip()
                    prev_clean = re.sub(r'[^\w\s]', '', prev).strip()
                    if prev_clean and 2 < len(prev_clean) < 25 and prev_clean.lower() not in exclude:
                        display = prev_clean
                        conf = 0.9
                
                users.append({'username': username, 'display': display, 'confidence': conf, 'source': '@mention'})
        
        # Pattern 2: Roblox URLs (high confidence)
        url_matches = re.findall(r'roblox\.com/users/(\d+)', text, re.IGNORECASE)
        for uid in url_matches:
            users.insert(0, {'username': f'ID:{uid}', 'id': uid, 'confidence': 0.98, 'source': 'url'})
        
        # Pattern 3: "Display @Username" or "Display Username" pairs
        for line in lines:
            # Common Roblox UI pattern
            pair = re.search(r'^([A-Z][a-zA-Z\s]{1,18}[a-zA-Z])\s*[@\s]\s*([a-z][a-z0-9_]{2,19})\b', line)
            if pair:
                display, username = pair.group(1).strip(), pair.group(2)
                if display.lower() not in exclude and username.lower() not in exclude:
                    existing = next((u for u in users if u['username'].lower() == username.lower()), None)
                    if existing:
                        existing['display'] = display
                        existing['confidence'] = 0.98
                        existing['source'] = 'display@user'
                    else:
                        users.append({'username': username, 'display': display, 'confidence': 0.98, 'source': 'display@user'})
        
        # Pattern 4: Username-like patterns (low confidence)
        potentials = re.findall(r'\b([a-z][a-z0-9_]{2,19})\b', text_lower)
        for name in set(potentials):
            if name not in exclude:
                if not any(u['username'].lower() == name for u in users):
                    # Check if near @ symbol in text
                    near_at = f'@{name}' in text_lower or f'@ {name}' in text_lower
                    conf = 0.6 if near_at else 0.45
                    users.append({'username': name, 'display': None, 'confidence': conf, 'source': 'pattern'})
        
        # Pattern 5: Hint override
        if hint:
            h = hint.strip().lower().replace('@', '')
            if re.match(r'^[a-z0-9_]{3,20}$', h) and h not in exclude:
                existing = next((u for u in users if u['username'].lower() == h), None)
                if existing:
                    existing['confidence'] = 1.0
                    existing['source'] = 'hint'
                else:
                    users.insert(0, {'username': h, 'display': None, 'confidence': 1.0, 'source': 'hint'})
        
        # Remove duplicates and sort by confidence
        seen = set()
        unique = []
        for u in sorted(users, key=lambda x: x['confidence'], reverse=True):
            key = u['username'].lower()
            if key not in seen:
                seen.add(key)
                unique.append(u)
        
        return unique
    
    async def _verify_fast(self, potentials: list, full_text: str, hint: str) -> list:
        """Fast verification with early exit"""
        verified = []
        full_lower = full_text.lower()
        
        for data in potentials[:6]:  # Limit to top 6
            username = data['username']
            
            if username.startswith('ID:'):
                continue
            
            try:
                # Fast API call
                async with self.session.post(
                    'https://users.roblox.com/v1/usernames/users',
                    json={"usernames": [username], "excludeBannedUsers": False},
                    timeout=8
                ) as resp:
                    if resp.status != 200:
                        continue
                    r = await resp.json()
                    
                    if not r.get('data'):
                        # Try fuzzy search
                        similar = await self._fuzzy_search_fast(username)
                        if similar:
                            r = {"data": [similar]}
                        else:
                            continue
                    
                    info = r['data'][0]
                    
                    # Get profile
                    async with self.session.get(f'https://users.roblox.com/v1/users/{info["id"]}', timeout=8) as resp:
                        if resp.status != 200:
                            continue
                        profile = await resp.json()
                
                # Calculate score
                score = data['confidence']
                reasons = [f"{data['source']} ({data['confidence']:.0%})"]
                
                prof_display = profile.get('displayName', '')
                ocr_display = data.get('display')
                
                # Display match bonus
                if ocr_display and prof_display:
                    sim = difflib.SequenceMatcher(None, ocr_display.lower(), prof_display.lower()).ratio()
                    if sim > 0.8:
                        score = min(score + 0.15, 1.0)
                        reasons.append(f"display:{sim:.0%}")
                
                if prof_display and prof_display.lower() in full_lower:
                    score = min(score + 0.1, 1.0)
                    reasons.append("display_in_img")
                
                # Hint bonus
                if hint and username.lower() == hint.lower().replace('@', ''):
                    score = 1.0
                    reasons.append("🎯HINT")
                
                verified.append({'profile': profile, 'score': score, 'reasons': reasons})
                
                # Early exit if perfect match
                if score >= 0.95:
                    break
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                continue
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _fuzzy_search_fast(self, username: str) -> dict:
        """Fast fuzzy search"""
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=3',
                timeout=8
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        for u in data['data']:
                            sim = difflib.SequenceMatcher(None, username.lower(), u['name'].lower()).ratio()
                            if sim > 0.75:
                                return u
        except:
            pass
        return None

class Bot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.default(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.whitelist = {str(OWNER_ID)}
        self.whitelist_file = 'whitelist.json'
        self.webhook = WebhookLogger(WEBHOOK_URL)
        self.session = None
        self.downloader = None
        self.scanner = None
    
    def save_whitelist(self):
        try:
            with open(self.whitelist_file, 'w') as f:
                json.dump({"users": list(self.whitelist)}, f)
        except:
            pass
    
    async def setup_hook(self):
        print("🔧 Setting up...")
        await self.webhook.setup()
        
        self.scanner = FastOCRScanner()
        await self.scanner.setup()
        self.session = self.scanner.session
        self.downloader = UniversalDownloader()
        
        try:
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, 'r') as f:
                    data = json.load(f)
                    self.whitelist.update(str(u) for u in data.get('users', []))
                print(f"✅ Loaded {len(self.whitelist)} whitelisted")
        except Exception as e:
            print(f"Whitelist load: {e}")
        
        # Clear and sync commands
        print("🔄 Syncing commands...")
        self.tree.clear_commands(guild=None)
        
        @self.tree.command(name="scan", description="🔍 FAST Roblox username scanner")
        @app_commands.describe(image="Screenshot", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await interaction.response.defer()
            if str(interaction.user.id) not in self.whitelist and str(interaction.user.id) != str(OWNER_ID):
                await interaction.followup.send("⛔ Not whitelisted!", ephemeral=True)
                return
            await self.do_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download video to MP4")
        @app_commands.describe(url="Video URL")
        async def download(interaction: discord.Interaction, url: str):
            await interaction.response.defer()
            if str(interaction.user.id) not in self.whitelist and str(interaction.user.id) != str(OWNER_ID):
                await interaction.followup.send("⛔ Not whitelisted!", ephemeral=True)
                return
            await self.do_download(interaction, url)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (Owner only)")
        @app_commands.describe(user="User to add/remove")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await interaction.response.defer(ephemeral=True)
            if str(interaction.user.id) != str(OWNER_ID):
                await interaction.followup.send("⛔ Owner only!", ephemeral=True)
                return
            await self.do_whitelist(interaction, user)
        
        for attempt in range(5):
            try:
                synced = await self.tree.sync()
                print(f"✅ Synced {len(synced)} commands")
                break
            except discord.HTTPException as e:
                if e.status == 429:
                    wait = getattr(e, 'retry_after', 5)
                    print(f"⏳ Rate limit, waiting {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    print(f"Sync error: {e}")
                    await asyncio.sleep(2)
        
        print("✅ Ready!")
    
    async def do_whitelist(self, interaction, user_input):
        target = re.sub(r'[<@!>]', '', user_input).strip()
        if not target.isdigit():
            await interaction.followup.send("❌ Invalid ID", ephemeral=True)
            return
        
        try:
            user = await self.fetch_user(int(target))
            name = f"@{user.name}" if user else target
        except:
            name = target
        
        if target in self.whitelist:
            if target == str(OWNER_ID):
                await interaction.followup.send("⛔ Can't remove owner", ephemeral=True)
                return
            self.whitelist.remove(target)
            self.save_whitelist()
            await self.webhook.log(content=f"❌ Removed {name}")
            await interaction.followup.send(f"❌ Removed {name}", ephemeral=True)
        else:
            self.whitelist.add(target)
            self.save_whitelist()
            await self.webhook.log(content=f"✅ Added {name}")
            await interaction.followup.send(f"✅ Added {name}", ephemeral=True)
    
    async def do_scan(self, interaction, image, hint):
        start_time = time.time()
        try:
            if image.size and image.size > 50 * 1024 * 1024:
                await interaction.followup.send("❌ Image too large (max 50MB)")
                return
            
            # Download image
            async with self.session.get(image.url, timeout=15) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to download image")
                    return
                img_data = await resp.read()
            
            # Quick processing message
            await interaction.followup.send(embed=discord.Embed(
                title="🔍 Scanning...", 
                description="Analyzing image...", 
                color=0xFFA500
            ))
            
            # Run fast scan
            result = await self.scanner.scan_fast(img_data, hint)
            
            elapsed = time.time() - start_time
            
            if not result['success']:
                preview = result.get('combined_text', 'Nothing')[:400]
                await interaction.edit_original_response(embed=discord.Embed(
                    title="❌ No User Found",
                    description=f"Couldn't verify user.\n\n**Detected:**\n```{preview}...```\n\n*Try `/scan image:@user hint:username`*",
                    color=0xFF0000
                ))
                return
            
            best = result['best_match']
            profile = best['profile']
            score = best['score']
            
            # Color
            if profile.get('isBanned'):
                color = 0x8B0000
            elif score >= 0.9:
                color = 0x00FF00
            elif score >= 0.7:
                color = 0xFFA500
            else:
                color = 0xFFFF00
            
            embed = discord.Embed(
                title=f"{profile.get('displayName', profile['name'])}",
                description=f"@{profile['name']}\n**Confidence:** `{score:.0%}`",
                url=f'https://roblox.com/users/{profile["id"]}/profile',
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(name="✅ Verified", value=' | '.join(best['reasons'][:3]), inline=False)
            embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
            embed.add_field(name="📅 Created", value=str(profile.get('created', 'N/A'))[:10], inline=True)
            embed.add_field(name="⚡ Status", value="🔴 BANNED" if profile.get('isBanned') else "✅ Active", inline=True)
            
            if profile.get('description'):
                desc = profile['description'][:180] + "..." if len(profile['description']) > 180 else profile['description']
                embed.add_field(name="📝 About", value=desc, inline=False)
            
            if len(result['users']) > 1:
                others = [f"`@{u['profile']['name']}` ({u['score']:.0%})" for u in result['users'][1:3]]
                if others:
                    embed.add_field(name="🔍 Others", value=" | ".join(others), inline=False)
            
            embed.set_image(url=image.url)
            methods = len(result.get('methods_tried', []))
            embed.set_footer(text=f"⚡ {elapsed:.1f}s | {methods} methods | TRUE OMEGA")
            
            await interaction.edit_original_response(embed=embed)
            
        except Exception as e:
            print(f"Scan error: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    async def do_download(self, interaction, url):
        try:
            result = await self.downloader.download(url, str(interaction.user.id))
            if not result['success']:
                await interaction.followup.send(f"❌ Download failed: `{result['error'][:100]}`")
                return
            
            size_mb = result['size'] / (1024 * 1024)
            if result['size'] > 25 * 1024 * 1024:
                await interaction.followup.send(f"⚠️ File too large ({size_mb:.1f}MB)")
                self.downloader.cleanup(result['file_path'])
                return
            
            safe = re.sub(r'[^\w\-_.]', '_', result['title'][:50])
            file = discord.File(result['file_path'], filename=f"{safe}.mp4")
            
            embed = discord.Embed(title="⚡ Download Complete", description=f"**{result['title'][:80]}**", color=0x00D4AA)
            embed.add_field(name="📦 Size", value=f"{size_mb:.1f}MB", inline=True)
            
            await interaction.followup.send(embed=embed, file=file)
            self.downloader.cleanup(result['file_path'])
        except Exception as e:
            print(f"Download error: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    async def on_ready(self):
        print(f"\n{'='*50}")
        print(f"✅ BOT ONLINE: {self.user}")
        print(f"   Servers: {len(self.guilds)}")
        print(f"   Whitelisted: {len(self.whitelist)}")
        print(f"{'='*50}\n")

def main():
    while True:
        try:
            bot = Bot()
            bot.run(TOKEN, log_handler=None)
            print("⚠️ Restarting in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"Fatal: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
