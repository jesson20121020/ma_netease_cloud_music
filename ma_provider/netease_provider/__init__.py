"""Netease Cloud Music provider that integrates with NeteaseCloudMusicApi."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.errors import MediaNotFoundError, ResourceTemporarilyUnavailable
from music_assistant_models.enums import (
    ConfigEntryType,
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.media_items import (
    Playlist,
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
CONF_KEY_COOKIE = "cookie"
# comma separated Netease chart names to add to the library (见 https://music.163.com/#/discover/toplist)
CONF_KEY_CHARTS = "charts"
DEFAULT_CHARTS = "飙升榜,新歌榜,热歌榜,原创榜"
# how many hot artists / hot (= newly released, all areas) albums to publish into the library
CONF_KEY_HOT_ARTISTS = "hot_artists"
CONF_KEY_HOT_ALBUMS = "hot_albums"
DEFAULT_HOT_ARTISTS = 50
DEFAULT_HOT_ALBUMS = 50

# address a NeteaseCloudMusicApi backend listens on by default
DEFAULT_API_URL = "http://localhost:3000"

# The Netease upstream throttles us ("操作频繁，请稍候再试", HTTP 405) when Music Assistant
# refreshes a large library, which issues a search per item. An anonymous Netease session
# (the NeteaseCloudMusicApi default) has a very small quota, so:
#   * never issue two requests back to back (REQUEST_MIN_INTERVAL),
#   * after a throttled answer pause ALL requests for an exponentially growing time
#     (RATE_LIMIT_BACKOFF, capped at RATE_LIMIT_BACKOFF_MAX),
#   * retry the throttled request itself up to RATE_LIMIT_RETRIES times, and only then
#     report a temporary failure instead of pretending the item does not exist.
RATE_LIMIT_BACKOFF = 15.0
RATE_LIMIT_BACKOFF_MAX = 120.0
RATE_LIMIT_RETRIES = 2
REQUEST_MIN_INTERVAL = 0.35
RATE_LIMIT_STATUS_CODES = (405, 429)

# Music Assistant only waits SEARCH_PROVIDER_SOFT_TIMEOUT (8s) for a provider search and
# then drops that provider from the answer; the frontend retries an empty provider answer
# a couple of times and afterwards keeps it until the search term changes. Sitting out a
# (15s..120s) rate-limit pause therefore turns a throttled search into "no results" for
# that term, so never block longer than this: raise ResourceTemporarilyUnavailable instead
# and let Music Assistant (and the frontend) retry later.
MAX_WAIT_FOR_RATE_LIMIT = 3.0

# NeteaseCloudMusicApi search types
# 1: 单曲, 10: 专辑, 100: 歌手, 1000: 歌单, 1009: 电台, 1014: 视频
NETEASE_SEARCH_TYPE_SONG = 1
NETEASE_SEARCH_TYPE_ALBUM = 10
NETEASE_SEARCH_TYPE_ARTIST = 100
NETEASE_SEARCH_TYPE_PLAYLIST = 1000
NETEASE_SEARCH_TYPE_RADIO = 1009

# Netease blocks the legacy /search interface for a while after a burst of requests
# ("操作频繁，请稍候再试", HTTP 405) while /cloudsearch keeps answering. /cloudsearch returns
# the exact same `result.songs|albums|artists|playlists` payload, so use it for searching.
NETEASE_SEARCH_ENDPOINT = "/cloudsearch"

SUPPORTED_FEATURES = {
    ProviderFeature.SEARCH,
    ProviderFeature.BROWSE,
    ProviderFeature.LIBRARY_ARTISTS,
    ProviderFeature.LIBRARY_ALBUMS,
    ProviderFeature.LIBRARY_TRACKS,
    ProviderFeature.LIBRARY_PLAYLISTS,
    ProviderFeature.ARTIST_ALBUMS,
    ProviderFeature.ARTIST_TOPTRACKS,
    ProviderFeature.PLAYLIST_CREATE,
    ProviderFeature.PLAYLIST_TRACKS_EDIT,
    ProviderFeature.LYRICS,
}


# Set-Cookie attributes that may be pasted together with the cookie value (the API's
# /login/* responses return "MUSIC_U=...; Max-Age=...; Expires=...; Path=/; __csrf=...").
# They are not part of the cookie the NeteaseCloudMusicApi expects as a request parameter.
_COOKIE_ATTRIBUTES = {"expires", "max-age", "path", "domain", "secure", "httponly", "samesite"}


def _clean_cookie(raw: str) -> str:
    """Drop Set-Cookie attributes and duplicate names from a pasted cookie string."""
    seen: dict[str, str] = {}
    for item in raw.replace(";;", ";").split(";"):
        name, sep, value = item.strip().partition("=")
        name = name.strip()
        if not sep or not name or name.lower() in _COOKIE_ATTRIBUTES:
            continue
        value = value.strip()
        if not value:
            # an empty MUSIC_U (logged-out browser, or a truncated copy) makes Netease treat
            # the whole thing as an anonymous session
            continue
        seen[name] = value
    return "; ".join(f"{name}={value}" for name, value in seen.items())


def _as_count(raw: Any, default: int) -> int:
    """Return a non-negative integer config value (0 disables the feature)."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def _parse_chart_names(raw: Any) -> list[str]:
    """
    Split a comma/顿号/slash separated chart name list into unique names.

    The single token ``all`` (``*`` / ``全部``) means "every chart Netease publishes"
    and is returned as ``["*"]``.
    """
    text = str(raw or "").replace("，", ",").replace("、", ",").replace("/", ",")
    names: list[str] = []
    for part in text.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    if len(names) == 1 and names[0].lower() in {"all", "*", "全部", "所有"}:
        return ["*"]
    return names


