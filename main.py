# ═══════════════════════════════════════════════════════════
# VIDEO DOWNLOADER - YT-DLP POWERED (FIXED)
# ═══════════════════════════════════════════════════════════
class VideoDownloader:
    """Download videos from Medal, Streamable, YouTube, etc. using yt-dlp"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.download_path = "downloads/videos"
        os.makedirs(self.download_path, exist_ok=True)
    
    def _run_yt_dlp(self, url: str, output_path: str) -> Tuple[bool, str, Optional[VideoInfo]]:
        """Run yt-dlp to download video"""
        try:
            # First, get info
            info_cmd = [
                'yt-dlp',
                '--dump-json',
                '--no-download',
                url
            ]
            
            result = subprocess.run(
                info_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, f"Failed to get video info: {result.stderr}", None
            
            try:
                info = json.loads(result.stdout.strip().split('\n')[0])
            except:
                return False, "Failed to parse video info", None
            
            video_info = VideoInfo(
                url=url,
                title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            # Download video
            download_cmd = [
                'yt-dlp',
                '-f', 'best[ext=mp4]/best',  # Best quality MP4 or best available
                '--merge-output-format', 'mp4',
                '-o', output_path,
                '--no-playlist',
                '--newline',
                url
            ]
            
            result = subprocess.run(
                download_cmd,
                capture_output=True,
                text=True,
                timeout=Config.VIDEO_TIMEOUT
            )
            
            if result.returncode != 0:
                return False, f"Download failed: {result.stderr}", video_info
            
            if os.path.exists(output_path):
                return True, "Success", video_info
            else:
                return False, "Output file not created", video_info
                
        except subprocess.TimeoutExpired:
            return False, "Download timeout", None
        except Exception as e:
            return False, str(e), None
    
    def _format_duration(self, seconds: Optional[Union[int, float]]) -> str:
        """Format seconds to readable duration - FIXED for float values"""
        if not seconds:
            return "Unknown"
        
        # Convert to int to handle float values from yt-dlp
        try:
            seconds = int(float(seconds))
        except (ValueError, TypeError):
            return "Unknown"
        
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
    
    async def download(self, url: str) -> Tuple[bool, str, Optional[str], Optional[VideoInfo]]:
        """
        Download video from URL
        Returns: (success, message, file_path, video_info)
        """
        # Validate URL
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')
        
        if not any(d in domain for d in Config.VIDEO_DOMAINS):
            return False, f"Unsupported domain. Supported: {', '.join(Config.VIDEO_DOMAINS)}", None, None
        
        # Generate filename
        video_id = hashlib.md5(url.encode()).hexdigest()[:8]
        output_path = os.path.join(self.download_path, f"{video_id}.mp4")
        
        # Check if already downloaded
        if os.path.exists(output_path):
            # Get info from cache or re-fetch
            return True, "Already downloaded (cached)", output_path, None
        
        # Run download in thread pool
        loop = asyncio.get_event_loop()
        success, message, info = await loop.run_in_executor(
            self.executor,
            self._run_yt_dlp,
            url,
            output_path
        )
        
        if success:
            return True, message, output_path, info
        else:
            return False, message, None, info
    
    async def get_info(self, url: str) -> Tuple[bool, Optional[VideoInfo]]:
        """Get video info without downloading"""
        try:
            cmd = ['yt-dlp', '--dump-json', '--no-download', url]
            loop = asyncio.get_event_loop()
            
            result = await loop.run_in_executor(
                self.executor,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
            
            if result.returncode != 0:
                return False, None
            
            info = json.loads(result.stdout.strip().split('\n')[0])
            
            video_info = VideoInfo(
                url=url,
                title=info.get('title', 'Unknown'),
                duration=self._format_duration(info.get('duration')),
                uploader=info.get('uploader', 'Unknown'),
                thumbnail=info.get('thumbnail'),
                filesize=info.get('filesize_approx') or info.get('filesize')
            )
            
            return True, video_info
            
        except Exception as e:
            logger.error(f"Get info error: {e}")
            return False, None


# ═══════════════════════════════════════════════════════════
# BOT - DOWNLOAD COMMAND (FIXED)
# ═══════════════════════════════════════════════════════════
async def cmd_download(self, interaction: discord.Interaction, url: str, info_only: bool = False):
    """Download video from URL using yt-dlp"""
    uid = str(interaction.user.id)
    
    if not self.db.is_whitelisted(uid):
        await interaction.response.send_message(
            embed=discord.Embed(title="⛔ Not Whitelisted", color=0xFF0000),
            ephemeral=True
        )
        return
    
    allowed, retry = await self.video_limiter.check(uid)
    if not allowed:
        await interaction.response.send_message(
            embed=discord.Embed(title="⏰ Rate Limited", description=f"Try again in {int(retry)}s", color=0xFFA500),
            ephemeral=True
        )
        return
    
    await interaction.response.defer(thinking=True)
    
    try:
        if info_only:
            # Just get info
            success, info = await self.video_downloader.get_info(url)
            if not success:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Failed to get video info", color=0xFF0000)
                )
                return
            
            embed = discord.Embed(
                title=f"📹 {info.title[:100]}",
                url=url,
                description=f"**{info.uploader}** • {info.duration}",
                color=0x00D4AA
            )
            if info.thumbnail:
                embed.set_thumbnail(url=info.thumbnail)
            embed.add_field(name="⏱️ Duration", value=info.duration, inline=True)
            embed.add_field(name="👤 Uploader", value=info.uploader, inline=True)
            embed.add_field(name="📁 Estimated Size", value=self._format_size(info.filesize), inline=True)
            embed.set_footer(text="Use /download without info_only to download")
            
            await interaction.followup.send(embed=embed)
        else:
            # Actually download
            success, message, file_path, info = await self.video_downloader.download(url)
            
            if not success:
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Download Failed", description=message, color=0xFF0000)
                )
                return
            
            if not file_path or not os.path.exists(file_path):
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ File not found", color=0xFF0000)
                )
                return
            
            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > Config.MAX_FILE_SIZE:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ File Too Large",
                        description=f"Video is {self._format_size(file_size)}, max is {self._format_size(Config.MAX_FILE_SIZE)}",
                        color=0xFF0000
                    )
                )
                return
            
            # Send file
            file = discord.File(file_path, filename=os.path.basename(file_path))
            
            embed = discord.Embed(
                title=f"📥 Downloaded: {info.title[:100] if info else 'Video'}",
                description=f"**{info.uploader if info else 'Unknown'}** • {info.duration if info else 'Unknown'}",
                color=0x00FF00
            )
            if info and info.thumbnail:
                embed.set_thumbnail(url=info.thumbnail)
            
            await interaction.followup.send(embed=embed, file=file)
            
            # Log and webhook
            if info:
                await self.db.log_download(uid, url, info.title)
                await self.webhook.send_video_download(interaction.user, info, file_path)
                
                # Update stats
                stats = await self.db.get_stats(uid)
                stats['videos_downloaded'] = stats.get('videos_downloaded', 0) + 1
                await self.db.save_stats(uid, stats)
            
    except Exception as e:
        logger.error(f"Download error: {traceback.format_exc()}")
        await interaction.followup.send(
            embed=discord.Embed(title="❌ Error", description=str(e)[:200], color=0xFF0000)
        )


def _format_size(self, size_bytes: Optional[Union[int, float]]) -> str:
    """Format file size to human readable - FIXED for float values"""
    if not size_bytes:
        return "Unknown"
    
    try:
        size_bytes = float(size_bytes)
    except (ValueError, TypeError):
        return "Unknown"
    
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
