from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from darkpulse.ingestion.checkpoints import CheckpointStore
from darkpulse.ingestion.collectors.base import BaseCollector, CollectorHealth, HealthStatus
from darkpulse.ingestion.collectors.http import CollectionError
from darkpulse.ingestion.collectors.registry import SourceDefinition
from darkpulse.ingestion.hashing import sha256_hex
from darkpulse.ingestion.records import SourceRecord
from darkpulse.models import ContentType, CrawlMetadata, SourceClass


@dataclass(frozen=True, slots=True)
class PublicTelegramMessage:
    message_id: int
    text: str
    observed_at: datetime
    media_ignored: bool = False

    def __post_init__(self) -> None:
        if self.message_id <= 0:
            raise ValueError("Telegram message ID must be positive")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Telegram message timestamp must include a timezone")


class TelegramReader(Protocol):
    def iter_public_messages(
        self,
        channel: str,
        *,
        min_id: int,
        limit: int,
    ) -> AsyncIterator[PublicTelegramMessage]: ...


def public_channel_name(locator: str) -> str:
    parsed = urlsplit(locator)
    if parsed.scheme.casefold() != "https" or parsed.hostname not in {"t.me", "telegram.me"}:
        raise ValueError("Telegram source must be a public HTTPS channel URL")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Telegram channel URL cannot include credentials, query, or fragment")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 1 or parts[0].casefold() == "joinchat" or parts[0].startswith("+"):
        raise ValueError("Telegram source must identify one public channel")
    return parts[0]


class TelegramCollector(BaseCollector):
    def __init__(
        self,
        *,
        source: SourceDefinition,
        checkpoints: CheckpointStore,
        reader: TelegramReader,
        max_messages: int = 100,
    ) -> None:
        if source.source_class is not SourceClass.TELEGRAM:
            raise ValueError("Telegram collector requires a telegram source")
        self._channel = public_channel_name(source.locator)
        if not 1 <= max_messages <= 1000:
            raise ValueError("max_messages must be between 1 and 1000")
        super().__init__(
            source_id=source.source_id,
            source_class=source.source_class,
            checkpoints=checkpoints,
            enabled=source.enabled,
        )
        self._source = source
        self._reader = reader
        self._max_messages = max_messages
        self._last_failure_code: str | None = None
        self._has_succeeded = False

    async def _collect(self) -> AsyncIterator[SourceRecord]:
        checkpoint = await self.checkpoint()
        try:
            min_id = int(checkpoint.cursor) if checkpoint else 0
        except ValueError:
            raise CollectionError("checkpoint_invalid", self.source_id) from None

        try:
            async for message in self._reader.iter_public_messages(
                self._channel,
                min_id=min_id,
                limit=self._max_messages,
            ):
                text = message.text.strip()
                if not text:
                    await self.save_checkpoint(str(message.message_id))
                    continue
                source_bytes = text.encode("utf-8")
                message_url = f"https://t.me/{self._channel}/{message.message_id}"
                yield SourceRecord(
                    source_class=SourceClass.TELEGRAM,
                    source_ref=message_url,
                    content_type=ContentType.MESSAGE,
                    mime_type="text/plain",
                    raw_content=text,
                    source_bytes=source_bytes,
                    captured_at=datetime.now(UTC),
                    source_observed_at=message.observed_at,
                    crawl_metadata=CrawlMetadata(
                        source_item_id=str(message.message_id),
                    ),
                    source_metadata={
                        "channel_ref_sha256": sha256_hex(self._channel.encode("utf-8")),
                        "collector": "telegram_public_read_only",
                        "media_ignored": message.media_ignored,
                        "source_id": self.source_id,
                    },
                )
                await self.save_checkpoint(str(message.message_id))
        except CollectionError:
            raise
        except Exception:
            self._last_failure_code = "telegram_read_failed"
            raise CollectionError("telegram_read_failed", self.source_id) from None

        self._last_failure_code = None
        self._has_succeeded = True

    async def _health(self) -> CollectorHealth:
        if self._last_failure_code:
            return CollectorHealth.create(
                self.source_id,
                HealthStatus.UNHEALTHY,
                reason_code=self._last_failure_code,
            )
        if not self._has_succeeded:
            return CollectorHealth.create(
                self.source_id,
                HealthStatus.DEGRADED,
                reason_code="not_collected",
            )
        return CollectorHealth.create(self.source_id, HealthStatus.HEALTHY)


class TelethonPublicReader:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def iter_public_messages(
        self,
        channel: str,
        *,
        min_id: int,
        limit: int,
    ) -> AsyncIterator[PublicTelegramMessage]:
        async for message in self._client.iter_messages(
            channel,
            min_id=min_id,
            limit=limit,
            reverse=True,
        ):
            if message.date is None:
                continue
            yield PublicTelegramMessage(
                message_id=int(message.id),
                text=str(message.message or ""),
                observed_at=message.date,
                media_ignored=message.media is not None,
            )


def _validated_session_path(session_path: Path, runtime_root: Path) -> Path:
    resolved_root = runtime_root.resolve()
    resolved_session = session_path.resolve()
    if not resolved_session.is_relative_to(resolved_root):
        raise ValueError("Telegram session must be stored inside the runtime directory")
    return resolved_session


async def connect_authorized_telegram_client(
    *,
    session_path: Path,
    runtime_root: Path,
    api_id: int,
    api_hash: str,
) -> Any:

    from telethon import TelegramClient

    resolved_session = _validated_session_path(session_path, runtime_root)
    if api_id <= 0 or not api_hash:
        raise ValueError("Telegram API credentials are not configured")
    client = TelegramClient(str(resolved_session), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Telegram session is not authorized")
    return client


async def bootstrap_telegram_session(
    *,
    session_path: Path,
    runtime_root: Path,
    api_id: int,
    api_hash: str,
    client_factory: Any | None = None,
) -> None:

    resolved_session = _validated_session_path(session_path, runtime_root)
    if api_id <= 0 or not api_hash:
        raise ValueError("Telegram API credentials are not configured")
    resolved_session.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved_session.parent.chmod(0o700)
    if client_factory is None:
        from telethon import TelegramClient

        client_factory = TelegramClient
    client = client_factory(str(resolved_session), api_id, api_hash)
    try:
        await client.start()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session authorization did not complete")
    finally:
        await client.disconnect()
        session_file = (
            resolved_session
            if resolved_session.suffix == ".session"
            else Path(f"{resolved_session}.session")
        )
        for private_file in (session_file, Path(f"{session_file}-journal")):
            if private_file.is_file():
                private_file.chmod(0o600)