def _payload_list(payload: Any, *keys: str) -> list[dict[str, Any]]:
    """Return the first list found under the given keys of an API payload."""
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _minimal_cookie(raw: str) -> str:
    """
    Return the smallest cookie Music Assistant needs: MUSIC_U plus (optionally) __csrf.

    Browsers hand out a whole pile of cookies, and the NeteaseCloudMusicApi forwards them
    verbatim; a stale/conflicting guest cookie in that pile can make the backend keep the
    anonymous session even though MUSIC_U is valid.
    """
    keep = {"MUSIC_U", "__csrf"}
    parts = [
        part
        for part in _clean_cookie(raw).split("; ")
        if part and part.partition("=")[0] in keep and part.partition("=")[2]
    ]
    return "; ".join(parts)


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

    Kept for Music Assistant versions that still resolve this module-level hook (the
    current server resolves the instance method ``NeteaseProvider.get_config_entries``
    instead, and collects the addresses through ``setup_flow.py``).

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
            default_value=DEFAULT_API_URL,
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
        ConfigEntry(
            key=CONF_KEY_COOKIE,
            type=ConfigEntryType.SECURE_STRING,
            label="登录 Cookie（可选）",
            description="登录后的 cookie，可显著提高接口配额（避免 405 操作频繁）并访问账号歌单；留空使用匿名会话",
            default_value="",
            required=False,
        ),
    )


