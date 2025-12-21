"""Netease Cloud Music Provider implementation for MusicAssistant."""

import logging
from typing import Any

import httpx

from music_assistant.models.config_entry import ConfigEntry, ConfigValueType
from music_assistant.models.media_items import (
    Album,
    Artist,
    MediaItemType,
    ProviderMapping,
    Radio,
    Track,
)
from music_assistant.models.provider import Provider

logger = logging.getLogger(__name__)


class NeteaseProvider(Provider):
    """Netease Cloud Music Provider for MusicAssistant."""

    @property
    def domain(self) -> str:
        """返回 Provider 的域名标识."""
        return "netease"

    async def setup(self) -> None:
        """初始化 Provider."""
        api_url = self.config.get_value("api_url")
        if not api_url:
            raise ValueError("API URL 未配置")
        self.api_url = api_url.rstrip("/")
        logger.info(f"NeteaseProvider 初始化完成，API URL: {self.api_url}")

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """返回 Provider 的配置项."""
        return (
            ConfigEntry(
                key="api_url",
                type=ConfigValueType.STRING,
                label="API 地址",
                description="netease_cloud_music_api 的部署地址，例如: http://localhost:3000",
                required=True,
                default_value="http://localhost:3000",
            ),
        )

    async def search(
        self,
        search_query: str,
        media_types: list[MediaItemType] | None = None,
        limit: int = 20,
    ) -> dict[MediaItemType, list[Track | Album | Artist | Radio]]:
        """
        搜索音乐、电台、有声读物等.

        Args:
            search_query: 搜索关键词
            media_types: 要搜索的媒体类型列表
            limit: 返回结果数量限制

        Returns:
            按媒体类型分组的搜索结果
        """
        if media_types is None:
            media_types = [MediaItemType.TRACK, MediaItemType.ALBUM, MediaItemType.ARTIST, MediaItemType.RADIO]

        results: dict[MediaItemType, list[Track | Album | Artist | Radio]] = {
            media_type: [] for media_type in media_types
        }

        try:
            # 搜索音乐
            if MediaItemType.TRACK in media_types:
                tracks = await self._search_tracks(search_query, limit)
                results[MediaItemType.TRACK] = tracks

            # 搜索专辑
            if MediaItemType.ALBUM in media_types:
                albums = await self._search_albums(search_query, limit)
                results[MediaItemType.ALBUM] = albums

            # 搜索艺术家
            if MediaItemType.ARTIST in media_types:
                artists = await self._search_artists(search_query, limit)
                results[MediaItemType.ARTIST] = artists

            # 搜索电台/有声读物（使用播客接口）
            if MediaItemType.RADIO in media_types:
                radios = await self._search_radios(search_query, limit)
                results[MediaItemType.RADIO] = radios

        except Exception as e:
            logger.error(f"搜索失败: {e}", exc_info=True)
            raise

        return results

    async def _search_tracks(self, query: str, limit: int = 20) -> list[Track]:
        """搜索歌曲."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/search"
                params = {"keywords": query, "type": 1, "limit": limit}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                tracks = []
                songs = data.get("result", {}).get("songs", [])
                for song in songs:
                    track = await self._song_to_track(song)
                    if track:
                        tracks.append(track)

                return tracks
        except Exception as e:
            logger.error(f"搜索歌曲失败: {e}", exc_info=True)
            return []

    async def _search_albums(self, query: str, limit: int = 20) -> list[Album]:
        """搜索专辑."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/search"
                params = {"keywords": query, "type": 10, "limit": limit}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                albums = []
                album_list = data.get("result", {}).get("albums", [])
                for album_data in album_list:
                    album = await self._album_data_to_album(album_data)
                    if album:
                        albums.append(album)

                return albums
        except Exception as e:
            logger.error(f"搜索专辑失败: {e}", exc_info=True)
            return []

    async def _search_artists(self, query: str, limit: int = 20) -> list[Artist]:
        """搜索艺术家."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/search"
                params = {"keywords": query, "type": 100, "limit": limit}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                artists = []
                artist_list = data.get("result", {}).get("artists", [])
                for artist_data in artist_list:
                    artist = await self._artist_data_to_artist(artist_data)
                    if artist:
                        artists.append(artist)

                return artists
        except Exception as e:
            logger.error(f"搜索艺术家失败: {e}", exc_info=True)
            return []

    async def _search_radios(self, query: str, limit: int = 20) -> list[Radio]:
        """搜索电台/有声读物（使用播客搜索）."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/search"
                params = {"keywords": query, "type": 1009, "limit": limit}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                radios = []
                dj_programs = data.get("result", {}).get("djRadios", [])
                for dj_data in dj_programs:
                    radio = await self._dj_data_to_radio(dj_data)
                    if radio:
                        radios.append(radio)

                return radios
        except Exception as e:
            logger.error(f"搜索电台失败: {e}", exc_info=True)
            return []

    async def _song_to_track(self, song: dict[str, Any]) -> Track | None:
        """将 API 返回的歌曲数据转换为 Track 对象."""
        try:
            song_id = str(song.get("id", ""))
            name = song.get("name", "")
            
            # 验证必要字段
            if not song_id or not name:
                logger.warning(f"歌曲数据缺少必要字段: id={song_id}, name={name}")
                return None
            
            artists_data = song.get("ar", [])
            album_data = song.get("al", {})
            duration = song.get("dt", 0) / 1000  # 转换为秒

            # 创建艺术家列表
            artists = []
            for artist_data in artists_data:
                artist_id = str(artist_data.get("id", ""))
                artist_name = artist_data.get("name", "")
                if artist_id and artist_name:
                    artist = Artist(
                        item_id=artist_id,
                        provider=self.domain,
                        name=artist_name,
                        provider_mappings={
                            ProviderMapping(
                                item_id=artist_id,
                                provider_domain=self.domain,
                                url=f"https://music.163.com/#/artist?id={artist_id}",
                            )
                        },
                    )
                    artists.append(artist)

            # 创建专辑对象
            album = None
            if album_data:
                album = Album(
                    item_id=str(album_data.get("id", "")),
                    provider=self.domain,
                    name=album_data.get("name", ""),
                    provider_mappings={
                        ProviderMapping(
                            item_id=str(album_data.get("id", "")),
                            provider_domain=self.domain,
                            url=f"https://music.163.com/#/album?id={album_data.get('id', '')}",
                        )
                    },
                )

            # 创建 Track 对象
            track = Track(
                item_id=song_id,
                provider=self.domain,
                name=name,
                version=song.get("tns", [None])[0] if song.get("tns") else None,
                duration=duration,
                artists=artists,
                album=album,
                provider_mappings={
                    ProviderMapping(
                        item_id=song_id,
                        provider_domain=self.domain,
                        url=f"https://music.163.com/#/song?id={song_id}",
                        available=True,
                    )
                },
            )

            return track
        except Exception as e:
            logger.error(f"转换歌曲数据失败: {e}", exc_info=True)
            return None

    async def _album_data_to_album(self, album_data: dict[str, Any]) -> Album | None:
        """将 API 返回的专辑数据转换为 Album 对象."""
        try:
            album_id = str(album_data.get("id", ""))
            name = album_data.get("name", "")
            
            # 验证必要字段
            if not album_id or not name:
                logger.warning(f"专辑数据缺少必要字段: id={album_id}, name={name}")
                return None
            
            artist_data = album_data.get("artist", {})

            # 创建艺术家
            artist = None
            if artist_data:
                artist_id = str(artist_data.get("id", ""))
                artist_name = artist_data.get("name", "")
                if artist_id and artist_name:
                    artist = Artist(
                        item_id=artist_id,
                        provider=self.domain,
                        name=artist_name,
                    )

            album = Album(
                item_id=album_id,
                provider=self.domain,
                name=name,
                artists=[artist] if artist else [],
                provider_mappings={
                    ProviderMapping(
                        item_id=album_id,
                        provider_domain=self.domain,
                        url=f"https://music.163.com/#/album?id={album_id}",
                        available=True,
                    )
                },
            )

            return album
        except Exception as e:
            logger.error(f"转换专辑数据失败: {e}", exc_info=True)
            return None

    async def _artist_data_to_artist(self, artist_data: dict[str, Any]) -> Artist | None:
        """将 API 返回的艺术家数据转换为 Artist 对象."""
        try:
            artist_id = str(artist_data.get("id", ""))
            name = artist_data.get("name", "")
            
            # 验证必要字段
            if not artist_id or not name:
                logger.warning(f"艺术家数据缺少必要字段: id={artist_id}, name={name}")
                return None

            artist = Artist(
                item_id=artist_id,
                provider=self.domain,
                name=name,
                provider_mappings={
                    ProviderMapping(
                        item_id=artist_id,
                        provider_domain=self.domain,
                        url=f"https://music.163.com/#/artist?id={artist_id}",
                        available=True,
                    )
                },
            )

            return artist
        except Exception as e:
            logger.error(f"转换艺术家数据失败: {e}", exc_info=True)
            return None

    async def _dj_data_to_radio(self, dj_data: dict[str, Any]) -> Radio | None:
        """将 API 返回的电台数据转换为 Radio 对象."""
        try:
            radio_id = str(dj_data.get("id", ""))
            name = dj_data.get("name", "")
            
            # 验证必要字段
            if not radio_id or not name:
                logger.warning(f"电台数据缺少必要字段: id={radio_id}, name={name}")
                return None

            radio = Radio(
                item_id=radio_id,
                provider=self.domain,
                name=name,
                provider_mappings={
                    ProviderMapping(
                        item_id=radio_id,
                        provider_domain=self.domain,
                        url=f"https://music.163.com/#/djradio?id={radio_id}",
                        available=True,
                    )
                },
            )

            return radio
        except Exception as e:
            logger.error(f"转换电台数据失败: {e}", exc_info=True)
            return None

    async def get_track(self, track_id: str) -> Track:
        """获取单曲详细信息."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/song/detail"
                params = {"ids": track_id}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                songs = data.get("songs", [])
                if not songs:
                    raise ValueError(f"未找到 ID 为 {track_id} 的歌曲")

                song = songs[0]
                track = await self._song_to_track(song)
                if not track:
                    raise ValueError(f"无法转换歌曲数据: {track_id}")

                return track
        except Exception as e:
            logger.error(f"获取歌曲详情失败: {e}", exc_info=True)
            raise

    async def get_album(self, album_id: str) -> Album:
        """获取专辑详细信息."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/album"
                params = {"id": album_id}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                album_data = data.get("album", {})
                if not album_data:
                    raise ValueError(f"未找到 ID 为 {album_id} 的专辑")

                album = await self._album_data_to_album(album_data)
                if not album:
                    raise ValueError(f"无法转换专辑数据: {album_id}")

                return album
        except Exception as e:
            logger.error(f"获取专辑详情失败: {e}", exc_info=True)
            raise

    async def get_artist(self, artist_id: str) -> Artist:
        """获取艺术家详细信息."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/artist/detail"
                params = {"id": artist_id}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                artist_data = data.get("data", {}).get("artist", {})
                if not artist_data:
                    raise ValueError(f"未找到 ID 为 {artist_id} 的艺术家")

                artist = await self._artist_data_to_artist(artist_data)
                if not artist:
                    raise ValueError(f"无法转换艺术家数据: {artist_id}")

                return artist
        except Exception as e:
            logger.error(f"获取艺术家详情失败: {e}", exc_info=True)
            raise

    async def get_radio(self, radio_id: str) -> Radio:
        """获取电台详细信息."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/dj/detail"
                params = {"rid": radio_id}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                radio_data = data.get("data", {})
                if not radio_data:
                    raise ValueError(f"未找到 ID 为 {radio_id} 的电台")

                radio = await self._dj_data_to_radio(radio_data)
                if not radio:
                    raise ValueError(f"无法转换电台数据: {radio_id}")

                return radio
        except Exception as e:
            logger.error(f"获取电台详情失败: {e}", exc_info=True)
            raise

    async def get_stream_url(self, item_id: str, media_type: MediaItemType) -> str:
        """
        获取流媒体 URL.

        Args:
            item_id: 媒体项 ID
            media_type: 媒体类型

        Returns:
            流媒体 URL
        """
        if media_type != MediaItemType.TRACK:
            raise ValueError(f"不支持的媒体类型: {media_type}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.api_url}/song/url/v1"
                params = {"id": item_id, "level": "exhigh"}
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                songs = data.get("data", [])
                if not songs:
                    raise ValueError(f"未找到 ID 为 {item_id} 的歌曲 URL")

                stream_url = songs[0].get("url")
                if not stream_url:
                    raise ValueError(f"歌曲 {item_id} 没有可用的 URL")

                return stream_url
        except Exception as e:
            logger.error(f"获取流媒体 URL 失败: {e}", exc_info=True)
            raise

