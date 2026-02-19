""" 🎯 TRUE OMEGA - ULTIMATE OCR SCANNER """
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
from typing import List, Dict, Optional, Tuple

warnings.filterwarnings('ignore')

# Config
OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
TOKEN = os.getenv('DISCORD_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://ptb.discord.com/api/webhooks/1474073290183282952/JTVRmKnXqqka8IqE0ZpWAtTvsMLd2tfpxbU93KGHWu-gDzQQwktjBf6QTmhPvy-zFZ1_')

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN environment variable not set!")
    sys.exit(1)

print("=" * 60)
print("🎯 TRUE OMEGA BOT - ULTIMATE OCR SCANNER")
print("=" * 60)

try:
    import discord
    from discord import app_commands
    print("✅ Core imports successful")
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

# Try to import additional OCR libraries
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    print("✅ EasyOCR available")
except:
    EASYOCR_AVAILABLE = False
    print("⚠️ EasyOCR not available")

try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
    print("✅ Tesseract available")
except:
    TESSERACT_AVAILABLE = False
    print("⚠️ Tesseract not available")

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
    print("✅ OpenCV available")
except:
    CV2_AVAILABLE = False
    print("⚠️ OpenCV not available")

class WebhookLogger:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.session = None
    
    async def setup(self):
        self.session = aiohttp.ClientSession()
    
    async def log(self, content=None, embed=None, username="TRUE OMEGA Logger"):
        if not self.session:
            await self.setup()
        try:
            payload = {
                "username": username,
                "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"
            }
            if content:
                payload["content"] = content
            if embed:
                payload["embeds"] = [embed.to_dict() if isinstance(embed, discord.Embed) else embed]
            
            async with self.session.post(self.webhook_url, json=payload) as resp:
                if resp.status not in [200, 204]:
                    print(f"Webhook failed: {resp.status}")
        except Exception as e:
            print(f"Webhook error: {e}")

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
                    'postprocessors': [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    }],
                    'geo_bypass': True,
                    'nocheckcertificate': True,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    },
                }
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        downloaded_files = [f for f in os.listdir(self.path) if f.startswith(dl_id)]
                        
                        if not downloaded_files:
                            return {"success": False, "error": "No file downloaded"}
                        
                        actual_file = os.path.join(self.path, downloaded_files[0])
                        file_size = os.path.getsize(actual_file)
                        
                        if not actual_file.endswith('.mp4'):
                            mp4_file = actual_file.rsplit('.', 1)[0] + '.mp4'
                            try:
                                subprocess.run(['ffmpeg', '-i', actual_file, '-c', 'copy', mp4_file, '-y'], 
                                             capture_output=True, timeout=30)
                                if os.path.exists(mp4_file):
                                    os.remove(actual_file)
                                    actual_file = mp4_file
                                    file_size = os.path.getsize(actual_file)
                            except:
                                os.rename(actual_file, mp4_file)
                                actual_file = mp4_file
                        
                        return {
                            "success": True,
                            "file_path": actual_file,
                            "title": info.get('title', 'video') if isinstance(info, dict) else 'video',
                            "size": file_size,
                        }
                        
                except Exception as e:
                    error_msg = str(e)
                    if 'format' in error_msg.lower():
                        ydl_opts['format'] = None
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                            info = ydl2.extract_info(url, download=True)
                            downloaded_files = [f for f in os.listdir(self.path) if f.startswith(dl_id)]
                            if downloaded_files:
                                actual_file = os.path.join(self.path, downloaded_files[0])
                                return {
                                    "success": True,
                                    "file_path": actual_file,
                                    "title": info.get('title', 'video') if isinstance(info, dict) else 'video',
                                    "size": os.path.getsize(actual_file),
                                }
                    raise e
            
            return await asyncio.wait_for(loop.run_in_executor(None, dl), timeout=180)
                
        except Exception as e:
            print(f"Download error: {e}")
            return {"success": False, "error": str(e)[:250]}
    
    def cleanup(self, file_path: str):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

