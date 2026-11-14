"""
Setup flow for the Netease Cloud Music provider.

Music Assistant resolves provider setup input through a flow (see the server's
``music_assistant.models.setup_flow``): a provider without a ``setup_flow`` module needs no
input at all and can therefore never be added, because there is nowhere to collect the
backend address. The flow below asks for the NeteaseCloudMusicApi address (and the optional
unblock API address), verifies that the address actually answers, and persists both as the
instance's setup data. The same flow serves a later reconfigure, prefilled with the values
that are already stored.

Signing in is optional but recommended: an anonymous Netease session has a very small quota
and gets throttled (405 "操作频繁") quickly, so the flow offers the NetEase QR login - the
user scans the code with the NetEase Cloud Music app and the resulting cookie is stored (it
raises the quota a lot and unlocks the account's own playlists). A cookie copied from
``/login/cellphone`` can still be pasted instead, and anonymous use stays possible.

The QR code is minted against the chosen backend, shown as a PROGRESS step image, and
minted afresh whenever its scan window elapses, so the displayed code never silently goes
stale.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import aiohttp
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType
from music_assistant_models.errors import InvalidDataError, ResourceTemporarilyUnavailable

from music_assistant.models.setup_flow import SetupFlowError, StepExpiredError

from . import CONF_KEY_API_URL, CONF_KEY_COOKIE, CONF_KEY_UNBLOCK_API_URL, DEFAULT_API_URL

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType

    from music_assistant.models.setup_flow import SetupSession

_LOGGER = logging.getLogger(__name__)

# flow-only form key: whether to sign in with the NetEase app (not persisted as a value)
CONF_KEY_QR_LOGIN = "qr_login"

# endpoint probed to confirm the address really serves a NeteaseCloudMusicApi backend
_PROBE_ENDPOINT = "/login/status"
_PROBE_TIMEOUT = 10.0

# NeteaseCloudMusicApi QR login endpoints (all GET, all on the backend address)
_QR_KEY_ENDPOINT = "/login/qr/key"
_QR_CREATE_ENDPOINT = "/login/qr/create"
_QR_CHECK_ENDPOINT = "/login/qr/check"

# scan window (seconds) a shown QR code is valid for before a fresh one is minted
_QR_EXPIRES_IN = 120.0
# delay (seconds) between poll attempts against the QR check endpoint
_QR_POLL_INTERVAL = 1.5
# hard limit of fresh QR codes per setup run (~1 hour), so a flow left open does not poll forever
_QR_MAX_REFRESHES = 30
# shown under the QR code in the setup dialog (the step's title is translated server-side,
# which a bind-mounted provider cannot provide, so the instruction travels as progress text)
_QR_PROGRESS_TEXT = (
    "打开手机上的「网易云音乐」App → 右上角「+」→ 扫一扫，扫描上面的二维码并在手机上确认登录。"
    "二维码 120 秒过期后会自动换一张新的，确认后这一步会自动完成。"
)

# Netease QR check status codes
_QR_CODE_EXPIRED = 800
_QR_CODE_WAITING_SCAN = 801
_QR_CODE_WAITING_CONFIRM = 802
_QR_CODE_CONFIRMED = 803

# cookie attributes the backend appends to Set-Cookie style strings; they are not part of the
# cookie value NeteaseCloudMusicApi expects as a request parameter
_COOKIE_ATTRIBUTES = {"expires", "max-age", "path", "domain", "secure", "httponly", "samesite"}


class QRLoginError(Exception):
    """Raised when the QR login cannot be completed (backend refused, no image, no cookie)."""


async def run_setup(session: SetupSession) -> None:
    """
    Collect the NeteaseCloudMusicApi address(es) and optionally sign in.

    :param session: The setup session driving the flow.
    """
    api_url = str(
        session.context.setup_data.get(CONF_KEY_API_URL)
        or session.context.values.get(CONF_KEY_API_URL)
        or DEFAULT_API_URL
    ).strip()
    unblock_api_url = str(
        session.context.setup_data.get(CONF_KEY_UNBLOCK_API_URL)
        or session.context.values.get(CONF_KEY_UNBLOCK_API_URL)
        or ""
    ).strip()
    # SECURE_STRING entries are never prefilled, so the stored cookie is not echoed back
    cookie = ""
    errors: dict[str, str] | None = None
    while True:
        values = await session.form(
            [
                ConfigEntry(
                    key=CONF_KEY_API_URL,
                    type=ConfigEntryType.STRING,
                    label="API 地址",
                    description=(
                        "NeteaseCloudMusicApi 服务地址，例如 http://192.168.31.1:3001"
                    ),
                    default_value=DEFAULT_API_URL,
                    value=api_url,
                    required=True,
                ),
                ConfigEntry(
                    key=CONF_KEY_UNBLOCK_API_URL,
                    type=ConfigEntryType.STRING,
                    label="解锁 API 地址（可选）",
                    description=(
                        "UnblockNeteaseMusic API 服务地址，例如 http://192.168.31.1:3003；"
                        "留空则不启用"
                    ),
                    default_value="",
                    value=unblock_api_url,
                    required=False,
                ),
                ConfigEntry(
                    key=CONF_KEY_QR_LOGIN,
                    type=ConfigEntryType.BOOLEAN,
                    label="扫码登录（推荐）",
                    description=(
                        "下一步会显示二维码，用网易云音乐 App 扫码确认即可登录。登录后接口配额大"
                        "幅提高，不再频繁「操作频繁」405，也能访问自己账号的歌单。取消勾选则使用"
                        "匿名会话（配额较低）"
                    ),
                    default_value=False,
                    value=True,
                    required=False,
                ),
                ConfigEntry(
                    key=CONF_KEY_COOKIE,
                    type=ConfigEntryType.SECURE_STRING,
                    label="登录 Cookie（可选，仅在不方便扫码时手填）",
                    description=(
                        "已经拿到 cookie 时可直接粘贴（留空则由扫码登录或匿名会话处理）。获取方法："
                        "curl -X POST 'http://<API地址>/login/cellphone?phone=手机号&password=密码'"
                        "，把返回 JSON 里的 cookie 字段粘贴到这里"
                    ),
                    default_value="",
                    required=False,
                ),
            ],
            step_id="user",
            errors=errors,
        )
        api_url = str(values.get(CONF_KEY_API_URL) or "").strip().rstrip("/")
        unblock_api_url = str(values.get(CONF_KEY_UNBLOCK_API_URL) or "").strip().rstrip("/")
        cookie = str(values.get(CONF_KEY_COOKIE) or "").strip()
        qr_login = bool(values.get(CONF_KEY_QR_LOGIN, True))
        try:
            payload = await _probe_api_url(session, api_url, cookie)
        except InvalidDataError as err:
            errors = {CONF_KEY_API_URL: getattr(err, "translation_key", None) or str(err)}
            continue
        except ResourceTemporarilyUnavailable as err:
            errors = {"base": getattr(err, "translation_key", None) or str(err)}
            continue
        logged_in = _is_logged_in(payload)
        if cookie and not logged_in:
            errors = {CONF_KEY_COOKIE: "cookie 无效或已过期（该 cookie 仍是匿名状态），请重新获取"}
            continue
        if not cookie and qr_login:
            try:
                qr_cookie = await _run_qr_login(session, api_url)
            except StepExpiredError:
                # the engine aborts the flow as timed out; nothing to save
                raise
            except QRLoginError as err:
                errors = {"base": str(err)}
                continue
            except ResourceTemporarilyUnavailable as err:
                errors = {"base": getattr(err, "translation_key", None) or str(err)}
                continue
            # a confirmed QR must actually yield a logged-in session, otherwise the login
            # would silently keep the (low quota) anonymous session
            try:
                qr_payload = await _probe_api_url(session, api_url, qr_cookie)
            except (InvalidDataError, ResourceTemporarilyUnavailable) as err:
                errors = {"base": getattr(err, "translation_key", None) or str(err)}
                continue
            if not _is_logged_in(qr_payload):
                errors = {"base": "扫码已确认，但后端返回的仍是匿名会话，请重试"}
                _LOGGER.warning("QR login confirmed but %s reports an anonymous session", api_url)
                continue
            cookie = qr_cookie
            _LOGGER.debug("QR login completed, storing the session cookie")
        if not cookie:
            _LOGGER.info(
                "%s 使用匿名会话（未登录）：网易云会以较低的配额限流，"
                "建议扫码登录或填入 cookie",
                api_url,
            )
        try:
            await session.finish(
                {
                    CONF_KEY_API_URL: api_url,
                    CONF_KEY_UNBLOCK_API_URL: unblock_api_url,
                    CONF_KEY_COOKIE: cookie,
                }
            )
            return
        except SetupFlowError as err:
            errors = {"base": err.translation_key or str(err)}


def _is_logged_in(payload: dict[str, Any]) -> bool:
    """
    Return whether a /login/status payload belongs to a real (non-anonymous) account.

    :param payload: The parsed /login/status response.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    # NeteaseCloudMusicApi always reports its own anonymous session as an account with
    # ``anonimousUser: true``; only a real login carries a non-anonymous account.
    return bool(account) and not account.get("anonimousUser")


