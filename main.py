""" 🎯 TRUE OMEGA - RAILWAY VERSION """
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
from datetime import datetime

warnings.filterwarnings('ignore')

# Config - USE ENVIRONMENT VARIABLES (Railway way)
OWNER_ID = os.getenv('OWNER_ID', '1382137288502542339')
OCR_SPACE_KEY = os.getenv('OCR_SPACE_KEY', '')
TOKEN = os.getenv('DISCORD_TOKEN')

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
    import aiohttp
    from PIL import Image
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

class VideoDownloader:
    def __init__(self):
        self.path = tempfile.mkdtemp()
    
    async def download(self, url: str, user_id: str) -> dict:
        if not YTDLP_AVAILABLE:
            return {"success": False, "error": "yt-dlp not installed"}
        
        dl_id = f"{user_id}_{int(time.time())}"
        output = os.path.join(self.path, f"{dl_id}.%(ext)s")
        
        try:
            loop = asyncio.get_event_loop()
            
            def dl():
                # FIXED: Better format selection for Medal.tv and others
                ydl_opts = {
                    'format': 'best[filesize<25M]/bestvideo[filesize<25M]+bestaudio[filesize<25M]/best[filesize<25M]/worst',
                    'outtmpl': output,
                    'quiet': True,
                    'no_warnings': True,
                    'max_filesize': 25 * 1024 * 1024,
                    'merge_output_format': 'mp4',
                    'postprocessors': [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    }],
                    # Add headers to avoid blocking
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0'
                    }
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return info
            
            result = await asyncio.wait_for(loop.run_in_executor(None, dl), timeout=120)
            
            # Find the downloaded file
            files = [f for f in os.listdir(self.path) if f.startswith(dl_id)]
            if files:
                actual = os.path.join(self.path, files[0])
                return {
                    "success": True,
                    "file_path": actual,
                    "title": result.get('title', 'video') if isinstance(result, dict) else 'video',
                    "size": os.path.getsize(actual),
                }
            else:
                return {"success": False, "error": "File not found after download"}
                
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}
    
    def cleanup(self, file_path: str):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