class UltimateRobloxScanner:
    """Multi-engine OCR with advanced Roblox username detection"""
    
    def __init__(self):
        self.session = None
        self.easyocr_reader = None
        if EASYOCR_AVAILABLE:
            try:
                # Initialize EasyOCR with English
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                print("✅ EasyOCR initialized")
            except Exception as e:
                print(f"⚠️ EasyOCR init failed: {e}")
    
    async def setup(self):
        self.session = aiohttp.ClientSession()
    
    async def scan_image(self, image_data: bytes, hint: str = None) -> Dict:
        """
        Ultimate scanning with multiple OCR engines and verification
        """
        results = {
            "success": False,
            "users": [],
            "best_match": None,
            "ocr_texts": {},
            "verification_details": []
        }
        
        # Run all OCR engines
        ocr_tasks = []
        
        # OCR.Space
        if OCR_SPACE_KEY:
            ocr_tasks.append(self._ocr_space(image_data))
        
        # EasyOCR
        if self.easyocr_reader:
            ocr_tasks.append(self._easyocr_scan(image_data))
        
        # Tesseract
        if TESSERACT_AVAILABLE:
            ocr_tasks.append(self._tesseract_scan(image_data))
        
        # Run all OCRs concurrently
        ocr_results = await asyncio.gather(*ocr_tasks, return_exceptions=True)
        
        all_texts = []
        for i, result in enumerate(ocr_results):
            if isinstance(result, Exception):
                print(f"OCR {i} failed: {result}")
                continue
            if result:
                engine_name = ["OCR.Space", "EasyOCR", "Tesseract"][i] if i < 3 else f"OCR_{i}"
                results["ocr_texts"][engine_name] = result
                all_texts.append(result)
        
        if not all_texts:
            return results
        
        # Combine and deduplicate texts
        combined_text = self._combine_ocr_texts(all_texts)
        results["combined_text"] = combined_text
        
        # Extract potential usernames using multiple methods
        potential_users = self._extract_all_usernames(combined_text, hint)
        
        if not potential_users:
            return results
        
        # Verify each potential user against Roblox API
        verified_users = await self._verify_users(potential_users, combined_text, hint)
        
        if verified_users:
            results["success"] = True
            results["users"] = verified_users
            results["best_match"] = verified_users[0]
        
        return results
    
    async def _ocr_space(self, image_data: bytes) -> str:
        """OCR.Space API"""
        try:
            b64 = base64.b64encode(image_data).decode()
            data = {
                'apikey': OCR_SPACE_KEY,
                'base64Image': f'data:image/jpeg;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true',
                'detectOrientation': 'true',
                'isTable': 'false',
            }
            
            async with self.session.post('https://api.ocr.space/parse/image', data=data, timeout=45) as resp:
                result = await resp.json()
            
            if result.get('IsErroredOnProcessing'):
                return ""
            
            parsed = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
            return parsed
        except Exception as e:
            print(f"OCR.Space error: {e}")
            return ""
    
    async def _easyocr_scan(self, image_data: bytes) -> str:
        """EasyOCR local processing"""
        try:
            # Convert bytes to numpy array
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            # Run OCR
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.easyocr_reader.readtext, img)
            
            # Extract text
            texts = [item[1] for item in result]
            return '\n'.join(texts)
        except Exception as e:
            print(f"EasyOCR error: {e}")
            return ""
    
    async def _tesseract_scan(self, image_data: bytes) -> str:
        """Tesseract OCR"""
        try:
            from PIL import Image
            import io
            
            image = Image.open(io.BytesIO(image_data))
            
            # Preprocess for better results
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, 
                lambda: pytesseract.image_to_string(image, config='--psm 6')
            )
            return text
        except Exception as e:
            print(f"Tesseract error: {e}")
            return ""
    
    def _combine_ocr_texts(self, texts: List[str]) -> str:
        """Combine texts from multiple OCR engines and remove duplicates"""
        all_lines = []
        seen_lines = set()
        
        for text in texts:
            lines = text.split('\n')
            for line in lines:
                cleaned = line.strip()
                if cleaned and len(cleaned) > 2:
                    # Normalize for deduplication
                    normalized = re.sub(r'[^\w@]', '', cleaned).lower()
                    if normalized not in seen_lines:
                        seen_lines.add(normalized)
                        all_lines.append(cleaned)
        
        return '\n'.join(all_lines)
    
    def _extract_all_usernames(self, text: str, hint: str = None) -> List[Dict]:
        """
        Extract usernames using multiple pattern matching strategies
        """
        users = []
        lines = text.split('\n')
        full_text_lower = text.lower()
        
        # Strategy 1: Direct @mentions with context
        for i, line in enumerate(lines):
            # Find @username patterns
            at_matches = re.findall(r'@([A-Za-z0-9_]{3,20})\b', line)
            
            for username in at_matches:
                user_data = {
                    'username': username,
                    'display': None,
                    'confidence': 0.7,
                    'source': 'at_mention',
                    'line_context': line
                }
                
                # Look for display name before @
                parts = line.split('@')
                if len(parts) > 1:
                    before_at = parts[0].strip()
                    # Clean up display name
                    display = re.sub(r'[^\w\s]', '', before_at).strip()
                    if display and len(display) > 1:
                        user_data['display'] = display
                        user_data['confidence'] = 0.8
                
                # Look at previous line for display name
                if not user_data['display'] and i > 0:
                    prev_line = lines[i-1].strip()
                    if prev_line and '@' not in prev_line and len(prev_line) < 30:
                        user_data['display'] = prev_line
                        user_data['confidence'] = 0.75
                
                # Look at next line for display name
                if not user_data['display'] and i < len(lines) - 1:
                    next_line = lines[i+1].strip()
                    if next_line and '@' not in next_line and len(next_line) < 30:
                        user_data['display'] = next_line
                        user_data['confidence'] = 0.75
                
                users.append(user_data)
        
        # Strategy 2: Roblox profile URLs
        url_patterns = [
            r'roblox\.com/users/(\d+)',
            r'roblox\.com/user\.aspx\?id=(\d+)',
            r'web\.roblox\.com/users/(\d+)',
        ]
        
        for pattern in url_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for uid in matches:
                users.insert(0, {
                    'username': f'ID:{uid}',
                    'id': uid,
                    'confidence': 0.95,
                    'source': 'url',
                    'line_context': f'User ID: {uid}'
                })
        
        # Strategy 3: Common Roblox username patterns
        # Look for text that looks like usernames (3-20 chars, alphanumeric + underscore)
        potential_names = re.findall(r'\b([A-Za-z0-9_]{3,20})\b', text)
        
        common_words = {'the', 'and', 'for', 'you', 'roblox', 'profile', 'home', 'games', 
                       'friends', 'inventory', 'avatar', 'shop', 'create', 'about', 
                       'chat', 'party', 'trade', 'premium', 'settings', 'search'}
        
        for name in potential_names:
            name_lower = name.lower()
            if name_lower not in common_words:
                # Check if not already found
                if not any(u['username'].lower() == name_lower for u in users):
                    # Check if it appears near "@" or in a username-like context
                    context_score = 0.5
                    
                    # Check surrounding text for username indicators
                    if f'@{name}' in text or f'@ {name}' in text:
                        context_score = 0.6
                    
                    users.append({
                        'username': name,
                        'display': None,
                        'confidence': context_score,
                        'source': 'pattern',
                        'line_context': name
                    })
        
        # Strategy 4: Display name + username pairs
        # Look for patterns like "DisplayName @username"
        for i, line in enumerate(lines):
            # Pattern: "Name @username" or "Name@username"
            pair_match = re.search(r'([A-Za-z\s]{2,25})\s*[@\s]\s*([A-Za-z0-9_]{3,20})\b', line)
            if pair_match:
                display = pair_match.group(1).strip()
                username = pair_match.group(2)
                
                # Update existing or add new
                existing = next((u for u in users if u['username'].lower() == username.lower()), None)
                if existing:
                    existing['display'] = display
                    existing['confidence'] = 0.9
                    existing['source'] = 'pair_match'
                else:
                    users.append({
                        'username': username,
                        'display': display,
                        'confidence': 0.9,
                        'source': 'pair_match',
                        'line_context': line
                    })
        
        # Strategy 5: If hint provided, boost it
        if hint:
            hint_clean = hint.strip().lower().replace('@', '')
            if re.match(r'^[a-z0-9_]{3,20}$', hint_clean):
                # Check if hint is already in list
                existing = next((u for u in users if u['username'].lower() == hint_clean), None)
                if existing:
                    existing['confidence'] = 1.0
                    existing['source'] = 'hint'
                else:
                    users.insert(0, {
                        'username': hint_clean,
                        'display': None,
                        'confidence': 1.0,
                        'source': 'hint',
                        'line_context': f'User hint: {hint}'
                    })
        
        # Sort by confidence (highest first)
        users.sort(key=lambda x: x['confidence'], reverse=True)
        
        return users
    
    async def _verify_users(self, potential_users: List[Dict], full_text: str, hint: str = None) -> List[Dict]:
        """
        Verify potential users against Roblox API with display name matching
        """
        verified = []
        full_text_lower = full_text.lower()
        
        for user_data in potential_users[:8]:  # Check top 8 candidates
            username = user_data['username']
            
            # Skip ID-based lookups for now (handle separately)
            if username.startswith('ID:'):
                continue
            
            try:
                # Lookup username
                async with self.session.post(
                    'https://users.roblox.com/v1/usernames/users',
                    json={"usernames": [username], "excludeBannedUsers": False},
                    timeout=10
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    
                    if not data.get('data') or len(data['data']) == 0:
                        # Try fuzzy match - maybe OCR misread a character
                        similar = await self._fuzzy_search(username)
                        if similar:
                            data = {"data": [similar]}
                        else:
                            continue
                    
                    user_info = data['data'][0]
                    uid = user_info['id']
                    
                    # Get full profile
                    async with self.session.get(
                        f'https://users.roblox.com/v1/users/{uid}',
                        timeout=10
                    ) as resp:
                        if resp.status != 200:
                            continue
                        profile = await resp.json()
                    
                    # Calculate match score
                    match_score = user_data['confidence']
                    match_reasons = [f"OCR confidence: {user_data['confidence']:.2f}"]
                    
                    # Check display name match
                    profile_display = profile.get('displayName', '')
                    ocr_display = user_data.get('display')
                    
                    if ocr_display and profile_display:
                        # Calculate similarity
                        similarity = difflib.SequenceMatcher(
                            None, 
                            ocr_display.lower(), 
                            profile_display.lower()
                        ).ratio()
                        
                        if similarity > 0.8:
                            match_score += 0.15
                            match_reasons.append(f"Display match: {similarity:.0%}")
                        elif similarity > 0.5:
                            match_score += 0.05
                            match_reasons.append(f"Display partial: {similarity:.0%}")
                    
                    # Check if display appears in OCR text
                    if profile_display and profile_display.lower() in full_text_lower:
                        match_score += 0.1
                        match_reasons.append("Display in text")
                    
                    # Check if hint matches
                    if hint:
                        hint_clean = hint.lower().replace('@', '')
                        if username.lower() == hint_clean:
                            match_score = 1.0
                            match_reasons.append("Exact hint match")
                    
                    # Check username appears in text (not just @)
                    if f' {username.lower()}' in full_text_lower or f'{username.lower()} ' in full_text_lower:
                        match_score += 0.05
                        match_reasons.append("Username in text")
                    
                    verified.append({
                        'profile': profile,
                        'ocr_data': user_data,
                        'match_score': min(match_score, 1.0),
                        'match_reasons': match_reasons,
                        'verified': True
                    })
                    
            except Exception as e:
                print(f"Verification error for {username}: {e}")
                continue
        
        # Sort by match score
        verified.sort(key=lambda x: x['match_score'], reverse=True)
        return verified
    
    async def _fuzzy_search(self, username: str) -> Optional[Dict]:
        """Try to find similar username if exact match fails"""
        try:
            # Search Roblox users API
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=10',
                timeout=10
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                
                if not data.get('data'):
                    return None
                
                # Find best match
                best_match = None
                best_score = 0
                
                for user in data['data']:
                    similarity = difflib.SequenceMatcher(
                        None,
                        username.lower(),
                        user['name'].lower()
                    ).ratio()
                    
                    if similarity > best_score and similarity > 0.7:
                        best_score = similarity
                        best_match = user
                
                return best_match
                
        except Exception as e:
            print(f"Fuzzy search error: {e}")
            return None

class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        
        super().__init__(
            intents=intents,
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.whitelist = {str(OWNER_ID)}
        self.session = None
        self.downloader = None
        self.scanner = None
        self.whitelist_file = 'whitelist.json'
        self.webhook = WebhookLogger(WEBHOOK_URL)
    
    def save_whitelist(self):
        try:
            with open(self.whitelist_file, 'w') as f:
                json.dump({"users": list(self.whitelist)}, f)
            return True
        except Exception as e:
            print(f"❌ Failed to save whitelist: {e}")
            return False
    
    def is_whitelisted(self, user_id: str) -> bool:
        return user_id == str(OWNER_ID) or user_id in self.whitelist
    
    async def setup_hook(self):
        print("🔧 Setting up bot...")
        
        await self.webhook.setup()
        
        # Setup scanner
        self.scanner = UltimateRobloxScanner()
        await self.scanner.setup()
        
        # Load whitelist
        try:
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, 'r') as f:
                    data = json.load(f)
                    self.whitelist.update(str(u) for u in data.get('users', []))
                print(f"✅ Loaded {len(self.whitelist)} whitelisted users")
            else:
                self.save_whitelist()
                print("✅ Created default whitelist.json")
        except Exception as e:
            print(f"⚠️ Whitelist error: {e}")
        
        self.session = aiohttp.ClientSession()
        self.downloader = UniversalDownloader()
        
        # Register commands
        @self.tree.command(name="scan", description="🔍 ULTIMATE Roblox username scanner")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await interaction.response.defer()
            
            if not self.is_whitelisted(str(interaction.user.id)):
                await interaction.followup.send("⛔ You're not whitelisted!", ephemeral=True)
                return
            
            await self.do_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download any video to MP4")
        @app_commands.describe(url="Any video URL (YouTube, Medal, Streamable, etc.)")
        async def download(interaction: discord.Interaction, url: str):
            await interaction.response.defer()
            
            if not self.is_whitelisted(str(interaction.user.id)):
                await interaction.followup.send("⛔ You're not whitelisted!", ephemeral=True)
                return
            
            await self.do_download(interaction, url)
        
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelist (Owner only)")
        @app_commands.describe(user="User to add/remove (@mention or ID)")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await interaction.response.defer(ephemeral=True)
            
            if str(interaction.user.id) != str(OWNER_ID):
                await interaction.followup.send("⛔ Only owner!", ephemeral=True)
                return
            
            await self.do_whitelist(interaction, user)
        
        await self.sync_commands_with_retry()
        print("✅ Bot setup complete!")
    
    async def sync_commands_with_retry(self, max_retries=5):
        for attempt in range(max_retries):
            try:
                print(f"🔄 Syncing commands (attempt {attempt + 1}/{max_retries})...")
                synced = await self.tree.sync()
                print(f"✅ Synced {len(synced)} commands globally")
                self.commands_synced = True
                return True
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else (2 ** attempt)
                    print(f"⏳ Rate limited. Waiting {retry_after:.1f}s...")
                    await asyncio.sleep(retry_after)
                else:
                    print(f"❌ HTTP error syncing: {e}")
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                print(f"⚠️ Sync error: {e}")
                await asyncio.sleep(2 ** attempt)
        
        print("❌ Failed to sync commands")
        return False
    
    async def log_usage(self, interaction: discord.Interaction, command: str, details: str = ""):
        try:
            guild_name = interaction.guild.name if interaction.guild else "DM"
            channel_name = getattr(interaction.channel, 'name', 'DM') if hasattr(interaction.channel, 'name') else 'DM'
            
            embed = discord.Embed(
                title=f"📝 /{command} Used",
                description=f"**User:** {interaction.user.name} (`{interaction.user.id}`)\n**Location:** {guild_name} / {channel_name}\n**Details:** {details}",
                color=0x00D4AA,
                timestamp=datetime.now()
            )
            
            await self.webhook.log(embed=embed)
        except Exception as e:
            print(f"Log error: {e}")
    
    async def do_whitelist(self, interaction: discord.Interaction, user_input: str):
        target_id = re.sub(r'[<@!>]', '', user_input).strip()
        
        if not target_id.isdigit():
            await interaction.followup.send("❌ Invalid user ID!", ephemeral=True)
            return
        
        if target_id in self.whitelist:
            if target_id == str(OWNER_ID):
                await interaction.followup.send("⛔ Can't remove owner!", ephemeral=True)
                return
            
            self.whitelist.remove(target_id)
            self.save_whitelist()
            
            try:
                user = await self.fetch_user(int(target_id))
                name = f"@{user.name}" if user else target_id
            except:
                name = target_id
            
            await self.webhook.log(content=f"❌ Removed **{name}** from whitelist")
            await interaction.followup.send(f"❌ Removed {name}", ephemeral=True)
        else:
            self.whitelist.add(target_id)
            self.save_whitelist()
            
            try:
                user = await self.fetch_user(int(target_id))
                name = f"@{user.name}" if user else target_id
            except:
                name = target_id
            
            await self.webhook.log(content=f"✅ Added **{name}** to whitelist")
            await interaction.followup.send(f"✅ Added {name}", ephemeral=True)
    
    async def do_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        await self.log_usage(interaction, "scan", f"Hint: {hint}" if hint else "No hint")
        
        try:
            if image.size and image.size > 50 * 1024 * 1024:
                await interaction.followup.send("❌ Image too large (max 50MB)")
                return
            
            # Download image
            async with self.session.get(image.url, timeout=30) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"❌ Failed to download image: {resp.status}")
                    return
                img_data = await resp.read()
            
            if len(img_data) < 100:
                await interaction.followup.send("❌ Image too small")
                return
            
            # Send processing message
            processing_embed = discord.Embed(
                title="🔍 Scanning...",
                description="Running multi-engine OCR analysis...",
                color=0xFFA500
            )
            await interaction.followup.send(embed=processing_embed)
            
            # Run ultimate scan
            result = await self.scanner.scan_image(img_data, hint)
            
            if not result['success'] or not result['best_match']:
                # Show what OCR found for debugging
                ocr_preview = result.get('combined_text', 'No text detected')[:500]
                await interaction.edit_original_response(embed=discord.Embed(
                    title="❌ No User Found",
                    description=f"Could not verify any Roblox user.\n\n**OCR detected:**\n```{ocr_preview}...```",
                    color=0xFF0000
                ))
                return
            
            # Get best match
            best = result['best_match']
            profile = best['profile']
            score = best['match_score']
            reasons = best['match_reasons']
            
            # Determine color based on score and ban status
            if profile.get('isBanned'):
                color = 0x8B0000  # Dark red for banned
            elif score >= 0.9:
                color = 0x00FF00  # Green for high confidence
            elif score >= 0.7:
                color = 0xFFA500  # Orange for medium
            else:
                color = 0xFFFF00  # Yellow for low
            
            # Create embed
            embed = discord.Embed(
                title=f"{profile.get('displayName', profile['name'])}",
                description=f"@{profile['name']}\n**Match Confidence:** `{score:.0%}`",
                url=f'https://roblox.com/users/{profile["id"]}/profile',
                color=color,
                timestamp=datetime.now()
            )
            
            # Add match reasons
            embed.add_field(
                name="✅ Verification Details",
                value='\n'.join(f"• {r}" for r in reasons[:4]),
                inline=False
            )
            
            embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
            embed.add_field(name="📅 Created", value=str(profile.get('created', 'Unknown'))[:10], inline=True)
            embed.add_field(
                name="⚡ Status", 
                value="🔴 BANNED" if profile.get('isBanned') else "✅ Active", 
                inline=True
            )
            
            # Add description if available
            if profile.get('description'):
                desc = profile['description'][:250]
                if len(profile['description']) > 250:
                    desc += "..."
                embed.add_field(name="📝 About", value=desc, inline=False)
            
            # Add other candidates if found
            if len(result['users']) > 1:
                other_users = []
                for u in result['users'][1:4]:
                    name = u['profile']['name']
                    conf = u['match_score']
                    other_users.append(f"`@{name}` ({conf:.0%})")
                
                if other_users:
                    embed.add_field(
                        name="🔍 Other Matches",
                        value=' | '.join(other_users),
                        inline=False
                    )
            
            embed.set_image(url=image.url)
            embed.set_footer(text=f"TRUE OMEGA | {len(result['ocr_texts'])} OCR engines used")
            
            await interaction.edit_original_response(embed=embed)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏱️ Scan timed out. Try a smaller image.")
        except Exception as e:
            print(f"Scan error: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    async def do_download(self, interaction: discord.Interaction, url: str):
        await self.log_usage(interaction, "download", f"URL: {url[:50]}...")
        
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            await interaction.followup.send("❌ Invalid URL format")
            return
        
        try:
            result = await self.downloader.download(url, str(interaction.user.id))
            
            if not result['success']:
                error = result['error']
                if 'format' in error.lower():
                    await interaction.followup.send(f"❌ Format not supported: `{error[:100]}`")
                elif 'unavailable' in error.lower():
                    await interaction.followup.send("❌ Video unavailable (private/deleted)")
                else:
                    await interaction.followup.send(f"❌ Download failed: `{error[:150]}`")
                return
            
            size_mb = result['size'] / (1024 * 1024)
            
            if result['size'] > 25 * 1024 * 1024:
                await interaction.followup.send(f"⚠️ File too large ({size_mb:.1f}MB). Max 25MB.")
                self.downloader.cleanup(result['file_path'])
                return
            
            safe_title = re.sub(r'[^\w\-_.]', '_', result['title'][:50])
            filename = f"{safe_title}.mp4" if not safe_title.endswith('.mp4') else safe_title
            
            file = discord.File(result['file_path'], filename=filename)
            
            embed = discord.Embed(
                title="⚡ Download Complete",
                description=f"**{result['title'][:100]}**",
                color=0x00D4AA
            )
            embed.add_field(name="📦 Size", value=f"{size_mb:.1f}MB", inline=True)
            embed.add_field(name="📹 Format", value="MP4", inline=True)
            embed.set_footer(text="TRUE OMEGA | Universal Downloader")
            
            await interaction.followup.send(embed=embed, file=file)
            self.downloader.cleanup(result['file_path'])
            
        except Exception as e:
            print(f"Download error: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    async def on_ready(self):
        print(f"\n{'='*60}")
        print(f"✅ BOT ONLINE: {self.user}")
        print(f"   ID: {self.user.id}")
        print(f"   Servers: {len(self.guilds)}")
        print(f"   Whitelisted: {len(self.whitelist)} users")
        print(f"{'='*60}\n")

def main():
    while True:
        try:
            bot = Bot()
            bot.run(TOKEN, log_handler=None)
            print("\n⚠️ Bot stopped, restarting in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            traceback.print_exc()
            print("\nRestarting in 10s...")
            time.sleep(10)

if __name__ == "__main__":
    main()
