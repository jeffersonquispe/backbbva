from __future__ import annotations

from src.application.ports.channel_library_port import (
    ChannelLibraryEntry,
    ChannelLibraryRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateChannelLibraryEntryUseCase:
    def __init__(
        self,
        channel_library_repository: ChannelLibraryRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._entries = channel_library_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        code: str,
        name: str,
        description: str = "",
    ) -> ChannelLibraryEntry:
        now = self._clock.now()
        return self._entries.create(
            ChannelLibraryEntry(
                id=str(self._id_generator.new_id()),
                code=code,
                name=name,
                description=description,
                created_at=now,
                updated_at=now,
            )
        )