async def _run_qr_login(session: SetupSession, api_url: str) -> str:
    """
    Show a QR code and wait for it to be scanned and confirmed, returning the cookie.

    A fresh QR code is minted and the PROGRESS step re-emitted whenever the scan window
    elapses (or the backend reports the code expired), so the displayed code stays valid.

    :param session: The setup session driving the flow.
    :param api_url: The NeteaseCloudMusicApi backend address.
    """
    for _attempt in range(_QR_MAX_REFRESHES):
        qr_key, qr_image = await _create_qr(session, api_url)
        try:
            return await session.progress_until(
                _poll_qr_login(session, api_url, qr_key),
                step_id="scan_qr",
                # the PROGRESS step renders progress_text below the image (its title comes from
                # the translation bundle, which a bind-mounted provider does not have)
                text=_QR_PROGRESS_TEXT,
                image=qr_image,
                expires_in=_QR_EXPIRES_IN,
            )
        except StepExpiredError:
            continue
    msg = "二维码多次刷新仍未完成登录，已放弃扫码，请重试或改用 cookie 方式"
    raise QRLoginError(msg)


async def _create_qr(session: SetupSession, api_url: str) -> tuple[str, str]:
    """
    Create a fresh QR login session and return its poll key and data-URI image.

    :param session: The setup session driving the flow.
    :param api_url: The NeteaseCloudMusicApi backend address.
    """
    key_payload = await _get_json(session, f"{api_url}{_QR_KEY_ENDPOINT}", {})
    key_data = _payload_data(key_payload)
    qr_key = str(key_data.get("unikey") or key_data.get("key") or "").strip()
    if not qr_key:
        msg = "后端没有返回二维码 key，请确认 API 地址指向 NeteaseCloudMusicApi"
        raise QRLoginError(msg)
    qr_payload = await _get_json(
        session, f"{api_url}{_QR_CREATE_ENDPOINT}", {"key": qr_key, "qrimg": "true"}
    )
    qr_data = _payload_data(qr_payload)
    # the backend already returns qrimg as a data:image/png;base64,... string, which is
    # exactly what the PROGRESS step takes, so it is emitted verbatim (no re-encoding)
    qr_image = str(qr_data.get("qrimg") or "").strip()
    if not qr_image:
        msg = "后端没有返回二维码图片，请确认 API 地址指向 NeteaseCloudMusicApi"
        raise QRLoginError(msg)
    return qr_key, qr_image


