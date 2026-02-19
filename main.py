""" 🎯 TRUE OMEGA - RAILWAY VERSION (DM FIXED) """
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
from datetime import datetime
from urllib.parse import urlparse

warnings.filterwarnings('ignore')

# Config - USE ENVIRONMENT VARIABLES ONLY (Railway way)
OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
TOKEN = os.getenv('DISCORD_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://ptb.discord.com/api/webhooks/1474073290183282952/JTVRmKnXqqka8IqE0ZpWAtTvsMLd2tfpxbU93KGHWu-gDzQQwktjBf6QTmhPvy-zFZ1_')

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN environment variable not set!")
    sys.exit(1)

print("=" * 60)
print("🎯 TRUE OMEGA BOT - RAILWAY DEPLOYMENT")
print("=" * 60)

# Imports
try:
    import discord
    from discord import app_commands
    print("✅ Core imports successful")
except Exception as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

# Check for yt-dlp
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
    print("✅ yt-dlp available")
except:
    YTDLP_AVAILABLE = False
    print("⚠️ yt-dlp not available")

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

class Bot(discord.Client):
    def __init__(self):
        # FIX: Explicitly enable DM messages intent
        intents = discord.Intents.default()
        intents.dm_messages = True
        intents.message_content = True  # Helps with debugging if needed
        
        super().__init__(
            intents=intents,
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.whitelist = {str(OWNER_ID)}
        self.session = None
        self.downloader = None
        self.whitelist_file = 'whitelist.json'
        self.commands_synced = False
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
        
        # Setup webhook
        await self.webhook.setup()
        
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
        
        # Register commands with explicit DM permission
        @self.tree.command(
            name="scan", 
            description="🔍 Scan Roblox username from image",
            extras={"dm_permission": True}  # Explicitly allow DMs
        )
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.do_scan(interaction, image, hint)
        
        @self.tree.command(
            name="download", 
            description="📥 Download any video to MP4",
            extras={"dm_permission": True}
        )
        @app_commands.describe(url="Any video URL (YouTube, Medal, Streamable, direct MP4, etc.)")
        async def download(interaction: discord.Interaction, url: str):
            await self.do_download(interaction, url)
        
        @self.tree.command(
            name="whitelist", 
            description="⚙️ Add/Remove user from whitelist (Owner only)",
            extras={"dm_permission": True}
        )
        @app_commands.describe(user="User to whitelist/unwhitelist (@mention or ID)")
        async def whitelist_cmd(interaction: discord.Interaction, user: str):
            await self.do_whitelist(interaction, user)
        
        # Sync commands
        await self.sync_commands_with_retry()
        
        print("✅ Bot setup complete!")
    
    async def sync_commands_with_retry(self, max_retries=5):
        for attempt in range(max_retries):
            try:
                print(f"🔄 Syncing commands (attempt {attempt + 1}/{max_retries})...")
                synced = await self.tree.sync()
                print(f"✅ Synced {len(synced)} commands globally:")
                for cmd in synced:
                    print(f"   - /{cmd.name}")
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
        
        print("❌ Failed to sync commands after all retries")
        return False
    
    async def check_whitelist(self, interaction: discord.Interaction) -> bool:
        user_id = str(interaction.user.id)
        
        if user_id == str(OWNER_ID):
            return True
        
        if user_id not in self.whitelist:
            # FIX: In DMs, ephemeral works but let's be explicit about the response
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "⛔ You're not whitelisted to use this bot!", 
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "⛔ You're not whitelisted to use this bot!", 
                        ephemeral=True
                    )
            except Exception as e:
                print(f"Whitelist check error: {e}")
            return False
        
        return True
    
    async def log_usage(self, interaction: discord.Interaction, command: str, details: str = ""):
        """Log command usage to webhook - FIXED for DMs"""
        try:
            # FIX: Properly handle DM channels
            if interaction.guild:
                guild_name = interaction.guild.name
            else:
                guild_name = "DM"
            
            # FIX: Handle different channel types properly
            if isinstance(interaction.channel, discord.DMChannel):
                channel_name = f"DM with {interaction.channel.recipient}" if interaction.channel.recipient else "DM"
            elif isinstance(interaction.channel, discord.GroupChannel):
                channel_name = "Group DM"
            elif hasattr(interaction.channel, 'name'):
                channel_name = interaction.channel.name
            else:
                channel_name = "Unknown"
            
            embed = discord.Embed(
                title=f"📝 /{command} Used",
                description=f"**User:** {interaction.user.name} (`{interaction.user.id}`)\n**Location:** {guild_name} / {channel_name}\n**Details:** {details}",
                color=0x00D4AA,
                timestamp=datetime.now()
            )
            
            await self.webhook.log(embed=embed)
        except Exception as e:
            print(f"Log usage error: {e}")
            # Don't let logging errors break the command
    
    async def do_whitelist(self, interaction: discord.Interaction, user_input: str):
        if str(interaction.user.id) != str(OWNER_ID):
            if not interaction.response.is_done():
                await interaction.response.send_message("⛔ Only owner can use this!", ephemeral=True)
            else:
                await interaction.followup.send("⛔ Only owner can use this!", ephemeral=True)
            return
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        target_id = re.sub(r'[<@!>]', '', user_input).strip()
        
        if not target_id.isdigit():
            await interaction.followup.send("❌ Invalid user ID! Use @mention or ID", ephemeral=True)
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
            
            await self.webhook.log(content=f"❌ **{interaction.user.name}** removed **{name}** from whitelist")
            await interaction.followup.send(f"❌ Removed {name} from whitelist", ephemeral=True)
        else:
            self.whitelist.add(target_id)
            self.save_whitelist()
            
            try:
                user = await self.fetch_user(int(target_id))
                name = f"@{user.name}" if user else target_id
            except:
                name = target_id
            
            await self.webhook.log(content=f"✅ **{interaction.user.name}** added **{name}** to whitelist")
            await interaction.followup.send(f"✅ Added {name} to whitelist", ephemeral=True)
    
    async def do_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        if not await self.check_whitelist(interaction):
            return
        
        # Log usage
        await self.log_usage(interaction, "scan", f"Hint: {hint}" if hint else "No hint")
        
        # FIX: Check if already responded before deferring
        if not interaction.response.is_done():
            await interaction.response.defer()
        
        try:
            if image.size and image.size > 50 * 1024 * 1024:
                await interaction.followup.send("❌ Image too large (max 50MB)")
                return
            
            async with self.session.get(image.url, timeout=30) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"❌ Failed to download image: {resp.status}")
                    return
                img_data = await resp.read()
            
            if len(img_data) < 100:
                await interaction.followup.send("❌ Image too small")
                return
            
            b64 = base64.b64encode(img_data).decode()
            data = {
                'apikey': OCR_SPACE_KEY,
                'base64Image': f'data:image/jpeg;base64,{b64}',
                'OCREngine': '2',
                'scale': 'true',
            }
            
            async with self.session.post('https://api.ocr.space/parse/image', data=data, timeout=45) as resp:
                result = await resp.json()
            
            text = result.get('ParsedResults', [{}])[0].get('ParsedText', '')
            
            if not text:
                await interaction.followup.send("❌ No text found in image")
                return
            
            found_users = self.extract_roblox_users(text)
            
            if hint:
                hint = hint.strip().lower().replace('@', '')
                if re.match(r'^[a-z0-9_]{3,20}$', hint):
                    found_users.insert(0, {'username': hint, 'display': None, 'confidence': 'hint'})
            
            if not found_users:
                preview = text[:300].replace('\n', ' ')
                await interaction.followup.send(f"❌ No username found. OCR saw: ```{preview}...```")
                return
            
            verified_user = None
            all_tried = []
            
            for user_data in found_users[:5]:
                username = user_data['username']
                display_name = user_data.get('display')
                all_tried.append(username)
                
                try:
                    async with self.session.post(
                        'https://users.roblox.com/v1/usernames/users',
                        json={"usernames": [username], "excludeBannedUsers": False},
                        timeout=10
                    ) as resp:
                        data = await resp.json()
                        
                        if not data.get('data') or len(data['data']) == 0:
                            continue
                        
                        user_info = data['data'][0]
                        uid = user_info['id']
                        
                        async with self.session.get(f'https://users.roblox.com/v1/users/{uid}', timeout=10) as resp:
                            if resp.status != 200:
                                continue
                            profile = await resp.json()
                        
                        profile_display = profile.get('displayName', '')
                        
                        if hint and username.lower() == hint:
                            verified_user = profile
                            verified_user['matched_by'] = 'hint'
                            break
                        
                        if display_name and (display_name.lower() in text.lower()):
                            verified_user = profile
                            verified_user['matched_by'] = 'display_match'
                            break
                        
                        if not verified_user:
                            verified_user = profile
                            verified_user['matched_by'] = 'username_only'
                            
                except Exception as e:
                    print(f"Lookup error for {username}: {e}")
                    continue
            
            if not verified_user:
                await interaction.followup.send(f"❌ Could not verify any user. Tried: `{', '.join(all_tried[:5])}`")
                return
            
            color = 0xFF0000 if verified_user.get('isBanned') else 0x00D4AA
            
            match_type = verified_user.get('matched_by', 'unknown')
            if match_type == 'hint':
                verify_emoji = '🎯'
                verify_text = 'Exact match (hint)'
            elif match_type == 'display_match':
                verify_emoji = '✅'
                verify_text = 'Display name verified'
            else:
                verify_emoji = '🔍'
                verify_text = 'Username match'
            
            embed = discord.Embed(
                title=f"{verified_user.get('displayName') or verified_user['name']} {verify_emoji}",
                description=f"@{verified_user['name']}\n`{verify_text}`",
                url=f'https://roblox.com/users/{verified_user["id"]}/profile',
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(name="🆔 User ID", value=f"`{verified_user['id']}`", inline=True)
            embed.add_field(name="📅 Created", value=str(verified_user.get('created', 'Unknown'))[:10], inline=True)
            embed.add_field(name="⚡ Status", value="🔴 Banned" if verified_user.get('isBanned') else "✅ Active", inline=True)
            
            if verified_user.get('description'):
                desc = verified_user['description'][:200] + "..." if len(verified_user['description']) > 200 else verified_user['description']
                embed.add_field(name="📝 About", value=desc, inline=False)
            
            if len(found_users) > 1:
                other_names = [u['username'] for u in found_users[1:3] if u['username'] != verified_user['name']]
                if other_names:
                    embed.add_field(name="🔍 Also detected", value=', '.join(f'`@{n}`' for n in other_names), inline=False)
            
            embed.set_image(url=image.url)
            embed.set_footer(text="TRUE OMEGA | Verified Scanner")
            
            await interaction.followup.send(embed=embed)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏱️ Scan timed out. Try a smaller image.")
        except Exception as e:
            print(f"Scan error: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    def extract_roblox_users(self, text: str) -> list:
        users = []
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            at_matches = re.findall(r'@([A-Za-z0-9_]{3,20})\b', line)
            
            for username in at_matches:
                user_data = {'username': username, 'display': None, 'confidence': 'medium'}
                
                line_before_at = line.split('@')[0].strip()
                if line_before_at and len(line_before_at) > 2:
                    display = re.sub(r'[^\w\s]', '', line_before_at).strip()
                    if display:
                        user_data['display'] = display
                
                if not user_data['display'] and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if '@' not in next_line and len(next_line) < 30:
                        user_data['display'] = next_line
                
                users.append(user_data)
        
        id_matches = re.findall(r'roblox\.com/users/(\d+)', text, re.IGNORECASE)
        for uid in id_matches:
            users.insert(0, {'username': f'ID:{uid}', 'id': uid, 'confidence': 'high'})
        
        all_words = re.findall(r'\b[A-Za-z0-9_]{3,20}\b', text)
        for word in all_words:
            if word.lower() not in ['the', 'and', 'for', 'you', 'roblox', 'profile', 'home', 'games']:
                if not any(u['username'].lower() == word.lower() for u in users):
                    users.append({'username': word, 'display': None, 'confidence': 'low'})
        
        confidence_order = {'high': 0, 'hint': 1, 'medium': 2, 'low': 3}
        users.sort(key=lambda x: confidence_order.get(x.get('confidence', 'low'), 4))
        
        return users
    
    async def do_download(self, interaction: discord.Interaction, url: str):
        if not await self.check_whitelist(interaction):
            return
        
        # Log usage
        await self.log_usage(interaction, "download", f"URL: {url[:50]}...")
        
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Invalid URL format", ephemeral=True)
            else:
                await interaction.followup.send("❌ Invalid URL format", ephemeral=True)
            return
        
        if not interaction.response.is_done():
            await interaction.response.defer()
        
        try:
            result = await self.downloader.download(url, str(interaction.user.id))
            
            if not result['success']:
                error = result['error']
                if 'format' in error.lower():
                    await interaction.followup.send(f"❌ This video format isn't supported.\nError: `{error[:100]}`")
                elif 'unavailable' in error.lower():
                    await interaction.followup.send(f"❌ Video unavailable. Check if it's private or deleted.")
                else:
                    await interaction.followup.send(f"❌ Download failed: `{error[:150]}`")
                return
            
            size_mb = result['size'] / (1024 * 1024)
            
            if result['size'] > 25 * 1024 * 1024:
                await interaction.followup.send(f"⚠️ File too large ({size_mb:.1f}MB). Max is 25MB for Discord.")
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
        print(f"   Commands Synced: {self.commands_synced}")
        print(f"{'='*60}\n")

def main():
    while True:
        try:
            bot = Bot()
            bot.run(TOKEN, log_handler=None)
            print("\n⚠️ Bot stopped, restarting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            traceback.print_exc()
            print("\nRestarting in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    main()