class NeteaseProvider(MusicProvider):
    """Netease Cloud Music provider implementation."""

    _api_url: str
    _unblock_api_url: str | None
    _cookie: str | None
    _http_client: httpx.AsyncClient
    _rate_limited_until: float
    _rate_limit_strikes: int
    _uid: str | None
    _charts: list[str]
    _hot_artists: int
    _hot_albums: int
    _last_request_at: float
    _request_lock: asyncio.Lock

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """
        Return the (options) config entries for this provider instance.

        The API addresses are collected by the setup flow (setup_flow.py) and stored as the
        instance's setup data. The entries below exist so addresses stored by earlier
        versions of this provider - which kept them as plain option values - are still read
        back on load. They are hidden from the UI: change an address through the provider's
        reconfigure flow, which is also what a fresh install uses.
        """
        return (
            ConfigEntry(
                key=CONF_KEY_API_URL,
                type=ConfigEntryType.STRING,
                default_value=DEFAULT_API_URL,
                required=True,
                hidden=True,
            ),
            ConfigEntry(
                key=CONF_KEY_UNBLOCK_API_URL,
                type=ConfigEntryType.STRING,
                default_value="",
                required=False,
                hidden=True,
            ),
            ConfigEntry(
                key=CONF_KEY_COOKIE,
                type=ConfigEntryType.SECURE_STRING,
                default_value="",
                required=False,
                hidden=True,
            ),
            ConfigEntry(
                key=CONF_KEY_HOT_ARTISTS,
                type=ConfigEntryType.INTEGER,
                label="同步热门歌手数量",
                description=(
                    "取网易云歌手榜（热门歌手）前 N 位加入媒体库；0 = 不同步。"
                    "登录后还会额外包含你关注的歌手"
                ),
                default_value=DEFAULT_HOT_ARTISTS,
                required=False,
            ),
            ConfigEntry(
                key=CONF_KEY_HOT_ALBUMS,
                type=ConfigEntryType.INTEGER,
                label="同步热门专辑数量",
                description=(
                    "取网易云「新碟上架」全部地区前 N 张加入媒体库；0 = 不同步。"
                    "登录后还会额外包含你收藏的专辑"
                ),
                default_value=DEFAULT_HOT_ALBUMS,
                required=False,
            ),
            ConfigEntry(
                key=CONF_KEY_CHARTS,
                type=ConfigEntryType.STRING,
                label="同步的榜单歌单",
                description=(
                    "逗号分隔的榜单名，会把网易云的榜单歌单一起同步进媒体库；留空则不同步。"
                    "名字取自 https://music.163.com/#/discover/toplist，例如："
                    "飙升榜,新歌榜,热歌榜,原创榜,网易云摇滚榜,网易云国风榜,网易云ACG动画榜"
                ),
                default_value=DEFAULT_CHARTS,
                required=False,
            ),
        )

    async def handle_async_init(self) -> None:
        """Initialize provider."""
        # get_setup_value reads the setup flow's value when present and otherwise falls
        # back to the stored option value, so installs configured either way resolve.
        api_url = self.get_setup_value(CONF_KEY_API_URL)
        if not api_url or not isinstance(api_url, str) or not api_url.strip():
            msg = "API URL is required"
            raise ValueError(msg)
        # Remove trailing slash
        self._api_url = api_url.strip().rstrip("/")

        unblock_api_url = self.get_setup_value(CONF_KEY_UNBLOCK_API_URL)
        if unblock_api_url and isinstance(unblock_api_url, str) and unblock_api_url.strip():
            self._unblock_api_url = unblock_api_url.strip().rstrip("/")
        else:
            self._unblock_api_url = None

        # Optional login cookie: an authenticated Netease session has a much higher quota
        # than the anonymous one that NeteaseCloudMusicApi starts with.
        raw_cookie = self.get_setup_value(CONF_KEY_COOKIE)
        raw_cookie = raw_cookie.strip() if isinstance(raw_cookie, str) else ""
        # a pasted cookie usually carries "Max-Age=/Expires=/Path=" tokens which make the
        # backend treat the whole thing as a broken cookie (i.e. silently anonymous)
        cookie = _clean_cookie(raw_cookie)
        if raw_cookie and cookie != raw_cookie:
            _LOGGER.info(
                "Netease cookie normalised: %d chars -> %d chars, names=[%s]",
                len(raw_cookie),
                len(cookie),
                ", ".join(part.split("=", 1)[0] for part in cookie.split("; ") if part),
            )
        self._cookie = cookie or None
        # Netease uid of the logged-in account (None while anonymous); library methods use it
        self._uid = None
        # chart playlists (飙升榜/新歌榜/...) to publish into the library as well
        self._charts = _parse_chart_names(
            self.get_setup_value(CONF_KEY_CHARTS, DEFAULT_CHARTS) or DEFAULT_CHARTS
        )
        self._hot_artists = _as_count(
            self.get_setup_value(CONF_KEY_HOT_ARTISTS, DEFAULT_HOT_ARTISTS), DEFAULT_HOT_ARTISTS
        )
        self._hot_albums = _as_count(
            self.get_setup_value(CONF_KEY_HOT_ALBUMS, DEFAULT_HOT_ALBUMS), DEFAULT_HOT_ALBUMS
        )

        # Keep a private httpx client: this provider's request helpers are written against
        # httpx, while Music Assistant's shared session is an aiohttp ClientSession (there
        # ``json()`` is a coroutine and the error types differ). Closed again in unload().
        self._http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._rate_limited_until = 0.0
        self._rate_limit_strikes = 0
        self._last_request_at = 0.0
        self._request_lock = asyncio.Lock()
        _LOGGER.info(
            "Netease Provider initialized with API URL: %s, Unblock API URL: %s, login cookie: %s",
            self._api_url,
            self._unblock_api_url,
            "yes" if self._cookie else "no (anonymous session, lower rate limit)",
        )
        if self._cookie:
            # a stored cookie that Netease no longer accepts keeps the provider on the tiny
            # anonymous quota without any visible symptom, so say out loud who we are logged in as
            await self._log_cookie_identity()

    async def _log_cookie_identity(self) -> None:
        """Verify the configured cookie with Netease and log who it belongs to."""
        full_cookie = self._cookie or ""
        minimal_cookie = _minimal_cookie(full_cookie)
        candidates = [("full", full_cookie)]
        if minimal_cookie and minimal_cookie != full_cookie:
            candidates.append(("minimal", minimal_cookie))
        try:
            chosen: tuple[str, str, dict] | None = None
            for label, cookie in candidates:
                self._cookie = cookie
                identity = await self._cookie_identity()
                if identity is not None:
                    chosen = (label, cookie, identity)
                    break
        except Exception as err:  # noqa: BLE001 - never fail provider setup because of the probe
            _LOGGER.debug("Could not verify the Netease cookie: %s", err)
            self._cookie = full_cookie
            return
        if chosen is None:
            # neither variant authenticates: the cookie itself is dead
            parts = [part for part in full_cookie.split("; ") if part]
            _LOGGER.warning(
                "Netease cookie is NOT logged in (Netease still answers with an anonymous "
                "session) - the account quota stays at the tiny guest one and searches will be "
                "throttled. Re-login in a browser and paste a fresh cookie. "
                "cookie length=%d, MUSIC_U length=%d, names=[%s]",
                len(full_cookie),
                len(next((p.partition("=")[2] for p in parts if p.startswith("MUSIC_U=")), "")),
                ", ".join(part.partition("=")[0] for part in parts),
            )
            self._cookie = full_cookie
            return
        label, cookie, identity = chosen
        self._cookie = cookie
        self._uid = str(identity.get("uid")) if identity.get("uid") else None
        # prove the cookie also reaches Netease through the backend, i.e. that ordinary
        # requests (search/library) are the logged-in ones and not the anonymous guest
        backend_sees_login = await self._backend_sees_login(identity.get("uid"))
        _LOGGER.info(
            "Netease login verified: %s (uid %s, vipType %s, cookie=%s%s, backend=%s)",
            identity.get("nickname") or "unknown",
            identity.get("uid"),
            identity.get("vipType"),
            label,
            "" if label == "full" else " (trimmed to MUSIC_U/__csrf)",
            "logged-in" if backend_sees_login else "anonymous(!)",
        )
        if not backend_sees_login:
            _LOGGER.warning(
                "The cookie is valid at Netease but the backend does not apply it - "
                "check that the NeteaseCloudMusicApi version is current, otherwise searches "
                "still run on the tiny guest quota",
            )

    async def _backend_sees_login(self, uid: Any) -> bool:
        """Return whether the backend itself answers as the logged-in account."""
        if not uid:
            return False
        try:
            data = await self._request("/user/playlist", params={"uid": str(uid), "limit": 1})
        except Exception as err:  # noqa: BLE001 - diagnostic only
            _LOGGER.debug("Backend login probe failed: %s", err)
            return False
        playlists = data.get("playlist") if isinstance(data, dict) else None
        return isinstance(playlists, list) and bool(playlists)

    async def _cookie_identity(self) -> dict[str, Any] | None:
        """Return the logged-in account behind the current cookie, or None when anonymous."""
        identity = self._identity_from_payload(await self._request("/login/status"))
        if identity is not None:
            return identity
        # the backend may be the thing dropping the cookie (it rebuilds the cookie header),
        # so ask Netease itself as a second opinion before declaring the cookie dead
        return await self._cookie_identity_direct()

    async def _cookie_identity_direct(self) -> dict[str, Any] | None:
        """Ask Netease's own web API who the current cookie belongs to."""
        if not self._cookie:
            return None
        url = "https://music.163.com/api/nuser/account/get"
        headers = {
            "Cookie": self._cookie,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://music.163.com/",
        }
        try:
            response = await self._http_client.post(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except Exception as err:  # noqa: BLE001 - diagnostic only
            _LOGGER.debug("Direct Netease cookie probe failed: %s", err)
            return None
        if not isinstance(payload, dict):
            return None
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        if not account or account.get("anonimousUser"):
            return None
        return {
            "uid": account.get("id"),
            "nickname": profile.get("nickname") or account.get("userName"),
            "vipType": account.get("vipType"),
        }

    def _identity_from_payload(self, data: Any) -> dict[str, Any] | None:
        """Extract the account identity from a /login/status style payload."""
        payload = data.get("data") if isinstance(data, dict) else None
        payload = payload if isinstance(payload, dict) else {}
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        if not account or account.get("anonimousUser"):
            return None
        return {
            "uid": account.get("id"),
            "nickname": profile.get("nickname") or account.get("userName"),
            "vipType": account.get("vipType"),
        }

    async def unload(self, is_removed: bool = False) -> None:
        """
        Handle unload/removal of the provider.

        :param is_removed: Whether the provider is removed from the configuration.
        """
        await self._close_http_client()
        await super().unload(is_removed)

    async def close(self) -> None:
        """
        Close the provider.

        Kept for older Music Assistant versions that call ``close()`` instead of
        ``unload()``; both paths close the HTTP client exactly once.
        """
        await self._close_http_client()

    async def _close_http_client(self) -> None:
        """Close the provider's HTTP client when it is still open."""
        client = getattr(self, "_http_client", None)
        if client is not None and not client.is_closed:
            await client.aclose()

    @property
    def is_streaming_provider(self) -> bool:
        """Return True if the provider is a streaming provider."""
        return True

    async def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """
        Make a request to NeteaseCloudMusicApi.

        Requests are serialized and rate limited so a burst - Music Assistant refreshes a
        library by searching per item - does not make the Netease upstream answer
        "操作频繁，请稍候再试" (HTTP 405). A throttled request waits out the pause and is
        retried; when it is still throttled afterwards this raises
        ResourceTemporarilyUnavailable so callers (and Music Assistant) treat it as a
        temporary provider problem instead of reporting the item as not found.
        """
        url = f"{self._api_url}{endpoint}"
        payload = dict(params) if params else {}
        if self._cookie:
            # NeteaseCloudMusicApi accepts the session cookie as a request parameter
            payload["cookie"] = self._cookie

        for attempt in range(RATE_LIMIT_RETRIES + 1):
            async with self._request_lock:
                await self._wait_for_slot()
                try:
                    response = await self._http_client.get(url, params=payload)
                    response.raise_for_status()
                except httpx.HTTPStatusError as err:
                    if err.response.status_code not in RATE_LIMIT_STATUS_CODES:
                        _LOGGER.error("HTTP error while requesting %s: %s", url, err)
                        return None
                    throttled = True
                except httpx.HTTPError as err:
                    _LOGGER.error("HTTP error while requesting %s: %s", url, err)
                    return None
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("Unexpected error while requesting %s: %s", url, err)
                    return None
                else:
                    throttled = False

            if throttled:
                self._note_rate_limit(url)
                if attempt < RATE_LIMIT_RETRIES:
                    continue
                msg = f"Netease API rate limit reached for {url}"
                raise ResourceTemporarilyUnavailable(
                    msg,
                    backoff_time=max(int(self._rate_limited_until - time.monotonic()), 1),
                )

            # a request went through: the backend is answering again, so forget old strikes
            self._rate_limit_strikes = 0
            try:
                data = response.json()
            except ValueError as err:
                _LOGGER.error("Invalid JSON in response from %s: %s", url, err)
                return None
            if data.get("code") != 200:
                _LOGGER.warning(
                    "API returned error code %s: %s", data.get("code"), data.get("message")
                )
                return None
            return data

    async def _wait_for_slot(self) -> None:
        """
        Sleep until it is allowed to send the next request (rate limit + spacing).

        A long remaining rate-limit pause is *not* slept through: that blocks a user search
        far past Music Assistant's provider timeout and makes the caller answer with an
        empty result, which then sticks. Raise ResourceTemporarilyUnavailable instead, so
        Music Assistant treats it as a temporary provider problem (retried later, and never
        cached as a valid empty answer).
        """
        while True:
            now = time.monotonic()
            # honor an active rate limit pause, but never send two requests back to back
            pause = self._rate_limited_until - now
            if pause > MAX_WAIT_FOR_RATE_LIMIT:
                msg = (
                    "Netease API rate limit active, refusing to wait "
                    f"{int(pause)}s for the next request slot"
                )
                raise ResourceTemporarilyUnavailable(msg, backoff_time=max(int(pause), 1))
            delay = max(pause, REQUEST_MIN_INTERVAL - (now - self._last_request_at))
            if delay <= 0:
                self._last_request_at = time.monotonic()
                return
            await asyncio.sleep(delay)

    def _note_rate_limit(self, url: str) -> None:
        """Back off for a while after the Netease backend reported that we are too fast."""
        self._rate_limit_strikes += 1
        backoff = min(
            RATE_LIMIT_BACKOFF * (2 ** (self._rate_limit_strikes - 1)),
            RATE_LIMIT_BACKOFF_MAX,
        )
        self._rate_limited_until = time.monotonic() + backoff
        # one warning per throttle episode keeps the log readable during a library refresh,
        # the repeated strikes of the same episode are only interesting when debugging
        log = _LOGGER.warning if self._rate_limit_strikes == 1 else _LOGGER.debug
        log("Netease API rate limit reached (%s): pausing requests for %ds", url, int(backoff))

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
                _LOGGER.debug("Successfully got unblocked URL for song %s from source: %s", song_id, data.get("source"))
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
            media_types = [MediaType.TRACK, MediaType.ALBUM, MediaType.ARTIST]

        result = SearchResults()
        # A throttled/temporarily failing backend must not be reported as "no results":
        # Music Assistant would cache that empty answer (24h for a streaming provider) and
        # the same search term would keep coming back empty. Track such failures and raise
        # at the end when nothing at all could be returned.
        transient_error: ResourceTemporarilyUnavailable | None = None

        # Search for tracks
        if MediaType.TRACK in media_types:
            try:
                data = await self._request(
                    NETEASE_SEARCH_ENDPOINT,
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_SONG, "limit": limit},
                )
                if data and "result" in data and "songs" in data["result"]:
                    songs_data = data["result"]["songs"][:limit]
                    # Batch fetch track details for accurate cover images; the search
                    # payload alone is good enough, so a failing details call must not
                    # throw away the tracks we already have.
                    try:
                        track_details = await self._batch_fetch_track_details(
                            [str(song["id"]) for song in songs_data]
                        )
                    except ResourceTemporarilyUnavailable:
                        track_details = {}
                    for song_data in songs_data:
                        track = await self._parse_track_from_search(song_data, track_details.get(str(song_data["id"])))
                        if track:
                            result.tracks.append(track)
            except ResourceTemporarilyUnavailable as err:
                transient_error = err
            except Exception as err:
                _LOGGER.warning("Error searching tracks: %s", err)

        # Search for albums
        if MediaType.ALBUM in media_types:
            try:
                data = await self._request(
                    NETEASE_SEARCH_ENDPOINT,
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_ALBUM, "limit": limit},
                )
                if data and "result" in data and "albums" in data["result"]:
                    for album_data in data["result"]["albums"][:limit]:
                        album = await self._parse_album_from_search(album_data)
                        if album:
                            result.albums.append(album)
            except ResourceTemporarilyUnavailable as err:
                transient_error = err
            except Exception as err:
                _LOGGER.warning("Error searching albums: %s", err)

        # Search for artists
        if MediaType.ARTIST in media_types:
            try:
                data = await self._request(
                    NETEASE_SEARCH_ENDPOINT,
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_ARTIST, "limit": limit},
                )
                if data and "result" in data and "artists" in data["result"]:
                    for artist_data in data["result"]["artists"][:limit]:
                        artist = await self._parse_artist_from_search(artist_data)
                        if artist:
                            result.artists.append(artist)
            except ResourceTemporarilyUnavailable as err:
                transient_error = err
            except Exception as err:
                _LOGGER.warning("Error searching artists: %s", err)

        # Search for playlists
        if MediaType.PLAYLIST in media_types:
            try:
                data = await self._request(
                    NETEASE_SEARCH_ENDPOINT,
                    params={"keywords": search_query, "type": NETEASE_SEARCH_TYPE_PLAYLIST, "limit": limit},
                )
                if data and "result" in data and "playlists" in data["result"]:
                    for playlist_data in data["result"]["playlists"][:limit]:
                        playlist = await self._parse_playlist_from_search(playlist_data)
                        if playlist:
                            result.playlists.append(playlist)
            except ResourceTemporarilyUnavailable as err:
                transient_error = err
            except Exception as err:
                _LOGGER.warning("Error searching playlists: %s", err)

        if transient_error is not None and not (
            result.tracks or result.albums or result.artists or result.playlists
        ):
            # nothing came back *and* the backend was throttling: let Music Assistant see a
            # temporary failure (retried later, not cached) instead of a valid empty answer
            raise transient_error

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
            # /cloudsearch spells fields "dt/artists/album", /song|/playlist|/likelist detail
            # spells them "dt/ar/al"; accept both so library syncs do not lose the artists
            duration = (song_data.get("dt") or song_data.get("duration") or 0) // 1000

            # Parse artists - prefer detail_data if available (has more complete info)
            artists = UniqueList[Artist]()
            artist_list: list[dict[str, Any]] = []
            for source in (detail_data, song_data):
                if not isinstance(source, dict):
                    continue
                candidate = source.get("ar") or source.get("artists")
                if isinstance(candidate, list) and candidate:
                    artist_list = candidate
                    break

            if artist_list:
                for artist_data in artist_list:
                    artist_id = str(artist_data["id"])
                    artist_name = artist_data.get("name", "Unknown Artist")
                    # Create artist with proper provider mapping and basic metadata
                    artist = Artist(
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
                    # Add basic metadata if available in the artist data
                    if "img1v1Url" in artist_data or "picUrl" in artist_data:
                        artist_img_url = artist_data.get("img1v1Url") or artist_data.get("picUrl")
                        artist.metadata = MediaItemMetadata()
                        artist.metadata.images = self._build_images([artist_img_url] if artist_img_url else None)
                    artists.append(artist)

            # Parse album - prefer detail_data if available (has more complete info)
            album: Album | ItemMapping | None = None
            album_cover_url: str | None = None
            album_data = None
            for source in (detail_data, song_data):
                if not isinstance(source, dict):
                    continue
                candidate = source.get("al") or source.get("album")
                if isinstance(candidate, dict) and candidate:
                    album_data = candidate
                    break

            if album_data:
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
                album_data = song_data.get("album", {}) if "album" in song_data else {}
                album_cover_url = album_data.get("picUrl") if album_data else None
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
                disc_number=song_data.get("cd", 1) if song_data.get("cd") else 1,
                track_number=song_data.get("no", 1) if song_data.get("no") else 1,
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
            raise MediaNotFoundError(msg)

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

        track_lyrics = await self.get_lyrics(prov_track_id)

        # Create metadata with both images and lyrics if available
        metadata = MediaItemMetadata(images=images)
        if track_lyrics:
            metadata.lyrics = track_lyrics

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
            metadata=metadata,
            disc_number=song_data.get("cd", 1),
            track_number=song_data.get("no", 1),
        )

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get full artist details by id."""
        # Get artist detail which includes basic info and description
        data = await self._request("/artist/detail", params={"id": prov_artist_id})
        if not data or "data" not in data:
            msg = f"Artist {prov_artist_id} not found"
            raise MediaNotFoundError(msg)

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
            raise MediaNotFoundError(msg)

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

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Get streamdetails for a track."""
        if media_type == MediaType.TRACK:
            # First try unblock API if configured
            if self._unblock_api_url:
                unblock_data = await self._request_unblock_api(item_id)
                if unblock_data and unblock_data.get("audioUrl"):
                    _LOGGER.debug("Using unblocked URL for track %s from source: %s", item_id, unblock_data.get("source"))
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

    async def get_artist_toptracks(self, prov_artist_id: str) -> list[Track]:
        """Get top tracks for the given artist."""
        _LOGGER.debug(f"get_artist_toptracks called for artist ID: {prov_artist_id}")

        # Use /artist/top/song API to get top songs for an artist
        data = await self._request("/artist/top/song", params={"id": prov_artist_id})
        if not data or "songs" not in data:
            _LOGGER.warning(f"No songs returned from artist/top/song API for artist {prov_artist_id}")
            return []

        songs = data["songs"]
        _LOGGER.debug(f"Found {len(songs)} top songs for artist {prov_artist_id}")

        tracks = []

        # Batch fetch track details for accurate cover images
        track_ids = [str(song["id"]) for song in songs]
        _LOGGER.debug(f"Batch fetching details for {len(track_ids)} tracks")
        track_details = await self._batch_fetch_track_details(track_ids)

        for idx, song_data in enumerate(songs):
            _LOGGER.debug(f"Processing top track {idx+1}: {song_data.get('name', 'Unknown')}")
            track = await self._parse_track_from_search(song_data, track_details.get(str(song_data["id"])))
            if track:
                tracks.append(track)
                _LOGGER.debug(f"Successfully added top track: {track.name}")
            else:
                _LOGGER.warning(f"Failed to create track for top song: {song_data.get('name', 'Unknown')}")

        _LOGGER.debug(f"Returning {len(tracks)} top tracks for artist {prov_artist_id}")
        return tracks

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Get all tracks for a given album."""
        _LOGGER.debug(f"get_album_tracks called for album ID: {prov_album_id}")

        data = await self._request("/album", params={"id": prov_album_id})
        _LOGGER.debug(f"Album API response: {data}")

        if not data:
            _LOGGER.warning(f"No data returned from album API for ID: {prov_album_id}")
            return []

        if "album" not in data:
            _LOGGER.warning(f"No 'album' key in response for ID: {prov_album_id}. Keys: {list(data.keys())}")
            return []

        songs = data.get("songs", [])
        _LOGGER.debug(f"Found {len(songs)} songs in album response")

        if not songs:
            _LOGGER.warning(f"No songs found in album {prov_album_id}")
            return []

        tracks = []

        # Batch fetch track details for accurate cover images
        track_ids = [str(song["id"]) for song in songs]
        _LOGGER.debug(f"Batch fetching details for {len(track_ids)} tracks")
        track_details = await self._batch_fetch_track_details(track_ids)

        for song_data in songs:
            _LOGGER.debug(f"Processing song: {song_data.get('name', 'Unknown')}")
            track = await self._parse_track_from_search(song_data, track_details.get(str(song_data["id"])))
            if track:
                tracks.append(track)
                _LOGGER.debug(f"Successfully created track: {track.name}")
            else:
                _LOGGER.warning(f"Failed to create track for song: {song_data.get('name', 'Unknown')}")

        _LOGGER.debug(f"Returning {len(tracks)} tracks for album {prov_album_id}")
        return tracks

    # Library methods - return empty for now as this is a streaming provider
    async def get_library_artists(self) -> AsyncGenerator[Artist, None]:
        """Retrieve library artists: followed ones (when logged in) plus the hot chart."""
        seen: set[str] = set()
        if self._uid:
            data = await self._request("/artist/sublist", params={"limit": 500, "offset": 0})
            followed = _payload_list(data, "data", "artists")
            _LOGGER.info("Netease library artists: %d followed artist(s)", len(followed))
            for artist_data in followed:
                artist = await self._parse_artist_from_search(artist_data)
                if artist and artist.item_id not in seen:
                    seen.add(artist.item_id)
                    yield artist
        if self._hot_artists <= 0:
            _LOGGER.info("Netease library artists: hot chart disabled (hot_artists=0)")
            return
        data = await self._request(
            "/top/artists", params={"limit": self._hot_artists, "offset": 0}
        )
        added = 0
        for artist_data in _payload_list(data, "artists"):
            artist = await self._parse_artist_from_search(artist_data)
            if artist and artist.item_id not in seen:
                seen.add(artist.item_id)
                added += 1
                yield artist
        _LOGGER.info("Netease library artists: %d hot artist(s) added", added)

    async def get_library_albums(self) -> AsyncGenerator[Album, None]:
        """Retrieve library albums: collected ones (when logged in) plus new releases."""
        seen: set[str] = set()
        if self._uid:
            data = await self._request("/album/sublist", params={"limit": 500, "offset": 0})
            saved = _payload_list(data, "data", "albums")
            _LOGGER.info("Netease library albums: %d saved album(s)", len(saved))
            for album_data in saved:
                album = await self._parse_album_row(album_data)
                if album and album.item_id not in seen:
                    seen.add(album.item_id)
                    yield album
        if self._hot_albums <= 0:
            _LOGGER.info("Netease library albums: new releases disabled (hot_albums=0)")
            return
        data = await self._request(
            "/album/new", params={"area": "ALL", "limit": self._hot_albums, "offset": 0}
        )
        added = 0
        for album_data in _payload_list(data, "albums"):
            album = await self._parse_album_row(album_data)
            if album and album.item_id not in seen:
                seen.add(album.item_id)
                added += 1
                yield album
        _LOGGER.info("Netease library albums: %d hot album(s) added", added)

    async def _parse_album_row(self, album_data: dict[str, Any]) -> Album | None:
        """Parse an album row from the sublist/new-release endpoints (artists -> artist)."""
        if isinstance(album_data.get("artists"), list) and album_data["artists"]:
            album_data = {**album_data, "artist": album_data["artists"][0]}
        return await self._parse_album_from_search(album_data)

    async def get_library_tracks(self) -> AsyncGenerator[Track, None]:
        """Retrieve library tracks from the provider."""
        if self._uid:
            # logged in: the account's liked songs ("我喜欢的音乐")
            data = await self._request("/likelist", params={"uid": self._uid})
            raw_ids = data.get("ids") if isinstance(data, dict) else None
            ids = [str(song_id) for song_id in (raw_ids or [])]
            _LOGGER.info("Netease library tracks: %d liked song(s)", len(ids))
            for start in range(0, len(ids), 200):
                chunk = ids[start : start + 200]
                detail = await self._request("/song/detail", params={"ids": ",".join(chunk)})
                for song_data in _payload_list(detail, "songs"):
                    track = await self._parse_track_from_search(song_data)
                    if track:
                        yield track
            return
        _LOGGER.debug("get_library_tracks called - returning popular tracks as library")

        # For streaming provider, return popular tracks as library
        # We'll get tracks from top playlists
        _LOGGER.debug("Requesting top playlists from API to get popular tracks")
        data = await self._request("/top/playlist", params={"limit": 10, "offset": 0, "cat": "全部"})

        if not data or "playlists" not in data:
            _LOGGER.warning("No playlists data returned from /top/playlist API")
            return

        playlists = data["playlists"][:3]  # Limit to 3 playlists
        _LOGGER.debug(f"Processing {len(playlists)} top playlists for tracks")

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
                        _LOGGER.debug("Reached track limit (30), stopping")
                        return

        _LOGGER.debug(f"Total yielded {count} tracks from get_library_tracks")

    async def get_library_playlists(self) -> AsyncGenerator[Playlist, None]:
        """Retrieve library/subscribed playlists (account playlists + configured charts)."""
        if self._uid:
            async for playlist in self._account_playlists():
                yield playlist
        else:
            async for playlist in self._popular_playlists():
                yield playlist
        async for playlist in self._chart_playlists():
            yield playlist

    async def _account_playlists(self) -> AsyncGenerator[Playlist, None]:
        """Yield the logged-in account's own + subscribed playlists (incl. 我喜欢的音乐)."""
        data = await self._request(
            "/user/playlist", params={"uid": self._uid, "limit": 1000, "offset": 0}
        )
        playlists_list = _payload_list(data, "playlist")
        _LOGGER.info(
            "Netease library playlists: %d playlist(s) of account %s",
            len(playlists_list),
            self._uid,
        )
        for playlist_data in playlists_list:
            playlist = await self._parse_playlist_from_search(playlist_data)
            if playlist:
                yield playlist

    async def _popular_playlists(self) -> AsyncGenerator[Playlist, None]:
        """Yield the public hot playlists (the anonymous-session behaviour)."""
        _LOGGER.debug("get_library_playlists called - returning popular playlists as library")
        data = await self._request(
            "/top/playlist/highquality", params={"limit": 50, "offset": 0, "cat": "全部"}
        )
        if not data or "playlists" not in data:
            _LOGGER.warning("No playlists data returned from /top/playlist API")
            return
        playlists_list = data["playlists"]
        _LOGGER.debug(f"Received {len(playlists_list)} playlists from API")
        for playlist_data in playlists_list:
            playlist = await self._parse_playlist_from_search(playlist_data)
            if playlist:
                yield playlist

    async def _chart_playlists(self) -> AsyncGenerator[Playlist, None]:
        """Yield the configured Netease charts (飙升榜/新歌榜/热歌榜...) as playlists."""
        if not self._charts:
            return
        data = await self._request("/toplist")
        charts = _payload_list(data, "list")
        by_name = {
            str(item.get("name")): item for item in charts if isinstance(item.get("name"), str)
        }
        if self._charts == ["*"]:
            _LOGGER.info(
                "Netease library charts: syncing all %d chart playlist(s)", len(by_name)
            )
            for item in charts:
                if not isinstance(item.get("name"), str):
                    continue
                playlist = await self._parse_playlist_from_search(item)
                if playlist:
                    yield playlist
            return
        resolved: list[dict[str, Any]] = []
        for name in self._charts:
            item = by_name.get(name)
            if item is None:
                # tolerate a partial name ("ACG" for 网易云ACG动画榜) as long as it is unambiguous
                candidates = [value for key, value in by_name.items() if name in key]
                item = candidates[0] if len(candidates) == 1 else None
            if item is None:
                _LOGGER.warning(
                    "Netease chart %r not found - use a name from /discover/toplist "
                    "(available: %s)",
                    name,
                    ", ".join(list(by_name)[:10]),
                )
                continue
            resolved.append(item)
        _LOGGER.info(
            "Netease library charts: %d chart playlist(s): %s",
            len(resolved),
            ", ".join(str(item.get("name")) for item in resolved),
        )
        for item in resolved:
            playlist = await self._parse_playlist_from_search(item)
            if playlist:
                yield playlist

    async def get_playlist(self, prov_playlist_id: str) -> Playlist:
        """Get full playlist details by id."""
        # Use /playlist/detail to get playlist details
        data = await self._request("/playlist/detail", params={"id": prov_playlist_id})
        if not data or "playlist" not in data:
            msg = f"Playlist {prov_playlist_id} not found"
            raise MediaNotFoundError(msg)

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

    async def get_playlist_tracks(self, prov_playlist_id: str, page: int = 0) -> list[Track]:
        """Get playlist tracks by id with page for pagination."""
        # Use /playlist/track/all to get all tracks in playlist
        data = await self._request("/playlist/track/all", params={"id": prov_playlist_id})
        if not data or "songs" not in data:
            # Alternative API endpoint might be needed
            _LOGGER.warning(f"No songs returned from playlist/track/all for playlist {prov_playlist_id}")
            # Try using playlist detail endpoint which might include tracks
            detail_data = await self._request("/playlist/detail", params={"id": prov_playlist_id, "limit": 100})
            if not detail_data or "playlist" not in detail_data:
                return []
            songs = detail_data["playlist"].get("tracks", [])
        else:
            songs = data["songs"]

        _LOGGER.debug(f"Found {len(songs)} songs in playlist {prov_playlist_id}")

        # Apply pagination: page is 0-indexed, default page size is 50
        page_size = 50
        start_index = page * page_size
        end_index = start_index + page_size
        paginated_songs = songs[start_index:end_index]

        # Batch fetch track details for accurate cover images
        track_ids = [str(song["id"]) for song in paginated_songs]
        _LOGGER.debug(f"Batch fetching details for {len(track_ids)} tracks")
        track_details = await self._batch_fetch_track_details(track_ids)

        tracks = []
        for idx, song_data in enumerate(paginated_songs):
            _LOGGER.debug(f"Processing playlist track {idx+1}: {song_data.get('name', 'Unknown')}")
            track = await self._parse_track_from_search(song_data, track_details.get(str(song_data["id"])))
            if track:
                _LOGGER.debug(f"Adding playlist track: {track.name}")
                tracks.append(track)
            else:
                _LOGGER.warning(f"Failed to parse playlist track: {song_data.get('name', 'Unknown')}")
        return tracks

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get full radio details by id."""
        # Use /dj/program/detail to get radio program details
        data = await self._request("/dj/program/detail", params={"id": prov_radio_id})
        if not data or "program" not in data:
            msg = f"Radio program {prov_radio_id} not found"
            raise MediaNotFoundError(msg)

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

    async def get_lyrics(self, prov_track_id: str) -> str | None:
        """Get lyrics for a given track id."""
        _LOGGER.debug(f"get_lyrics called for track ID: {prov_track_id}")

        # Use the /lyric endpoint to get lyrics for the track
        data = await self._request("/lyric", params={"id": prov_track_id})
        if not data:
            _LOGGER.warning(f"No lyrics data returned from API for track {prov_track_id}")
            return None

        # Netease API typically returns lyrics in the 'lrc' field with 'lyric' subfield
        lrc_data = data.get("lrc")
        if not lrc_data or "lyric" not in lrc_data:
            _LOGGER.warning(f"No lyrics found in API response for track {prov_track_id}")
            return None

        lyrics_text = lrc_data["lyric"]
        if not lyrics_text:
            _LOGGER.warning(f"Empty lyrics returned from API for track {prov_track_id}")
            return None

        _LOGGER.debug(f"Successfully retrieved lyrics for track {prov_track_id}")
        return lyrics_text

    async def get_popular_artists(self, limit: int = 50) -> AsyncGenerator[Artist, None]:
        """Get popular/hot artists from Netease Cloud Music."""
        data = await self._request("/top/artists", params={"limit": limit, "offset": 0})
        if not data or "artists" not in data:
            return

        for artist_data in data["artists"]:
            artist = await self._parse_artist_from_search(artist_data)
            if artist:
                yield artist