async def _poll_qr_login(session: SetupSession, api_url: str, qr_key: str) -> str:
    """
    Poll the QR check endpoint until the login is confirmed, returning the session cookie.

    :param session: The setup session driving the flow.
    :param api_url: The NeteaseCloudMusicApi backend address.
    :param qr_key: The QR poll key from _create_qr.
    """
    while True:
        try:
            payload = await _get_json(
                session, f"{api_url}{_QR_CHECK_ENDPOINT}", {"key": qr_key}
            )
        except (ResourceTemporarilyUnavailable, QRLoginError) as err:
            # a transient hiccup while polling must not kill the shown QR code
            _LOGGER.debug("QR poll failed (%s), retrying", err)
            await asyncio.sleep(_QR_POLL_INTERVAL)
            continue
        code = _payload_code(payload)
        if code == _QR_CODE_CONFIRMED:
            cookie = _clean_cookie(_payload_cookie(payload))
            if not cookie:
                msg = "扫码已确认，但后端没有返回 cookie"
                raise QRLoginError(msg)
            return cookie
        if code == _QR_CODE_EXPIRED:
            # let the caller mint a fresh code alongside the step deadline
            raise StepExpiredError
        # 801 (waiting for scan) / 802 (scanned, waiting for confirm): keep polling
        await asyncio.sleep(_QR_POLL_INTERVAL)


