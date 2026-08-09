from __future__ import annotations

import time

from src.application.ports.fraud_taxonomy_port import (
    FraudTaxonomyPort,
    SimilarFraudTaxonomy,
)


class MockFraudTaxonomyAdapter(FraudTaxonomyPort):
    def find_similar(self, query: str, top_k: int = 5) -> list[SimilarFraudTaxonomy]:
        time.sleep(0.05)
        return [
            SimilarFraudTaxonomy(
                code="ACCOUNT_TAKEOVER",
                name="Account takeover",
                description=(
                    "Unauthorized party gains control of the customer's "
                    "account, often after a credential or device change."
                ),
                similarity_score=0.78,
            )
        ][:top_k]
