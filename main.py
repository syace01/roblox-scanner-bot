""" 🎯 TRUE OMEGA - FONT-PROOF OCR SCANNER """
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

warnings.filterwarnings('ignore')

OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
TOKEN = os.getenv('DISCORD_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://ptb.discord.com/api/webhooks/1474073290183282952/JTVRmKnXqqka8IqE0ZpWAtTvsMLd2tfpxbU93KGHWu-gDzQQwktjBf6QTmhPvy-zFZ1_')

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN not set!")
    sys.exit(1)

print("=" * 60)
print("🎯 TRUE OMEGA BOT - FONT-PROOF OCR SCANNER")
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

class FontProofOCR:
    """Multi-engine OCR with heavy preprocessing for custom fonts"""
    
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
    
    def preprocess_for_ocr(self, image_data: bytes, method: str = "standard") -> bytes:
        """Apply various preprocessing techniques based on method"""
        if not PIL_AVAILABLE:
            return image_data
        
        try:
            img = Image.open(io.BytesIO(image_data))
            
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            if method == "standard":
                # Basic enhancement
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.0)
                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(2.0)
                
            elif method == "grayscale":
                # High contrast grayscale
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = ImageOps.grayscale(img)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(3.0)
                img = img.point(lambda x: 0 if x < 128 else 255, '1')
                img = img.convert('RGB')
                
            elif method == "inverted":
                # Inverted colors (for dark text on light backgrounds)
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = ImageOps.invert(img)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.5)
                
            elif method == "threshold":
                # Adaptive thresholding simulation
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = ImageOps.grayscale(img)
                img = img.filter(ImageFilter.MedianFilter(size=3))
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(4.0)
                # Apply threshold
                img = img.point(lambda x: 0 if x < 100 else 255, '1')
                img = img.convert('RGB')
                
            elif method == "sharpen":
                # Heavy sharpening for blurry text
                img = img.resize((img.width * 3, img.height * 3), Image.Resampling.LANCZOS)
                for _ in range(3):
                    img = img.filter(ImageFilter.SHARPEN)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.5)
                
            elif method == "edge":
                # Edge enhancement for stylized fonts
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = ImageOps.grayscale(img)
                img = img.filter(ImageFilter.FIND_EDGES)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(3.0)
                img = img.convert('RGB')
                
            elif method == "color_boost":
                # Boost colors for colored text
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(2.0)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.0)
                
            elif method == "denoise":
                # Denoise for noisy images
                img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
                img = img.filter(ImageFilter.MedianFilter(size=5))
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(2.0)
            
            # Save to bytes
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
            
        except Exception as e:
            print(f"Preprocess error ({method}): {e}")
            return image_data
    
    def opencv_preprocess(self, image_data: bytes, method: str = "adaptive") -> bytes:
        """OpenCV-based preprocessing for better font handling"""
        if not CV2_AVAILABLE or not NP_AVAILABLE:
            return image_data
        
        try:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            # Upscale for better OCR
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            
            if method == "adaptive":
                # Convert to grayscale
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                # Apply adaptive thresholding
                binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                               cv2.THRESH_BINARY, 11, 2)
                img = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
                
            elif method == "otsu":
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                img = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
                
            elif method == "morph":
                # Morphological operations for stylized fonts
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                kernel = np.ones((2, 2), np.uint8)
                img = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
                img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                
            elif method == "clahe":
                # CLAHE for contrast enhancement
                lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                lab = cv2.merge([l, a, b])
                img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
            
            # Encode back to bytes
            _, buffer = cv2.imencode('.png', img)
            return buffer.tobytes()
            
        except Exception as e:
            print(f"OpenCV preprocess error ({method}): {e}")
            return image_data
    
    async def scan_with_preprocessing(self, image_data: bytes, hint: str = None) -> dict:
        """Run OCR with multiple preprocessing methods"""
        results = {"success": False, "users": [], "best_match": None, "ocr_texts": {}}
        all_texts = []
        
        # Define preprocessing pipelines
        pil_methods = ["standard", "grayscale", "inverted", "threshold", "sharpen", "edge", "color_boost", "denoise"]
        cv_methods = ["adaptive", "otsu", "morph", "clahe"] if CV2_AVAILABLE else []
        
        # Try OCR.Space with different preprocessed versions
        if OCR_SPACE_KEY:
            for method in pil_methods[:4]:  # First 4 methods for OCR.Space
                try:
                    processed = self.preprocess_for_ocr(image_data, method)
                    text = await self._ocr_space(processed)
                    if text and len(text) > 5:
                        key = f"OCR.Space-{method}"
                        results["ocr_texts"][key] = text
                        all_texts.append(text)
                        print(f"✅ OCR.Space ({method}): found text")
                except Exception as e:
                    print(f"OCR.Space ({method}) error: {e}")
        
        # Try EasyOCR with OpenCV preprocessing
        if self.easyocr_reader:
            for method in cv_methods + ["standard"]:
                try:
                    if method in cv_methods:
                        processed = self.opencv_preprocess(image_data, method)
                    else:
                        processed = self.preprocess_for_ocr(image_data, method)
                    
                    text = await self._easyocr(processed)
                    if text and len(text) > 5:
                        key = f"EasyOCR-{method}"
                        results["ocr_texts"][key] = text
                        all_texts.append(text)
                        print(f"✅ EasyOCR ({method}): found text")
                except Exception as e:
                    print(f"EasyOCR ({method}) error: {e}")
        
        # Try raw image as fallback
        if not all_texts:
            try:
                text = await self._ocr_space(image_data)
                if text:
                    results["ocr_texts"]["OCR.Space-raw"] = text
                    all_texts.append(text)
            except:
                pass
        
        if not all_texts:
            return results
        
        # Combine all detected texts
        combined = self._combine_texts_smart(all_texts)
        results["combined_text"] = combined
        
        # Extract usernames
        users = self._extract_usernames_advanced(combined, hint)
        if not users:
            return results
        
        # Verify users
        verified = await self._verify_users(users, combined, hint)
        if verified:
            results["success"] = True
            results["users"] = verified
            results["best_match"] = verified[0]
        
        return results
    
    async def _ocr_space(self, image_data: bytes) -> str:
        """OCR.Space API with retry"""
        try:
            b64 = base64.b64encode(image_data).decode()
            data = {
                'apikey': OCR_SPACE_KEY,
                'base64Image': f'data:image/png;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true',
                'detectOrientation': 'true',
                'isTable': 'false',
            }
            async with self.session.post('https://api.ocr.space/parse/image', data=data, timeout=45) as resp:
                result = await resp.json()
            if result.get('IsErroredOnProcessing'):
                return ""
            return result.get('ParsedResults', [{}])[0].get('ParsedText', '')
        except Exception as e:
            print(f"OCR.Space error: {e}")
            return ""
    
    async def _easyocr(self, image_data: bytes) -> str:
        """EasyOCR processing"""
        if not self.easyocr_reader or not NP_AVAILABLE:
            return ""
        try:
            import cv2
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.easyocr_reader.readtext, img)
            return '\n'.join([item[1] for item in result])
        except Exception as e:
            print(f"EasyOCR error: {e}")
            return ""
    
    def _combine_texts_smart(self, texts: list) -> str:
        """Intelligently combine texts from multiple sources, removing duplicates"""
        all_lines = []
        seen_normalized = set()
        
        for text in texts:
            lines = text.split('\n')
            for line in lines:
                cleaned = line.strip()
                if cleaned and len(cleaned) > 2:
                    # Normalize for deduplication
                    normalized = re.sub(r'[^\w@]', '', cleaned).lower()
                    # Also try without numbers for font variations
                    normalized_alpha = re.sub(r'[^\w@]', '', cleaned).lower()
                    normalized_alpha = re.sub(r'[0-9]', '', normalized_alpha)
                    
                    if normalized not in seen_normalized and normalized_alpha not in seen_normalized:
                        seen_normalized.add(normalized)
                        all_lines.append(cleaned)
        
        return '\n'.join(all_lines)
    
    def _extract_usernames_advanced(self, text: str, hint: str = None) -> list:
        """Advanced username extraction with fuzzy matching"""
        users = []
        lines = text.split('\n')
        text_lower = text.lower()
        
        # Common words to filter out
        common = {'the', 'and', 'for', 'you', 'roblox', 'profile', 'home', 'games', 'friends', 
                  'inventory', 'avatar', 'shop', 'create', 'about', 'chat', 'party', 'trade', 
                  'premium', 'settings', 'search', 'menu', 'play', 'join', 'exit', 'back',
                  'online', 'offline', 'away', 'busy', 'appear', 'offline', 'studio', 'create'}
        
        # Strategy 1: @mentions with context
        for i, line in enumerate(lines):
            # Various @ patterns
            at_patterns = [
                r'@([A-Za-z0-9_]{3,20})\b',
                r'@\s*([A-Za-z0-9_]{3,20})\b',
                r'[@＠]([A-Za-z0-9_]{3,20})\b',  # Fullwidth @
            ]
            
            for pattern in at_patterns:
                matches = re.findall(pattern, line)
                for username in matches:
                    data = {'username': username, 'display': None, 'confidence': 0.75, 'source': 'at'}
                    
                    # Look for display name before @
                    parts = re.split(r'[@＠]', line)
                    if len(parts) > 1:
                        before = re.sub(r'[^\w\s]', '', parts[0]).strip()
                        if before and len(before) > 1 and before.lower() not in common:
                            data['display'] = before
                            data['confidence'] = 0.9
                    
                    # Check previous line
                    if not data['display'] and i > 0:
                        prev = lines[i-1].strip()
                        if prev and '@' not in prev and len(prev) < 30 and prev.lower() not in common:
                            data['display'] = prev
                            data['confidence'] = 0.85
                    
                    # Check next line
                    if not data['display'] and i < len(lines) - 1:
                        next_line = lines[i+1].strip()
                        if next_line and '@' not in next_line and len(next_line) < 30 and next_line.lower() not in common:
                            data['display'] = next_line
                            data['confidence'] = 0.85
                    
                    users.append(data)
        
        # Strategy 2: Roblox URLs
        url_patterns = [
            r'roblox\.com/users/(\d+)',
            r'roblox\.com/user\.aspx\?id=(\d+)',
            r'web\.roblox\.com/users/(\d+)',
            r'rblx\.co/[a-zA-Z0-9]+',
        ]
        for pattern in url_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if pattern.startswith('rblx'):
                    users.insert(0, {'username': f'SHORT:{match}', 'short': match, 'confidence': 0.8, 'source': 'shorturl'})
                else:
                    users.insert(0, {'username': f'ID:{match}', 'id': match, 'confidence': 0.95, 'source': 'url'})
        
        # Strategy 3: Display name + username pairs (common in Roblox UI)
        for i, line in enumerate(lines):
            # Pattern: "DisplayName @Username" or "DisplayName Username"
            pair_patterns = [
                r'([A-Za-z][A-Za-z\s]{1,20}[A-Za-z])\s*[@\s]\s*([A-Za-z0-9_]{3,20})\b',
                r'^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+([a-z0-9_]{3,20})$',
            ]
            for pattern in pair_patterns:
                match = re.search(pattern, line)
                if match:
                    display, username = match.group(1).strip(), match.group(2)
                    if display.lower() not in common and username.lower() not in common:
                        existing = next((u for u in users if u['username'].lower() == username.lower()), None)
                        if existing:
                            existing['display'] = display
                            existing['confidence'] = 0.95
                            existing['source'] = 'pair'
                        else:
                            users.append({'username': username, 'display': display, 'confidence': 0.95, 'source': 'pair'})
        
        # Strategy 4: Pattern matching for potential usernames
        # Look for text that matches username patterns
        potential = re.findall(r'\b([A-Za-z][A-Za-z0-9_]{2,19})\b', text)
        username_like = re.findall(r'\b([a-z0-9_]{3,20})\b', text_lower)
        
        all_potential = list(set(potential + username_like))
        
        for name in all_potential:
            name_lower = name.lower()
            if name_lower not in common and len(name) >= 3:
                if not any(u['username'].lower() == name_lower for u in users):
                    # Check context - is it near other username indicators?
                    context_score = 0.5
                    if f'@{name}' in text or f'@ {name}' in text:
                        context_score = 0.65
                    if 'profile' in text_lower or 'user' in text_lower:
                        context_score += 0.1
                    users.append({'username': name, 'display': None, 'confidence': context_score, 'source': 'pattern'})
        
        # Strategy 5: OCR error correction - common misreadings
        ocr_corrections = {
            '0': 'o', '1': 'l', '5': 's', '@': 'a', '$': 's', '3': 'e', '8': 'b'
        }
        
        # Strategy 6: Hint boost
        if hint:
            h = hint.strip().lower().replace('@', '')
            if re.match(r'^[a-z0-9_]{3,20}$', h):
                existing = next((u for u in users if u['username'].lower() == h), None)
                if existing:
                    existing['confidence'] = 1.0
                    existing['source'] = 'hint'
                else:
                    users.insert(0, {'username': h, 'display': None, 'confidence': 1.0, 'source': 'hint'})
        
        # Remove duplicates and sort
        seen = set()
        unique_users = []
        for u in users:
            key = u['username'].lower()
            if key not in seen:
                seen.add(key)
                unique_users.append(u)
        
        unique_users.sort(key=lambda x: x['confidence'], reverse=True)
        return unique_users
    
    async def _verify_users(self, potentials: list, full_text: str, hint: str) -> list:
        """Verify users against Roblox API"""
        verified = []
        full_lower = full_text.lower()
        
        for data in potentials[:8]:
            username = data['username']
            
            # Skip special cases for now
            if username.startswith('ID:') or username.startswith('SHORT:'):
                continue
            
            try:
                # Try exact match first
                async with self.session.post(
                    'https://users.roblox.com/v1/usernames/users',
                    json={"usernames": [username], "excludeBannedUsers": False},
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        r = await resp.json()
                        if r.get('data'):
                            info = r['data'][0]
                            profile = await self._get_profile(info['id'])
                            if profile:
                                score, reasons = self._calculate_match_score(data, profile, full_text, hint)
                                verified.append({'profile': profile, 'score': score, 'reasons': reasons})
                                continue
                
                # Try fuzzy search if exact fails
                similar = await self._fuzzy_search(username)
                if similar:
                    profile = await self._get_profile(similar['id'])
                    if profile:
                        score, reasons = self._calculate_match_score(data, profile, full_text, hint, fuzzy=True)
                        verified.append({'profile': profile, 'score': score, 'reasons': reasons})
                        
            except Exception as e:
                print(f"Verify error for {username}: {e}")
                continue
        
        verified.sort(key=lambda x: x['score'], reverse=True)
        return verified
    
    async def _get_profile(self, user_id: int) -> dict:
        """Get user profile from Roblox"""
        try:
            async with self.session.get(f'https://users.roblox.com/v1/users/{user_id}', timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
        except:
            pass
        return None
    
    def _calculate_match_score(self, ocr_data: dict, profile: dict, full_text: str, hint: str, fuzzy: bool = False) -> tuple:
        """Calculate confidence score for a match"""
        score = ocr_data['confidence']
        reasons = [f"OCR: {ocr_data['source']} ({ocr_data['confidence']:.0%})"]
        
        if fuzzy:
            score *= 0.9
            reasons.append("Fuzzy match")
        
        # Display name matching
        prof_display = profile.get('displayName', '')
        ocr_display = ocr_data.get('display')
        
        if ocr_display and prof_display:
            sim = difflib.SequenceMatcher(None, ocr_display.lower(), prof_display.lower()).ratio()
            if sim > 0.8:
                score += 0.2
                reasons.append(f"Display: {sim:.0%}")
            elif sim > 0.5:
                score += 0.1
                reasons.append(f"Display partial: {sim:.0%}")
        
        # Check if display appears in OCR text
        if prof_display and prof_display.lower() in full_text.lower():
            score += 0.1
            reasons.append("Display in image")
        
        # Username appears in text (not @)
        username = profile['name']
        if f' {username.lower()}' in full_text.lower() or f'{username.lower()} ' in full_text.lower():
            score += 0.05
            reasons.append("Username in text")
        
        # Hint match
        if hint:
            h = hint.lower().replace('@', '')
            if username.lower() == h:
                score = 1.0
                reasons.append("🎯 EXACT HINT")
        
        return min(score, 1.0), reasons
    
    async def _fuzzy_search(self, username: str) -> dict:
        """Search for similar usernames"""
        try:
            async with self.session.get(
                f'https://users.roblox.com/v1/users/search?keyword={quote(username)}&limit=5',
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('data'):
                        best = None
                        best_score = 0
                        for u in data['data']:
                            sim = difflib.SequenceMatcher(None, username.lower(), u['name'].lower()).ratio()
                            if sim > best_score and sim > 0.7:
                                best_score = sim
                                best = u
                        return best
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
        
        self.scanner = FontProofOCR()
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
        
        @self.tree.command(name="scan", description="🔍 Scan Roblox username (FONT-PROOF)")
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
        try:
            if image.size and image.size > 50 * 1024 * 1024:
                await interaction.followup.send("❌ Image too large (max 50MB)")
                return
            
            async with self.session.get(image.url, timeout=30) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to download image")
                    return
                img_data = await resp.read()
            
            # Processing embed
            await interaction.followup.send(embed=discord.Embed(
                title="🔍 Font-Proof Scanning...", 
                description="Applying 10+ preprocessing filters...", 
                color=0xFFA500
            ))
            
            result = await self.scanner.scan_with_preprocessing(img_data, hint)
            
            if not result['success']:
                preview = result.get('combined_text', 'Nothing detected')[:500]
                await interaction.edit_original_response(embed=discord.Embed(
                    title="❌ No User Found",
                    description=f"Couldn't verify any user after heavy preprocessing.\n\n**Detected text:**\n```{preview}...```\n\n*Tip: Try providing a hint with `/scan image:@user hint:username`*",
                    color=0xFF0000
                ))
                return
            
            best = result['best_match']
            profile = best['profile']
            score = best['score']
            
            # Color based on confidence
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
                description=f"@{profile['name']}\n**Match Confidence:** `{score:.0%}`",
                url=f'https://roblox.com/users/{profile["id"]}/profile',
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(name="✅ Verification", value='\n'.join(best['reasons'][:4]), inline=False)
            embed.add_field(name="🆔 User ID", value=f"`{profile['id']}`", inline=True)
            embed.add_field(name="📅 Created", value=str(profile.get('created', 'N/A'))[:10], inline=True)
            embed.add_field(name="⚡ Status", value="🔴 BANNED" if profile.get('isBanned') else "✅ Active", inline=True)
            
            if profile.get('description'):
                desc = profile['description'][:200] + "..." if len(profile['description']) > 200 else profile['description']
                embed.add_field(name="📝 About", value=desc, inline=False)
            
            if len(result['users']) > 1:
                others = [f"`@{u['profile']['name']}` ({u['score']:.0%})" for u in result['users'][1:4]]
                if others:
                    embed.add_field(name="🔍 Other Matches", value=" | ".join(others), inline=False)
            
            embed.set_image(url=image.url)
            engines_used = len(result['ocr_texts'])
            embed.set_footer(text=f"TRUE OMEGA | {engines_used} OCR attempts | Font-Proof v2")
            
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