async def _get_json(
    session: SetupSession, url: str, params: dict[str, str]
) -> dict[str, Any]:
    """
    Fetch a JSON payload from the NeteaseCloudMusicApi backend.

    :param session: The setup session driving the flow.
    :param url: Full request URL.
    :param params: Query parameters (a timestamp is added).
    """
    query = {**params, "timestamp": str(int(time.time() * 1000))}
    try:
        async with session.mass.http_session.get(
            url, params=query, timeout=aiohttp.ClientTimeout(total=_PROBE_TIMEOUT)
        ) as response:
            status = response.status
            if status >= 400:
                msg = f"{url} 返回错误：HTTP {status}"
                raise ResourceTemporarilyUnavailable(msg)
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        msg = f"无法连接后端 {url}：{err}"
        raise ResourceTemporarilyUnavailable(msg) from err
    except ValueError as err:
        msg = f"{url} 返回的不是 JSON"
        raise QRLoginError(msg) from err
    if not isinstance(payload, dict):
        msg = f"{url} 返回的不是 JSON 对象"
        raise QRLoginError(msg)
    return payload


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Return the (nested) ``data`` object of a NeteaseCloudMusicApi response.

    :param payload: The parsed response.
    """
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _payload_code(payload: dict[str, Any]) -> int | None:
    """
    Return the status code of a NeteaseCloudMusicApi response (top level or nested).

    :param payload: The parsed response.
    """
    for candidate in (payload.get("code"), _payload_data(payload).get("code")):
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def _payload_cookie(payload: dict[str, Any]) -> str:
    """
    Extract the cookie string of a confirmed QR check response.

    :param payload: The parsed response.
    """
    cookie = payload.get("cookie") or _payload_data(payload).get("cookie")
    return str(cookie or "").strip()


def _clean_cookie(raw: str) -> str:
    """
    Drop Set-Cookie attributes from a cookie string, keeping ``name=value`` pairs only.

    :param raw: The cookie string returned by the backend.
    """
    parts: list[str] = []
    for item in raw.split(";"):
        name, _, value = item.strip().partition("=")
        if not name or not _ or name.strip().lower() in _COOKIE_ATTRIBUTES:
            continue
        parts.append(f"{name.strip()}={value.strip()}")
    return "; ".join(parts)


async def _probe_api_url(session: SetupSession, api_url: str, cookie: str) -> dict[str, Any]:
    """
    Verify that the given address serves a NeteaseCloudMusicApi-compatible backend.

    :param session: The setup session driving the flow (for the shared HTTP session).
    :param api_url: The backend address to probe.
    :param cookie: The (optional) login cookie to verify.
    """
    if not api_url:
        msg = "API 地址不能为空"
        raise InvalidDataError(msg)
    params: dict[str, Any] = {"timestamp": int(time.time() * 1000)}
    if cookie:
        params["cookie"] = cookie
    try:
        # the server's shared session is an aiohttp ClientSession
        async with session.mass.http_session.get(
            f"{api_url}{_PROBE_ENDPOINT}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=_PROBE_TIMEOUT),
        ) as response:
            status = response.status
            if 400 <= status < 500:
                # something answered, but not the expected endpoint: wrong address
                msg = f"{api_url} 不是可用的 NeteaseCloudMusicApi 服务地址（HTTP {status}）"
                raise InvalidDataError(msg)
            if status >= 500:
                msg = f"API 地址 {api_url} 返回错误：HTTP {status}"
                raise ResourceTemporarilyUnavailable(msg)
            try:
                payload = await response.json(content_type=None)
            except ValueError as err:
                msg = f"{api_url} 不是可用的 NeteaseCloudMusicApi 服务地址（响应不是 JSON）"
                raise InvalidDataError(msg) from err
    except (aiohttp.ClientError, TimeoutError) as err:
        # nothing answered at this address: it may just not be up yet
        msg = f"无法连接 API 地址 {api_url}：{err}"
        raise ResourceTemporarilyUnavailable(msg) from err
    if not isinstance(payload, dict) or not {"data", "code"} & set(payload):
        msg = f"{api_url} 不是可用的 NeteaseCloudMusicApi 服务地址"
        raise InvalidDataError(msg)
    return payload
