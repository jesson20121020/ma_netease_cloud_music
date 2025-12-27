"""Netease Cloud Music provider that integrates with NeteaseCloudMusicApi."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import (
    ConfigEntryType,
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.media_items import (
    Album,
    Artist,
    Audiobook,
    AudioFormat,
    ItemMapping,
    MediaItemChapter,
    MediaItemImage,
    MediaItemMetadata,
    Podcast,
    PodcastEpisode,
    ProviderMapping,
    SearchResults,
    Track,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.constants import MASS_LOGO, VARIOUS_ARTISTS_FANART
from music_assistant.models.music_provider import MusicProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

_LOGGER = logging.getLogger(__name__)


CONF_KEY_API_URL = "api_url"
CONF_KEY_UNBLOCK_API_URL = "unblock_api_url"

# NeteaseCloudMusicApi search types
# 1: 单曲, 10: 专辑, 100: 歌手, 1000: 歌单, 1009: 电台, 1014: 视频
NETEASE_SEARCH_TYPE_SONG = 1
NETEASE_SEARCH_TYPE_ALBUM = 10
NETEASE_SEARCH_TYPE_ARTIST = 100
NETEASE_SEARCH_TYPE_PLAYLIST = 1000
NETEASE_SEARCH_TYPE_RADIO = 1009

SUPPORTED_FEATURES = {
    ProviderFeature.SEARCH,
    ProviderFeature.BROWSE,
    ProviderFeature.LIBRARY_ARTISTS,
    ProviderFeature.LIBRARY_ALBUMS,
    ProviderFeature.LIBRARY_TRACKS,
    ProviderFeature.LIBRARY_PODCASTS,
    ProviderFeature.LIBRARY_AUDIOBOOKS,
    ProviderFeature.ARTIST_ALBUMS,
}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    return NeteaseProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,  # noqa: ARG001
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,  # noqa: ARG001
    values: dict[str, ConfigValueType] | None = None,  # noqa: ARG001
) -> tuple[ConfigEntry, ...]:
    """
    Return Config entries to setup this provider.

    instance_id: id of an existing provider instance (None if new instance setup).
    action: [optional] action key called from config entries UI.
    values: the (intermediate) raw values for config entries sent with the action.
    """
    return (
        ConfigEntry(
            key=CONF_KEY_API_URL,
            type=ConfigEntryType.STRING,
            label="API 地址",
            description="NeteaseCloudMusicApi 服务地址（例如：http://localhost:3000）",
            default_value="http://localhost:3000",
            required=True,
        ),
        ConfigEntry(
            key=CONF_KEY_UNBLOCK_API_URL,
            type=ConfigEntryType.STRING,
            label="解锁 API 地址",
            description="网易云音乐解锁 API 服务地址（例如：http://localhost:3001），用于获取无版权限制的音源",
            default_value="",
            required=False,
        ),
    )


class NeteaseProvider(MusicProvider):
    """Netease Cloud Music provider implementation."""

    _api_url: str
    _unblock_api_url: str | None
    _http_client: httpx.AsyncClient

    async def handle_async_init(self) -> None:
        """Initialize provider."""
        api_url = self.config.get_value(CONF_KEY_API_URL)
        if not api_url or not isinstance(api_url, str):
            msg = "API URL is required"
            raise ValueError(msg)
        # Remove trailing slash
        self._api_url = api_url.rstrip("/")

        unblock_api_url = self.config.get_value(CONF_KEY_UNBLOCK_API_URL)
        if unblock_api_url and isinstance(unblock_api_url, str) and unblock_api_url.strip():
            self._unblock_api_url = unblock_api_url.rstrip("/")
        else:
            self._unblock_api_url = None

        self._http_client = httpx.AsyncClient(timeout=30.0)
        _LOGGER.info("Netease Provider initialized with API URL: %s, Unblock API URL: %s",
                    self._api_url, self._unblock_api_url)

    async def close(self) -> None:
        """Cleanup on provider close."""
        await super().close()
        await self._http_client.aclose()

    @property
    def is_streaming_provider(self) -> bool:
        """Return True if the provider is a streaming provider."""
        return True

    async def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Make a request to NeteaseCloudMusicApi."""
        url = f"{self._api_url}{endpoint}"
        try:
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 200:
                _LOGGER.warning("API returned error code %s: %s", data.get("code"), data.get("message"))
                return None
            return data
        except httpx.HTTPError as err:
            _LOGGER.error("HTTP error while requesting %s: %s", url, err)
            return None
        except Exception as err:
            _LOGGER.error("Unexpected error while requesting %s: %s", url, err)
            return None

    async def _request_unblock_api(self, song_id: str) -> dict[str, Any] | None:
        """Request unblock API to get alternative audio sources."""
        if not self._unblock_api_url:
            return None

        url = f"{self._unblock_api_url}/match/{song_id}"
        try:
            _LOGGER.debug("Requesting unblock API: %s", url)
            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("audioUrl"):
                _LOGGER.info("Successfully got unblocked URL for song %s from source: %s", song_id, data.get("source"))
                return data
            else:
                _LOGGER.debug("Unblock API returned no valid result for song %s", song_id)
                return None
        except httpx.HTTPError as err:
            _LOGGER.warning("HTTP error while requesting unblock API %s: %s", url, err)
            return None
        except Exception as err:
            _LOGGER.warning("Unexpected error while requesting unblock API %s: %s", url, err)
            return None

    def _build_image(self, url: str | None, image_type: ImageType = ImageType.THUMB) -> MediaItemImage | None:
        """Build MediaItemImage from URL."""
        if not url:
            return None
        # Process Netease image URL to add size parameter for better quality
        processed_url = self._process_netease_image_url(url)
        return MediaItemImage(
            type=image_type,
            path=processed_url,
            provider=self.instance_id,
            remotely_accessible=True,
        )

    def _process_netease_image_url(self, url: str, size: int = 300) -> str:
        """Process Netease image URL to add size parameter for better quality."""
        if not url or 'music.126.net' not in url:
            return url
        # Add size parameter if not already present
        if '?' in url:
            return url
        return f"{url}?param={size}y{size}"

    def _build_images(self, urls: list[str] | None) -> UniqueList[MediaItemImage]:
        """Build UniqueList of MediaItemImage from URLs."""
        images = UniqueList[MediaItemImage]()
        if urls:
            for url in urls[:3]:  # Limit to 3 images
                img = self._build_image(url)
                if img:
                    images.append(img)
        if not images:
            # Add default image if no images available
            images.append(
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=MASS_LOGO,
                    provider="builtin",
                    remotely_accessible=False,
                )
            )
        return images

    async def search(
        self, search_query: str, media_types: list[MediaType] | None = None, limit: int = 20
    ) -> SearchResults:
        """Perform search on the provider."""
        if not media_types:
            media_types = [MediaType.TRACK, MediaType.ALBUM, MediaType.ARTIST, MediaType.PODCAST]

        result = SearchResults()

        # Search for tracks
        if MediaType.TRACK in media_types:
            try:
                data = await self._request(
                    "/search",
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_SONG, "limit": limit},
                )
                if data and "result" in data and "songs" in data["result"]:
                    songs_data = data["result"]["songs"][:limit]
                    # Batch fetch track details for accurate cover images
                    track_details = await self._batch_fetch_track_details([str(song["id"]) for song in songs_data])
                    for song_data in songs_data:
                        track = await self._parse_track_from_search(song_data, track_details.get(str(song_data["id"])))
                        if track:
                            result.tracks.append(track)
            except Exception as err:
                _LOGGER.error("Error searching tracks: %s", err)

        # Search for albums
        if MediaType.ALBUM in media_types:
            try:
                data = await self._request(
                    "/search",
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_ALBUM, "limit": limit},
                )
                if data and "result" in data and "albums" in data["result"]:
                    for album_data in data["result"]["albums"][:limit]:
                        album = await self._parse_album_from_search(album_data)
                        if album:
                            result.albums.append(album)
            except Exception as err:
                _LOGGER.error("Error searching albums: %s", err)

        # Search for artists
        if MediaType.ARTIST in media_types:
            try:
                data = await self._request(
                    "/search",
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_ARTIST, "limit": limit},
                )
                if data and "result" in data and "artists" in data["result"]:
                    for artist_data in data["result"]["artists"][:limit]:
                        artist = await self._parse_artist_from_search(artist_data)
                        if artist:
                            result.artists.append(artist)
            except Exception as err:
                _LOGGER.error("Error searching artists: %s", err)

        # Search for playlists
        if MediaType.PLAYLIST in media_types:
            try:
                data = await self._request(
                    "/search",
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_PLAYLIST, "limit": limit},
                )
                if data and "result" in data and "playlists" in data["result"]:
                    for playlist_data in data["result"]["playlists"][:limit]:
                        playlist = await self._parse_playlist_from_search(playlist_data)
                        if playlist:
                            result.playlists.append(playlist)
            except Exception as err:
                _LOGGER.error("Error searching playlists: %s", err)

        # Search for podcasts (radio)
        if MediaType.PODCAST in media_types:
            try:
                data = await self._request(
                    "/search",
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_RADIO, "limit": limit},
                )
                if data and "result" in data and "djRadios" in data["result"]:
                    for radio_data in data["result"]["djRadios"][:limit]:
                        podcast = await self._parse_podcast_from_search(radio_data)
                        if podcast:
                            result.podcasts.append(podcast)
            except Exception as err:
                _LOGGER.error("Error searching podcasts: %s", err)

        return result



    async def _batch_fetch_track_details(self, track_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Batch fetch track details for accurate cover images."""
        if not track_ids:
            return {}
        
        # Use batch API to get details for multiple tracks
        ids_str = ','.join(track_ids)
        data = await self._request("/song/detail", params={"ids": ids_str})
        if not data or "songs" not in data:
            return {}
        
        # Create mapping of track_id to detail data
        details = {}
        for song in data["songs"]:
            details[str(song["id"])] = song
        return details

    async def _parse_track_from_search(self, song_data: dict[str, Any], detail_data: dict[str, Any] | None = None) -> Track | None:
        """Parse Track from search result."""
        try:
            song_id = str(song_data["id"])
            name = song_data.get("name", "Unknown")
            duration = song_data.get("duration", 0) // 1000  # Convert from milliseconds

            # Parse artists
            artists = UniqueList[Artist]()
            if "artists" in song_data:
                for artist_data in song_data["artists"]:
                    artist_id = str(artist_data["id"])
                    artist_name = artist_data.get("name", "Unknown Artist")
                    artists.append(
                        Artist(
                            item_id=artist_id,
                            provider=self.instance_id,
                            name=artist_name,
                            provider_mappings={
                                ProviderMapping(
                                    item_id=artist_id,
                                    provider_domain=self.domain,
                                    provider_instance=self.instance_id,
                                )
                            },
                        )
                    )

            # Parse album
            album: Album | ItemMapping | None = None
            album_cover_url: str | None = None
            if "album" in song_data:
                album_data = song_data["album"]
                album_id = str(album_data["id"])
                album_name = album_data.get("name", "Unknown Album")
                album_cover_url = album_data.get("picUrl")
                album = Album(
                    item_id=album_id,
                    provider=self.instance_id,
                    name=album_name,
                    artists=artists.copy() if artists else UniqueList(),
                    provider_mappings={
                        ProviderMapping(
                            item_id=album_id,
                            provider_domain=self.domain,
                            provider_instance=self.instance_id,
                        )
                    },
                )

            # Build images: prefer detail data, then search data
            cover_url = None
            if detail_data:
                # Use detailed data which has accurate picUrl
                cover_url = detail_data.get("picUrl") or detail_data.get("al", {}).get("picUrl")
            if not cover_url:
                # Fallback to search data
                song_pic_url = song_data.get("picUrl")
                cover_url = song_pic_url or album_cover_url
            images = self._build_images([cover_url] if cover_url else None)

            return Track(
                item_id=song_id,
                provider=self.instance_id,
                name=name,
                duration=duration,
                artists=artists,
                album=album,
                provider_mappings={
                    ProviderMapping(
                        item_id=song_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(images=images),
                disc_number=song_data.get("disc", 1),
                track_number=song_data.get("trackNo", 1),
            )
        except Exception as err:
            _LOGGER.error("Error parsing track from search: %s", err)
            return None

    async def _parse_album_from_search(self, album_data: dict[str, Any]) -> Album | None:
        """Parse Album from search result."""
        try:
            album_id = str(album_data["id"])
            name = album_data.get("name", "Unknown Album")
            artists = UniqueList[Artist]()
            if "artist" in album_data:
                artist_data = album_data["artist"]
                artist_id = str(artist_data["id"])
                artist_name = artist_data.get("name", "Unknown Artist")
                artists.append(
                    Artist(
                        item_id=artist_id,
                        provider=self.instance_id,
                        name=artist_name,
                        provider_mappings={
                            ProviderMapping(
                                item_id=artist_id,
                                provider_domain=self.domain,
                                provider_instance=self.instance_id,
                            )
                        },
                    )
                )

            images = self._build_images([album_data.get("picUrl")] if album_data.get("picUrl") else None)

            return Album(
                item_id=album_id,
                provider=self.instance_id,
                name=name,
                artists=artists,
                provider_mappings={
                    ProviderMapping(
                        item_id=album_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(images=images),
                year=album_data.get("publishTime", 0) // 10000 if album_data.get("publishTime") else None,
            )
        except Exception as err:
            _LOGGER.error("Error parsing album from search: %s", err)
            return None

    async def _parse_artist_from_search(self, artist_data: dict[str, Any]) -> Artist | None:
        """Parse Artist from search result."""
        try:
            artist_id = str(artist_data["id"])
            name = artist_data.get("name", "Unknown Artist")
            # Try multiple possible fields for artist image
            pic_url = (
                artist_data.get("picUrl")
                or artist_data.get("img1v1Url")
                or artist_data.get("cover")
            )
            images = self._build_images([pic_url] if pic_url else None)

            return Artist(
                item_id=artist_id,
                provider=self.instance_id,
                name=name,
                provider_mappings={
                    ProviderMapping(
                        item_id=artist_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(images=images),
            )
        except Exception as err:
            _LOGGER.error("Error parsing artist from search: %s", err)
            return None

    async def _parse_playlist_from_search(self, playlist_data: dict[str, Any]) -> Playlist | None:
        """Parse Playlist from search result."""
        try:
            from music_assistant_models.media_items import Playlist

            playlist_id = str(playlist_data["id"])
            name = playlist_data.get("name", "Unknown Playlist")
            images = self._build_images([playlist_data.get("coverImgUrl")] if playlist_data.get("coverImgUrl") else None)

            return Playlist(
                item_id=playlist_id,
                provider=self.instance_id,
                name=name,
                provider_mappings={
                    ProviderMapping(
                        item_id=playlist_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(
                    images=images,
                    description=playlist_data.get("description", ""),
                ),
                is_editable=False,  # Netease playlists are typically not editable by users
            )
        except Exception as err:
            _LOGGER.error("Error parsing playlist from search: %s", err)
            return None

    async def _parse_radio_from_search(self, program_data: dict[str, Any]) -> Radio | None:
        """Parse Radio from search result (using program data)."""
        try:
            from music_assistant_models.media_items import Radio

            program_id = str(program_data["id"])
            name = program_data.get("name", "Unknown Radio Program")
            images = self._build_images([program_data.get("coverUrl")] if program_data.get("coverUrl") else None)

            # Get radio station info
            radio_station_id = str(program_data.get("radio", {}).get("id", ""))
            radio_station = None
            if radio_station_id:
                try:
                    radio_station_data = await self._request("/dj/detail", params={"rid": radio_station_id})
                    if radio_station_data and "data" in radio_station_data:
                        radio_station = radio_station_data["data"].get("name", "Unknown Station")
                except Exception:
                    radio_station = "Unknown Station"

            return Radio(
                item_id=program_id,
                provider=self.instance_id,
                name=name,
                provider_mappings={
                    ProviderMapping(
                        item_id=program_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(
                    images=images,
                    description=program_data.get("description", ""),
                ),
                owner=radio_station,
            )
        except Exception as err:
            _LOGGER.error("Error parsing radio from search: %s", err)
            return None

    async def _parse_podcast_from_search(self, radio_data: dict[str, Any]) -> Podcast | None:
        """Parse Podcast from search result (using radio data)."""
        try:
            radio_id = str(radio_data["id"])
            name = radio_data.get("name", "Unknown Radio")
            images = self._build_images([radio_data.get("picUrl")] if radio_data.get("picUrl") else None)

            return Podcast(
                item_id=radio_id,
                provider=self.instance_id,
                name=name,
                provider_mappings={
                    ProviderMapping(
                        item_id=radio_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(
                    images=images,
                    description=radio_data.get("desc", ""),
                ),
                publisher=radio_data.get("dj", {}).get("nickname", "Unknown Publisher"),
            )
        except Exception as err:
            _LOGGER.error("Error parsing podcast from search: %s", err)
            return None

    async def get_track(self, prov_track_id: str) -> Track:
        """Get full track details by id."""
        data = await self._request("/song/detail", params={"ids": prov_track_id})
        if not data or "songs" not in data or not data["songs"]:
            msg = f"Track {prov_track_id} not found"
            raise ValueError(msg)

        song_data = data["songs"][0]
        song_id = str(song_data["id"])
        name = song_data.get("name", "Unknown")
        duration = song_data.get("dt", 0) // 1000

        # Parse artists
        artists = UniqueList[Artist]()
        if "ar" in song_data:
            for artist_data in song_data["ar"]:
                artist_id = str(artist_data["id"])
                artist_name = artist_data.get("name", "Unknown Artist")
                artists.append(await self.get_artist(artist_id))

        # Parse album
        album: Album | ItemMapping | None = None
        if "al" in song_data:
            album_data = song_data["al"]
            album_id = str(album_data["id"])
            album = await self.get_album(album_id)

        # Build images: try song's picUrl first, then album's
        song_pic_url = song_data.get("picUrl")
        album_pic_url = song_data.get("al", {}).get("picUrl")
        cover_url = song_pic_url or album_pic_url
        images = self._build_images([cover_url] if cover_url else None)

        return Track(
            item_id=song_id,
            provider=self.instance_id,
            name=name,
            duration=duration,
            artists=artists,
            album=album,
            provider_mappings={
                ProviderMapping(
                    item_id=song_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(images=images),
            disc_number=song_data.get("cd", 1),
            track_number=song_data.get("no", 1),
        )

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get full artist details by id."""
        # Get artist detail which includes basic info and description
        data = await self._request("/artist/detail", params={"id": prov_artist_id})
        if not data or "data" not in data:
            msg = f"Artist {prov_artist_id} not found"
            raise ValueError(msg)

        artist_data = data["data"]["artist"]
        artist_id = str(artist_data["id"])
        name = artist_data.get("name", "Unknown Artist")
        
        # Get artist picUrl - try multiple possible fields
        pic_url = (
            artist_data.get("picUrl")
            or artist_data.get("img1v1Url")
            or artist_data.get("cover")
        )
        images = self._build_images([pic_url] if pic_url else None)

        return Artist(
            item_id=artist_id,
            provider=self.instance_id,
            name=name,
            provider_mappings={
                ProviderMapping(
                    item_id=artist_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=artist_data.get("briefDesc", ""),
            ),
        )

    async def get_album(self, prov_album_id: str) -> Album:
        """Get full album details by id."""
        data = await self._request("/album", params={"id": prov_album_id})
        if not data or "album" not in data:
            msg = f"Album {prov_album_id} not found"
            raise ValueError(msg)

        album_data = data["album"]
        album_id = str(album_data["id"])
        name = album_data.get("name", "Unknown Album")

        # Parse artists
        artists = UniqueList[Artist]()
        if "artists" in album_data:
            for artist_data in album_data["artists"]:
                artist_id = str(artist_data["id"])
                artists.append(await self.get_artist(artist_id))

        # Build images: try album's picUrl first, then from first song if available
        album_pic_url = album_data.get("picUrl")
        if not album_pic_url and "songs" in album_data and album_data["songs"]:
            # Try to get picUrl from the first song
            first_song = album_data["songs"][0]
            album_pic_url = first_song.get("picUrl") or first_song.get("al", {}).get("picUrl")
        images = self._build_images([album_pic_url] if album_pic_url else None)

        return Album(
            item_id=album_id,
            provider=self.instance_id,
            name=name,
            artists=artists,
            provider_mappings={
                ProviderMapping(
                    item_id=album_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=album_data.get("description", ""),
            ),
            year=album_data.get("publishTime", 0) // 10000 if album_data.get("publishTime") else None,
        )

    async def get_podcast(self, prov_podcast_id: str) -> Podcast:
        """Get full podcast details by id (using radio API)."""
        data = await self._request("/dj/detail", params={"rid": prov_podcast_id})
        if not data or "data" not in data:
            msg = f"Podcast {prov_podcast_id} not found"
            raise ValueError(msg)

        radio_data = data["data"]
        radio_id = str(radio_data["id"])
        name = radio_data.get("name", "Unknown Radio")
        images = self._build_images([radio_data.get("picUrl")] if radio_data.get("picUrl") else None)

        return Podcast(
            item_id=radio_id,
            provider=self.instance_id,
            name=name,
            provider_mappings={
                ProviderMapping(
                    item_id=radio_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=radio_data.get("desc", ""),
            ),
            publisher=radio_data.get("dj", {}).get("nickname", "Unknown Publisher"),
        )

    async def get_audiobook(self, prov_audiobook_id: str) -> Audiobook:
        """Get full audiobook details by id (using radio API for now)."""
        # Note: NeteaseCloudMusicApi might have specific audiobook endpoints
        # For now, we'll use the radio/dj endpoint as a fallback
        data = await self._request("/dj/detail", params={"rid": prov_audiobook_id})
        if not data or "data" not in data:
            msg = f"Audiobook {prov_audiobook_id} not found"
            raise ValueError(msg)

        radio_data = data["data"]
        radio_id = str(radio_data["id"])
        name = radio_data.get("name", "Unknown Audiobook")
        images = self._build_images([radio_data.get("picUrl")] if radio_data.get("picUrl") else None)

        return Audiobook(
            item_id=radio_id,
            provider=self.instance_id,
            name=name,
            provider_mappings={
                ProviderMapping(
                    item_id=radio_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=radio_data.get("desc", ""),
            ),
            publisher=radio_data.get("dj", {}).get("nickname", "Unknown Publisher"),
            authors=UniqueList([radio_data.get("dj", {}).get("nickname", "Unknown Author")]),
            duration=0,  # Will be calculated from episodes if available
        )

    async def get_podcast_episodes(
        self,
        prov_podcast_id: str,
    ) -> AsyncGenerator[PodcastEpisode, None]:
        """Get all PodcastEpisodes for given podcast id."""
        # Use /dj/program to get radio programs
        data = await self._request("/dj/program", params={"rid": prov_podcast_id, "limit": 100})
        if not data or "programs" not in data:
            return

        podcast = await self.get_podcast(prov_podcast_id)
        for idx, program_data in enumerate(data["programs"], start=1):
            episode = await self._parse_podcast_episode(program_data, podcast)
            if episode:
                yield episode

    async def _parse_podcast_episode(self, program_data: dict[str, Any], podcast: Podcast) -> PodcastEpisode | None:
        """Parse PodcastEpisode from program data."""
        try:
            episode_id = str(program_data["id"])
            name = program_data.get("name", "Unknown Episode")
            duration = program_data.get("duration", 0) // 1000

            images = self._build_images([program_data.get("coverUrl")] if program_data.get("coverUrl") else None)

            return PodcastEpisode(
                item_id=episode_id,
                provider=self.instance_id,
                name=name,
                duration=duration,
                podcast=ItemMapping(
                    item_id=podcast.item_id,
                    provider=podcast.provider,
                    name=podcast.name,
                    media_type=MediaType.PODCAST,
                    image=podcast.metadata.images[0] if podcast.metadata.images else None,
                ),
                provider_mappings={
                    ProviderMapping(
                        item_id=episode_id,
                        provider_domain=self.domain,
                        provider_instance=self.instance_id,
                    )
                },
                metadata=MediaItemMetadata(
                    images=images,
                    description=program_data.get("description", ""),
                ),
                position=program_data.get("serialNum", 0),
            )
        except Exception as err:
            _LOGGER.error("Error parsing podcast episode: %s", err)
            return None

    async def get_podcast_episode(self, prov_episode_id: str) -> PodcastEpisode:
        """Get (full) podcast episode details by id."""
        data = await self._request("/dj/program/detail", params={"id": prov_episode_id})
        if not data or "program" not in data:
            msg = f"Podcast episode {prov_episode_id} not found"
            raise ValueError(msg)

        program_data = data["program"]
        episode_id = str(program_data["id"])
        name = program_data.get("name", "Unknown Episode")
        duration = program_data.get("duration", 0) // 1000

        # Get podcast info
        radio_id = str(program_data.get("radio", {}).get("id", ""))
        podcast = await self.get_podcast(radio_id) if radio_id else None

        images = self._build_images([program_data.get("coverUrl")] if program_data.get("coverUrl") else None)

        return PodcastEpisode(
            item_id=episode_id,
            provider=self.instance_id,
            name=name,
            duration=duration,
            podcast=ItemMapping(
                item_id=podcast.item_id,
                provider=podcast.provider,
                name=podcast.name,
                media_type=MediaType.PODCAST,
                image=podcast.metadata.images[0] if podcast and podcast.metadata.images else None,
            )
            if podcast
            else None,
            provider_mappings={
                ProviderMapping(
                    item_id=episode_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=program_data.get("description", ""),
            ),
            position=program_data.get("serialNum", 0),
        )

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Get streamdetails for a track/podcast episode."""
        if media_type == MediaType.TRACK:
            # First try unblock API if configured
            if self._unblock_api_url:
                unblock_data = await self._request_unblock_api(item_id)
                if unblock_data and unblock_data.get("audioUrl"):
                    _LOGGER.info("Using unblocked URL for track %s from source: %s", item_id, unblock_data.get("source"))
                    return StreamDetails(
                        provider=self.instance_id,
                        item_id=item_id,
                        audio_format=AudioFormat(
                            content_type=ContentType.FLAC if unblock_data.get("type") == "flac" else ContentType.MP3,
                            sample_rate=44100,
                            bit_depth=16,
                            channels=2,
                        ),
                        media_type=media_type,
                        stream_type=StreamType.HTTP,
                        path=unblock_data["audioUrl"],
                        can_seek=True,
                        allow_seek=True,
                    )

            # Fallback to original API
            data = await self._request("/song/url/v1", params={"id": item_id, "level": "hires"})
            if data and "data" in data and data["data"]:
                song_url_data = data["data"][0]
                url = song_url_data.get("url")
                if url:
                    _LOGGER.debug("Using original URL for track %s", item_id)
                    return StreamDetails(
                        provider=self.instance_id,
                        item_id=item_id,
                        audio_format=AudioFormat(
                            content_type=ContentType.MP3,
                            sample_rate=44100,
                            bit_depth=16,
                            channels=2,
                        ),
                        media_type=media_type,
                        stream_type=StreamType.HTTP,
                        path=url,
                        can_seek=True,
                        allow_seek=True,
                    )
        elif media_type == MediaType.PODCAST:
            # For podcast episodes, we might need to get the program detail first
            # and then extract the audio URL
            # This is a simplified version - you may need to adjust based on actual API response
            data = await self._request("/dj/program/detail", params={"id": item_id})
            if data and "program" in data:
                program_data = data["program"]
                # Try to get the main song URL if available
                main_song_id = program_data.get("mainSong", {}).get("id")
                if main_song_id:
                    return await self.get_stream_details(str(main_song_id), MediaType.TRACK)

        msg = f"Could not get stream URL for {item_id}"
        raise ValueError(msg)

    async def get_artist_albums(self, prov_artist_id: str) -> list[Album]:
        """Get a list of albums for the given artist."""
        data = await self._request("/artist/album", params={"id": prov_artist_id, "limit": 50})
        if not data or "hotAlbums" not in data:
            return []

        albums = []
        for album_data in data["hotAlbums"]:
            try:
                album_id = str(album_data["id"])
                album_name = album_data.get("name", "Unknown Album")

                # Parse artists - create minimal objects without fetching full details for speed
                artists = UniqueList[Artist]()
                if "artists" in album_data:
                    for artist_info in album_data["artists"]:
                        artist_id = str(artist_info["id"])
                        artist_name = artist_info.get("name", "Unknown Artist")
                        artists.append(
                            Artist(
                                item_id=artist_id,
                                provider=self.instance_id,
                                name=artist_name,
                                provider_mappings={
                                    ProviderMapping(
                                        item_id=artist_id,
                                        provider_domain=self.domain,
                                        provider_instance=self.instance_id,
                                    )
                                },
                            )
                        )

                images = self._build_images([album_data.get("picUrl")] if album_data.get("picUrl") else None)

                albums.append(
                    Album(
                        item_id=album_id,
                        provider=self.instance_id,
                        name=album_name,
                        artists=artists,
                        provider_mappings={
                            ProviderMapping(
                                item_id=album_id,
                                provider_domain=self.domain,
                                provider_instance=self.instance_id,
                            )
                        },
                        metadata=MediaItemMetadata(images=images),
                        year=album_data.get("publishTime", 0) // 10000 if album_data.get("publishTime") else None,
                    )
                )
            except Exception as err:
                _LOGGER.error("Error parsing artist album: %s", err)
                continue

        return albums

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Get all tracks for a given album."""
        _LOGGER.info(f"get_album_tracks called for album ID: {prov_album_id}")

        data = await self._request("/album", params={"id": prov_album_id})
        _LOGGER.info(f"Album API response: {data}")

        if not data:
            _LOGGER.warning(f"No data returned from album API for ID: {prov_album_id}")
            return []

        if "album" not in data:
            _LOGGER.warning(f"No 'album' key in response for ID: {prov_album_id}. Keys: {list(data.keys())}")
            return []

        songs = data.get("songs", [])
        _LOGGER.info(f"Found {len(songs)} songs in album response")

        if not songs:
            _LOGGER.warning(f"No songs found in album {prov_album_id}")
            return []

        tracks = []

        # Batch fetch track details for accurate cover images
        track_ids = [str(song["id"]) for song in songs]
        _LOGGER.info(f"Batch fetching details for {len(track_ids)} tracks")
        track_details = await self._batch_fetch_track_details(track_ids)

        for song_data in songs:
            _LOGGER.info(f"Processing song: {song_data.get('name', 'Unknown')}")
            track = await self._parse_track_from_search(song_data, track_details.get(str(song_data["id"])))
            if track:
                tracks.append(track)
                _LOGGER.info(f"Successfully created track: {track.name}")
            else:
                _LOGGER.warning(f"Failed to create track for song: {song_data.get('name', 'Unknown')}")

        _LOGGER.info(f"Returning {len(tracks)} tracks for album {prov_album_id}")
        return tracks

    # Library methods - return empty for now as this is a streaming provider
    async def get_library_artists(self) -> AsyncGenerator[Artist, None]:
        """Retrieve library artists from the provider."""
        _LOGGER.info("get_library_artists called - returning popular/hot artists as library")

        # For streaming provider, return popular/hot artists as library
        _LOGGER.info("Requesting top artists from API: /top/artists with limit=50")
        data = await self._request("/top/artists", params={"limit": 50, "offset": 0})

        if not data:
            _LOGGER.warning("No data returned from /top/artists API")
            return

        if "artists" not in data:
            _LOGGER.warning(f"No 'artists' key in API response. Response keys: {list(data.keys())}")
            return

        artists_list = data["artists"]
        _LOGGER.info(f"Received {len(artists_list)} artists from API")

        count = 0
        for artist_data in artists_list:
            artist_name = artist_data.get("name", "Unknown")
            artist_id = artist_data.get("id", "Unknown")

            _LOGGER.debug(f"Processing artist: {artist_name} (ID: {artist_id})")

            artist = await self._parse_artist_from_search(artist_data)
            if artist:
                count += 1
                _LOGGER.debug(f"Successfully yielded artist {count}: {artist.name}")
                yield artist
            else:
                _LOGGER.warning(f"Failed to parse artist: {artist_name}")

        _LOGGER.info(f"Total yielded {count} artists from get_library_artists")

    async def get_library_albums(self) -> AsyncGenerator[Album, None]:
        """Retrieve library albums from the provider."""
        _LOGGER.info("get_library_albums called - returning newest albums as library")

        # Use /album/newest API to get the latest albums
        _LOGGER.info("Requesting newest albums from API: /album/newest")
        data = await self._request("/album/newest", params={})

        if not data or "albums" not in data:
            _LOGGER.warning("No albums data returned from /album/newest API")
            return

        albums_list = data["albums"]
        _LOGGER.info(f"Received {len(albums_list)} newest albums from API")

        count = 0
        for album_data in albums_list:
            album_name = album_data.get("name", "Unknown Album")
            album_id = str(album_data.get("id", ""))

            _LOGGER.debug(f"Processing newest album: {album_name} (ID: {album_id})")

            # Parse album
            album = await self._parse_album_from_search(album_data)
            if album:
                count += 1
                _LOGGER.debug(f"Successfully yielded album {count}: {album.name}")
                yield album
            else:
                _LOGGER.warning(f"Failed to parse album: {album_name}")

        _LOGGER.info(f"Total yielded {count} albums from get_library_albums")

    async def get_library_tracks(self) -> AsyncGenerator[Track, None]:
        """Retrieve library tracks from the provider."""
        _LOGGER.info("get_library_tracks called - returning popular tracks as library")

        # For streaming provider, return popular tracks as library
        # We'll get tracks from top playlists
        _LOGGER.info("Requesting top playlists from API to get popular tracks")
        data = await self._request("/top/playlist", params={"limit": 10, "offset": 0, "cat": "全部"})

        if not data or "playlists" not in data:
            _LOGGER.warning("No playlists data returned from /top/playlist API")
            return

        playlists = data["playlists"][:3]  # Limit to 3 playlists
        _LOGGER.info(f"Processing {len(playlists)} top playlists for tracks")

        count = 0
        for playlist in playlists:
            playlist_id = str(playlist["id"])
            _LOGGER.debug(f"Getting tracks from playlist: {playlist_id}")

            # Get playlist details to extract tracks
            playlist_data = await self._request("/playlist/detail", params={"id": playlist_id})
            if not playlist_data or "playlist" not in playlist_data:
                continue

            tracks_data = playlist_data["playlist"].get("tracks", [])[:5]  # Limit tracks per playlist
            _LOGGER.debug(f"Found {len(tracks_data)} tracks in playlist {playlist_id}")

            for track_data in tracks_data:
                track_id = str(track_data["id"])
                track_name = track_data.get("name", "Unknown")

                _LOGGER.debug(f"Processing track: {track_name} (ID: {track_id})")

                # Parse track
                track = await self._parse_track_from_search(track_data)
                if track:
                    count += 1
                    _LOGGER.debug(f"Successfully yielded track {count}: {track.name}")
                    yield track

                    # Limit total tracks returned
                    if count >= 30:
                        _LOGGER.info("Reached track limit (30), stopping")
                        return

        _LOGGER.info(f"Total yielded {count} tracks from get_library_tracks")

    async def get_library_podcasts(self) -> AsyncGenerator[Podcast, None]:
        """Retrieve library podcasts from the provider."""
        _LOGGER.info("get_library_podcasts called - returning popular podcasts/radio as library")

        # For streaming provider, return popular radio/podcasts as library
        _LOGGER.info("Requesting hot radios from API: /dj/hot with limit=20")
        data = await self._request("/dj/hot", params={"limit": 20, "offset": 0})

        if not data or "djRadios" not in data:
            _LOGGER.warning("No djRadios data returned from /dj/hot API")
            return

        radios_list = data["djRadios"]
        _LOGGER.info(f"Received {len(radios_list)} radios from API")

        count = 0
        for radio_data in radios_list[:20]:  # Limit to 20
            radio_name = radio_data.get("name", "Unknown Radio")
            radio_id = str(radio_data.get("id", ""))

            _LOGGER.debug(f"Processing radio: {radio_name} (ID: {radio_id})")

            # Parse podcast/radio
            podcast = await self._parse_podcast_from_search(radio_data)
            if podcast:
                count += 1
                _LOGGER.debug(f"Successfully yielded podcast {count}: {podcast.name}")
                yield podcast
            else:
                _LOGGER.warning(f"Failed to parse radio: {radio_name}")

        _LOGGER.info(f"Total yielded {count} podcasts from get_library_podcasts")

    async def get_library_audiobooks(self) -> AsyncGenerator[Audiobook, None]:
        """Retrieve library audiobooks from the provider."""
        _LOGGER.info("get_library_audiobooks called - returning popular audiobooks/radio as library")

        # For streaming provider, return popular radio/audiobooks as library
        # We'll use the same radio API as podcasts but treat them as audiobooks
        _LOGGER.info("Requesting hot radios from API: /dj/hot with limit=15")
        data = await self._request("/dj/hot", params={"limit": 15, "offset": 0})

        if not data or "djRadios" not in data:
            _LOGGER.warning("No djRadios data returned from /dj/hot API")
            return

        radios_list = data["djRadios"]
        _LOGGER.info(f"Received {len(radios_list)} radios from API")

        count = 0
        for radio_data in radios_list[:15]:  # Limit to 15
            radio_name = radio_data.get("name", "Unknown Radio")
            radio_id = str(radio_data.get("id", ""))

            _LOGGER.debug(f"Processing radio as audiobook: {radio_name} (ID: {radio_id})")

            # Parse audiobook/radio - reuse podcast parsing logic but create Audiobook objects
            try:
                audiobook = Audiobook(
                    item_id=radio_id,
                    provider=self.instance_id,
                    name=radio_name,
                    provider_mappings={
                        ProviderMapping(
                            item_id=radio_id,
                            provider_domain=self.domain,
                            provider_instance=self.instance_id,
                        )
                    },
                    metadata=MediaItemMetadata(
                        images=self._build_images([radio_data.get("picUrl")] if radio_data.get("picUrl") else None),
                        description=radio_data.get("desc", ""),
                    ),
                    publisher=radio_data.get("dj", {}).get("nickname", "Unknown Publisher"),
                    authors=UniqueList([radio_data.get("dj", {}).get("nickname", "Unknown Author")]),
                    duration=0,  # Will be calculated from episodes if available
                )

                count += 1
                _LOGGER.debug(f"Successfully yielded audiobook {count}: {audiobook.name}")
                yield audiobook
            except Exception as err:
                _LOGGER.warning(f"Failed to parse radio as audiobook: {radio_name}, error: {err}")

        _LOGGER.info(f"Total yielded {count} audiobooks from get_library_audiobooks")

    async def get_library_radios(self) -> AsyncGenerator[Radio, None]:
        """Retrieve library radios from the provider."""
        _LOGGER.info("get_library_radios called - returning recommended radio programs")

        # Use /program/recommend API to get recommended radio programs
        _LOGGER.info("Requesting recommended radio programs from API: /program/recommend")
        data = await self._request("/program/recommend", params={})

        if not data or "programs" not in data:
            _LOGGER.warning("No programs data returned from /program/recommend API")
            return

        programs_list = data["programs"]
        _LOGGER.info(f"Received {len(programs_list)} recommended radio programs from API")

        count = 0
        for program_data in programs_list:
            program_name = program_data.get("name", "Unknown Radio Program")
            program_id = str(program_data.get("id", ""))

            _LOGGER.debug(f"Processing radio program: {program_name} (ID: {program_id})")

            # Parse radio program
            radio = await self._parse_radio_from_search(program_data)
            if radio:
                count += 1
                _LOGGER.debug(f"Successfully yielded radio {count}: {radio.name}")
                yield radio
            else:
                _LOGGER.warning(f"Failed to parse radio program: {program_name}")

        _LOGGER.info(f"Total yielded {count} radio programs from get_library_radios")

    async def get_playlist(self, prov_playlist_id: str) -> Playlist:
        """Get full playlist details by id."""
        # Use /playlist/detail to get playlist details
        data = await self._request("/playlist/detail", params={"id": prov_playlist_id})
        if not data or "playlist" not in data:
            msg = f"Playlist {prov_playlist_id} not found"
            raise ValueError(msg)

        playlist_data = data["playlist"]
        playlist_id = str(playlist_data["id"])
        name = playlist_data.get("name", "Unknown Playlist")
        
        # Get playlist owner
        creator_data = playlist_data.get("creator", {})
        owner = creator_data.get("nickname", "Unknown Owner")

        images = self._build_images([playlist_data.get("coverImgUrl")] if playlist_data.get("coverImgUrl") else None)

        return Playlist(
            item_id=playlist_id,
            provider=self.instance_id,
            name=name,
            provider_mappings={
                ProviderMapping(
                    item_id=playlist_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=playlist_data.get("description", ""),
            ),
            owner=owner,
            is_editable=False,  # Netease playlists are typically not editable by users
        )

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get full radio details by id."""
        # Use /dj/program/detail to get radio program details
        data = await self._request("/dj/program/detail", params={"id": prov_radio_id})
        if not data or "program" not in data:
            msg = f"Radio program {prov_radio_id} not found"
            raise ValueError(msg)

        program_data = data["program"]
        program_id = str(program_data["id"])
        name = program_data.get("name", "Unknown Radio Program")
        
        # Get radio station info
        radio_station_id = str(program_data.get("radio", {}).get("id", ""))
        radio_station = await self.get_podcast(radio_station_id) if radio_station_id else None

        images = self._build_images([program_data.get("coverUrl")] if program_data.get("coverUrl") else None)

        return Radio(
            item_id=program_id,
            provider=self.instance_id,
            name=name,
            provider_mappings={
                ProviderMapping(
                    item_id=program_id,
                    provider_domain=self.domain,
                    provider_instance=self.instance_id,
                )
            },
            metadata=MediaItemMetadata(
                images=images,
                description=program_data.get("description", ""),
            ),
            owner=radio_station.name if radio_station else "Unknown Station",
        )

    async def get_popular_artists(self, limit: int = 50) -> AsyncGenerator[Artist, None]:
        """Get popular/hot artists from Netease Cloud Music."""
        data = await self._request("/top/artists", params={"limit": limit, "offset": 0})
        if not data or "artists" not in data:
            return

        for artist_data in data["artists"]:
            artist = await self._parse_artist_from_search(artist_data)
            if artist:
                yield artist
