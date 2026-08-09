from __future__ import annotations

import time

from src.application.ports.fraud_similarity_port import (
    SimilarFraudCase,
    SimilarFraudCasePort,
)


class MockSimilarFraudCaseAdapter(SimilarFraudCasePort):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudCase]:
        time.sleep(0.05)
        return [
            SimilarFraudCase(
                case_id="case-0001",
                summary="Device change followed by high-value transfer.",
                outcome="confirmed_fraud",
                similarity_score=0.82,
            )
        ][:top_k]
