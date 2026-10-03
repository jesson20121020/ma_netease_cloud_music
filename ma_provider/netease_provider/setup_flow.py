"""
Setup flow for the Netease Cloud Music provider.

Music Assistant resolves provider setup input through a flow (see the server's
``music_assistant.models.setup_flow``): a provider without a ``setup_flow`` module needs no
input at all and can therefore never be added, because there is nowhere to collect the
backend address. The flow below asks for the NeteaseCloudMusicApi address (and the optional
unblock API address), verifies that the address actually answers, and persists both as the
instance's setup data. The same flow serves a later reconfigure, prefilled with the values
that are already stored.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType
from music_assistant_models.errors import InvalidDataError, ResourceTemporarilyUnavailable

from music_assistant.models.setup_flow import SetupFlowError

from . import CONF_KEY_API_URL, CONF_KEY_UNBLOCK_API_URL, DEFAULT_API_URL

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigValueType

    from music_assistant.models.setup_flow import SetupSession

# endpoint probed to confirm the address really serves a NeteaseCloudMusicApi backend
_PROBE_ENDPOINT = "/login/status"
_PROBE_TIMEOUT = 10.0


async def run_setup(session: SetupSession) -> None:
    """
    Collect the NeteaseCloudMusicApi address (and the optional unblock API address).

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
            ],
            step_id="user",
            errors=errors,
        )
        api_url = str(values.get(CONF_KEY_API_URL) or "").strip().rstrip("/")
        unblock_api_url = str(values.get(CONF_KEY_UNBLOCK_API_URL) or "").strip().rstrip("/")
        try:
            await _probe_api_url(session, api_url)
        except InvalidDataError as err:
            errors = {CONF_KEY_API_URL: getattr(err, "translation_key", None) or str(err)}
            continue
        except ResourceTemporarilyUnavailable as err:
            errors = {"base": getattr(err, "translation_key", None) or str(err)}
            continue
        try:
            await session.finish(
                {
                    CONF_KEY_API_URL: api_url,
                    CONF_KEY_UNBLOCK_API_URL: unblock_api_url,
                }
            )
            return
        except SetupFlowError as err:
            errors = {"base": err.translation_key or str(err)}


async def _probe_api_url(session: SetupSession, api_url: str) -> None:
    """
    Verify that the given address serves a NeteaseCloudMusicApi-compatible backend.

    :param session: The setup session driving the flow (for the shared HTTP session).
    :param api_url: The backend address to probe.
    """
    if not api_url:
        msg = "API 地址不能为空"
        raise InvalidDataError(msg)
    try:
        response = await session.mass.http_session.get(
            f"{api_url}{_PROBE_ENDPOINT}",
            params={"timestamp": int(time.time() * 1000)},
            timeout=_PROBE_TIMEOUT,
        )
    except httpx.HTTPError as err:
        # nothing answered at this address: it may just not be up yet
        msg = f"无法连接 API 地址 {api_url}：{err}"
        raise ResourceTemporarilyUnavailable(msg) from err
    if 400 <= response.status_code < 500:
        # something answered, but not the expected endpoint: wrong address
        msg = f"{api_url} 不是可用的 NeteaseCloudMusicApi 服务地址（HTTP {response.status_code}）"
        raise InvalidDataError(msg)
    try:
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as err:
        msg = f"API 地址 {api_url} 返回错误：{err}"
        raise ResourceTemporarilyUnavailable(msg) from err
    except ValueError as err:
        msg = f"{api_url} 不是可用的 NeteaseCloudMusicApi 服务地址（响应不是 JSON）"
        raise InvalidDataError(msg) from err
    if not isinstance(payload, dict) or not {"data", "code"} & set(payload):
        msg = f"{api_url} 不是可用的 NeteaseCloudMusicApi 服务地址"
        raise InvalidDataError(msg)
