# ═══════════════════════════════════════════════════════════
# ROBLOX API - FIXED FOR NEW API CHANGES
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
        """Get friends - FIXED for new Roblox API that only returns IDs"""
        cached = await self.cache.get(f"f:{user_id}")
        if cached:
            return [FriendData(**f) for f in cached]
        
        try:
            # Step 1: Get friend IDs from friends endpoint
            async with self.session.get(
                f'https://friends.roblox.com/v1/users/{user_id}/friends',
                timeout=aiohttp.ClientTimeout(total=Config.FRIENDS_TIMEOUT)
            ) as resp:
                if resp.status == 403:
                    logger.info("Friends list is private")
                    return []
                if resp.status != 200:
                    logger.warning(f"Friends API returned {resp.status}")
                    return []
                
                data = await resp.json()
                friend_entries = data.get('data', [])
                
                if not friend_entries:
                    logger.info("No friends found")
                    return []
                
                logger.info(f"Got {len(friend_entries)} friend IDs from API")
                
                # Extract just the IDs (new API only returns id and isDeleted)
                friend_ids = [f.get('id') for f in friend_entries if f.get('id')]
                
                if not friend_ids:
                    return []
            
            # Step 2: Get online status for these friends
            online_ids = await self._get_online_friends(user_id)
            
            # Step 3: Batch lookup user details (max 100 per request)
            friends = []
            for i in range(0, len(friend_ids), 100):
                batch = friend_ids[i:i+100]
                batch_friends = await self._batch_fetch_users(batch, online_ids)
                friends.extend(batch_friends)
            
            # Cache
            cache_data = [{'id': f.id, 'name': f.name, 'display_name': f.display_name, 'is_online': f.is_online} for f in friends]
            await self.cache.set(f"f:{user_id}", cache_data, 300)
            
            return friends[:50]  # Return max 50
                
        except Exception as e:
            logger.error(f"Get friends error: {e}")
            return []
    
    async def _get_online_friends(self, user_id: int) -> Set[int]:
        """Get set of online friend IDs"""
        try:
            async with self.session.get(
                f'https://friends.roblox.com/v1/users/{user_id}/friends/online',
                timeout=aiohttp.ClientTimeout(total=Config.API_TIMEOUT)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # New API format: {"data": [{"id": 123, "userPresence": {...}}]}
                    return {f.get('id') for f in data.get('data', []) if f.get('id')}
        except Exception as e:
            logger.debug(f"Get online friends error: {e}")
        return set()
    
    async def _batch_fetch_users(self, user_ids: List[int], online_ids: Set[int]) -> List[FriendData]:
        """Fetch user details in batch"""
        if not user_ids:
            return []
        
        try:
            # Use the users API to get details for multiple users
            # We have to fetch one by one since batch endpoint is limited
            friends = []
            
            # Actually, let's use the presence API to get names or fetch individually
            # since the batch user endpoint doesn't exist for unauthenticated requests
            
            for uid in user_ids:
                try:
                    # Try cache first
                    cached = await self.cache.get(f"u:{uid}")
                    if cached:
                        friends.append(FriendData(
                            id=uid,
                            name=cached.get('name', str(uid)),
                            display_name=cached.get('displayName') or cached.get('name', str(uid)),
                            is_online=uid in online_ids
                        ))
                        continue
                    
                    # Fetch individual user
                    async with self.session.get(
                        f'https://users.roblox.com/v1/users/{uid}',
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as resp:
                        if resp.status == 200:
                            user_data = await resp.json()
                            username = user_data.get('name', str(uid))
                            display = user_data.get('displayName') or username
                            
                            # Cache it
                            await self.cache.set(f"u:{uid}", user_data, 600)
                            
                            friends.append(FriendData(
                                id=uid,
                                name=username,
                                display_name=display,
                                is_online=uid in online_ids
                            ))
                        else:
                            # If we can't fetch, use ID as placeholder
                            friends.append(FriendData(
                                id=uid,
                                name=f"User_{uid}",
                                display_name=f"User {uid}",
                                is_online=uid in online_ids
                            ))
                except Exception as e:
                    logger.debug(f"Error fetching user {uid}: {e}")
                    friends.append(FriendData(
                        id=uid,
                        name=f"User_{uid}",
                        display_name=f"User {uid}",
                        is_online=uid in online_ids
                    ))
            
            return friends
            
        except Exception as e:
            logger.error(f"Batch fetch error: {e}")
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
