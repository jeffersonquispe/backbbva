from __future__ import annotations

import time

from src.application.ports.modus_operandi_port import (
    ModusOperandiPort,
    SimilarModusOperandi,
)


class MockModusOperandiAdapter(ModusOperandiPort):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarModusOperandi]:
        time.sleep(0.05)
        return [
            SimilarModusOperandi(
                pattern_id="mo-0001",
                description=(
                    "Personal data changed shortly before a transaction "
                    "from a new, unrecognized device."
                ),
                similarity_score=0.75,
            )
        ][:top_k]