class Bot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.all(),
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox | /scan")
        )
        self.tree = app_commands.CommandTree(self)
        self.whitelist = {str(OWNER_ID)}
        self.session = None
        self.downloader = None
        self.whitelist_file = 'whitelist.json'
    
    def save_whitelist(self):
        """Save whitelist to file"""
        try:
            with open(self.whitelist_file, 'w') as f:
                json.dump({"users": list(self.whitelist)}, f)
            return True
        except Exception as e:
            print(f"❌ Failed to save whitelist: {e}")
            return False
    
    async def setup_hook(self):
        print("🔧 Setting up bot...")
        
        # Load whitelist from file
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
        self.downloader = VideoDownloader()
        
        # Register commands
        @self.tree.command(name="scan", description="🔍 Scan Roblox username from image")
        @app_commands.describe(image="Screenshot to scan", hint="Optional username hint")
        async def scan(interaction: discord.Interaction, image: discord.Attachment, hint: str = None):
            await self.do_scan(interaction, image, hint)
        
        @self.tree.command(name="download", description="📥 Download video from URL")
        @app_commands.describe(url="Video URL to download")
        async def download(interaction: discord.Interaction, url: str):
            await self.do_download(interaction, url)
        
        # NEW: Whitelist command group
        @self.tree.command(name="whitelist", description="⚙️ Manage whitelisted users (Owner only)")
        @app_commands.describe(action="Action to perform", user="User to add/remove (ID or mention)")
        @app_commands.choices(action=[
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
            app_commands.Choice(name="list", value="list"),
            app_commands.Choice(name="check", value="check"),
        ])
        async def whitelist_cmd(interaction: discord.Interaction, action: app_commands.Choice[str], user: str = None):
            await self.do_whitelist(interaction, action.value, user)
        
        # Sync commands globally
        try:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} commands globally")
        except Exception as e:
            print(f"⚠️ Command sync error: {e}")
        
        print("✅ Bot setup complete!")
    
    async def do_whitelist(self, interaction: discord.Interaction, action: str, user_input: str = None):
        """Handle whitelist management"""
        user_id = str(interaction.user.id)
        
        # Only owner can manage whitelist
        if user_id != str(OWNER_ID):
            await interaction.response.send_message("⛔ Only the bot owner can manage whitelist!", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        if action == "list":
            if not self.whitelist:
                await interaction.followup.send("📋 Whitelist is empty!", ephemeral=True)
                return
            
            users_list = []
            for uid in sorted(self.whitelist):
                try:
                    user = await self.fetch_user(int(uid))
                    name = f"{user.name}#{user.discriminator}" if user else f"Unknown ({uid})"
                    users_list.append(f"• `{uid}` - {name}")
                except:
                    users_list.append(f"• `{uid}` - Unknown")
            
            embed = discord.Embed(
                title="📋 Whitelisted Users",
                description="\n".join(users_list) or "None",
                color=0x00D4AA
            )
            embed.set_footer(text=f"Total: {len(self.whitelist)} users")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        if action == "check":
            if not user_input:
                await interaction.followup.send("❌ Please provide a user ID to check!", ephemeral=True)
                return
            
            # Extract ID from mention or use as-is
            check_id = re.sub(r[<@!>], '', user_input).strip()
            is_whitelisted = check_id in self.whitelist
            
            status = "✅ Whitelisted" if is_whitelisted else "❌ Not whitelisted"
            await interaction.followup.send(f"{status} - `{check_id}`", ephemeral=True)
            return
        
        # Add/Remove need user input
        if not user_input:
            await interaction.followup.send("❌ Please provide a user ID!", ephemeral=True)
            return
        
        # Extract ID from mention or use as-is
        target_id = re.sub(r[<@!>], '', user_input).strip()
        
        # Validate ID
        if not target_id.isdigit():
            await interaction.followup.send("❌ Invalid user ID! Use the user's ID or mention them.", ephemeral=True)
            return
        
        if action == "add":
            if target_id in self.whitelist:
                await interaction.followup.send(f"⚠️ User `{target_id}` is already whitelisted!", ephemeral=True)
                return
            
            self.whitelist.add(target_id)
            if self.save_whitelist():
                await interaction.followup.send(f"✅ Added `{target_id}` to whitelist!", ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to save whitelist!", ephemeral=True)
        
        elif action == "remove":
            if target_id == str(OWNER_ID):
                await interaction.followup.send("⛔ Cannot remove the owner!", ephemeral=True)
                return
            
            if target_id not in self.whitelist:
                await interaction.followup.send(f"⚠️ User `{target_id}` is not in whitelist!", ephemeral=True)
                return
            
            self.whitelist.remove(target_id)
            if self.save_whitelist():
                await interaction.followup.send(f"✅ Removed `{target_id}` from whitelist!", ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to save whitelist!", ephemeral=True)
    
    async def do_scan(self, interaction: discord.Interaction, image: discord.Attachment, hint: str):
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist:
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # Validate image
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
            
            # OCR with OCR.space
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
            
            # Find usernames - multiple patterns
            usernames = []
            
            # Pattern 1: @username
            usernames.extend(re.findall(r'@([A-Za-z0-9_]{3,20})\b', text))
            
            # Pattern 2: roblox.com/users/ID
            id_matches = re.findall(r'roblox\.com/users/(\d+)', text, re.IGNORECASE)
            
            # Pattern 3: standalone username (if hint provided)
            if hint:
                hint = hint.strip()
                if re.match(r'^[A-Za-z0-9_]{3,20}$', hint):
                    usernames.insert(0, hint)
            
            if not usernames and not id_matches:
                preview = text[:300].replace('\n', ' ')
                await interaction.followup.send(f"❌ No username found. OCR saw: ```{preview}...```")
                return
            
            # Try to resolve user
            user_info = None
            resolved_username = None
            
            # Try ID first (most reliable)
            if id_matches:
                try:
                    uid = int(id_matches[0])
                    async with self.session.get(f'https://users.roblox.com/v1/users/{uid}', timeout=10) as resp:
                        if resp.status == 200:
                            user_info = await resp.json()
                            resolved_username = user_info.get('name')
                except Exception as e:
                    print(f"ID lookup error: {e}")
            
            # Try username lookup
            if not user_info and usernames:
                for username in usernames[:3]:
                    try:
                        async with self.session.post(
                            'https://users.roblox.com/v1/usernames/users',
                            json={"usernames": [username], "excludeBannedUsers": False},
                            timeout=10
                        ) as resp:
                            data = await resp.json()
                            if data.get('data') and len(data['data']) > 0:
                                user_data = data['data'][0]
                                async with self.session.get(f'https://users.roblox.com/v1/users/{user_data["id"]}', timeout=10) as resp:
                                    if resp.status == 200:
                                        user_info = await resp.json()
                                        resolved_username = username
                                        break
                    except Exception as e:
                        print(f"Username lookup error for {username}: {e}")
                        continue
            
            if not user_info:
                tried = ', '.join(usernames[:5]) if usernames else f"ID:{id_matches[0]}" if id_matches else "none"
                await interaction.followup.send(f"❌ Could not resolve user. Tried: `{tried}`")
                return
            
            # Build embed
            color = 0xFF0000 if user_info.get('isBanned') else 0x00D4AA
            
            embed = discord.Embed(
                title=user_info.get('displayName') or user_info['name'],
                description=f"@{user_info['name']}",
                url=f'https://roblox.com/users/{user_info["id"]}/profile',
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(name="🆔 User ID", value=f"`{user_info['id']}`", inline=True)
            embed.add_field(name="📅 Created", value=str(user_info.get('created', 'Unknown'))[:10], inline=True)
            embed.add_field(name="⚡ Status", value="🔴 Banned" if user_info.get('isBanned') else "✅ Active", inline=True)
            
            if user_info.get('description'):
                desc = user_info['description'][:200] + "..." if len(user_info['description']) > 200 else user_info['description']
                embed.add_field(name="📝 About", value=desc, inline=False)
            
            embed.set_image(url=image.url)
            embed.set_footer(text="TRUE OMEGA | Railway Deployment")
            
            await interaction.followup.send(embed=embed)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏱️ Scan timed out. Try a smaller image.")
        except Exception as e:
            print(f"Scan error: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"❌ Error: {str(e)[:200]}")
    
    async def do_download(self, interaction: discord.Interaction, url: str):
        user_id = str(interaction.user.id)
        
        if user_id not in self.whitelist:
            await interaction.response.send_message("⛔ Not whitelisted", ephemeral=True)
            return
        
        if not url.startswith(('http://', 'https://')):
            await interaction.response.send_message("❌ Invalid URL", ephemeral=True)
            return
        
        # Check supported sites
        supported = ['youtube', 'youtu.be', 'tiktok', 'instagram', 'twitter', 'x.com', 'reddit', 'streamable', 'medal.tv', 'medal']
        if not any(site in url.lower() for site in supported):
            await interaction.response.send_message(
                "❌ Unsupported site. Supported: YouTube, TikTok, Instagram, Twitter/X, Reddit, Streamable, Medal.tv",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            result = await self.downloader.download(url, str(interaction.user.id))
            
            if not result['success']:
                await interaction.followup.send(f"❌ Download failed: {result['error']}")
                return
            
            size_mb = result['size'] / (1024 * 1024)
            
            if result['size'] > 25 * 1024 * 1024:
                await interaction.followup.send(f"⚠️ File too large ({size_mb:.1f}MB). Max is 25MB for Discord.")
                self.downloader.cleanup(result['file_path'])
                return
            
            # Sanitize filename
            safe_title = re.sub(r'[^\w\-_.]', '_', result['title'][:40])
            filename = f"{safe_title}.mp4"
            
            file = discord.File(result['file_path'], filename=filename)
            
            embed = discord.Embed(
                title="📥 Download Complete",
                description=f"**{result['title'][:100]}**",
                color=0x00D4AA
            )
            embed.add_field(name="📦 Size", value=f"{size_mb:.1f}MB", inline=True)
            embed.set_footer(text="TRUE OMEGA | Railway")
            
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
            print("\n⚠️ Bot stopped, restarting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            traceback.print_exc()
            print("\nRestarting in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    main()
