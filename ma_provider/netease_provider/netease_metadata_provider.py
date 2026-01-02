"""Netease Cloud Music Metadata provider for Music Assistant."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from music_assistant_models.enums import ProviderFeature
from music_assistant_models.media_items import MediaItemMetadata, Track

from music_assistant.models.metadata_provider import MetadataProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry, ConfigValueType, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

_LOGGER = logging.getLogger(__name__)


SUPPORTED_FEATURES = {
    ProviderFeature.TRACK_METADATA,
    ProviderFeature.LYRICS,
}


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    return NeteaseMetadataProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: MusicAssistant,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, ConfigValueType] | None = None,
) -> tuple[ConfigEntry, ...]:
    """
    Return Config entries to setup this provider.

    instance_id: id of an existing provider instance (None if new instance setup).
    action: [optional] action key called from config entries UI.
    values: the (intermediate) raw values for config entries sent with the action.
    """
    # This metadata provider will use the same configuration as the main NeteaseProvider
    # ruff: noqa: ARG001
    return ()


class NeteaseMetadataProvider(MetadataProvider):
    """Netease Cloud Music Metadata provider for handling lyrics."""

    async def handle_async_init(self) -> None:
        """Handle async initialization of the provider."""
        # Find the associated Netease music provider instance to reuse its API client
        self._netease_provider = None
        for prov in self.mass.music.providers:
            if prov.domain == "netease_provider" and hasattr(prov, 'get_lyrics'):
                self._netease_provider = prov
                break

        if not self._netease_provider:
            _LOGGER.warning(
                "Netease music provider not found. "
                "Lyrics functionality will not be available."
            )

    async def get_track_metadata(self, track: Track) -> MediaItemMetadata | None:
        """Retrieve metadata for a track, including lyrics."""
        # Check if lyrics are already available in the track metadata
        if track.metadata and (track.metadata.lyrics or track.metadata.lrc_lyrics):
            self.logger.debug("Skipping lyrics lookup for %s: Already has lyrics", track.name)
            return None

        # Ensure we have both track name and artist information
        if not track.name or len(track.name.strip()) == 0:
            self.logger.info("Skipping lyrics lookup for track: No track name information")
            return None

        if not track.artists:
            self.logger.info("Skipping lyrics lookup for %s: No artist information", track.name)
            return None

        # If we don't have a netease provider instance, we can't look up lyrics
        if not self._netease_provider:
            self.logger.info("Netease music provider not available for lyrics lookup")
            return None

        # Find a track with a provider mapping to get the provider track ID
        prov_track_id = None
        for prov_mapping in track.provider_mappings:
            if prov_mapping.provider_domain == "netease_provider":
                prov_track_id = prov_mapping.item_id
                break

        # If we don't have a netease provider-specific track ID, we can't look up lyrics
        if not prov_track_id:
            self.logger.info("Skipping lyrics lookup for %s: No netease provider mapping found", track.name)
            return None

        # Get lyrics using the netease provider's get_lyrics method
        track_lyrics = await self._netease_provider.get_lyrics(prov_track_id)

        if track_lyrics:
            # Create and return new metadata with lyrics
            metadata = MediaItemMetadata()
            metadata.lyrics = track_lyrics

            self.logger.debug("Found lyrics for %s", track.name)
            return metadata

        self.logger.info("No lyrics found for %s", track.name)
        return None
