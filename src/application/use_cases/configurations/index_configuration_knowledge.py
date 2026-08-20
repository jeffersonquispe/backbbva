from __future__ import annotations

from uuid import UUID

from src.application.ports.configuration_port import ConfigurationRecord
from src.application.use_cases.fraud_knowledge.ingest_modus_operandi import (
    IngestModusOperandiInput,
    IngestModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_red_flag import (
    IngestRedFlagInput,
    IngestRedFlagUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_similar_case import (
    IngestSimilarCaseInput,
    IngestSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_taxonomia import (
    IngestTaxonomiaInput,
    IngestTaxonomiaUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_yellow_flag import (
    IngestYellowFlagInput,
    IngestYellowFlagUseCase,
)


class IndexConfigurationKnowledgeUseCase:
    """Rebuilds a configuration version's OpenSearch fraud_knowledge
    documents from its DynamoDB agent settings - taxonomies, modus
    operandi, red/yellow flags, example cases. Each configuration version
    gets its own fresh generation of documents (stamped with
    configuration_id + version), mirroring how DynamoDB versions are
    already immutable once created.

    # ponytail: no rollback/retry if an ingest call fails partway - the
    # DynamoDB record (source of truth) still exists but is left
    # partially/un-indexed. Add a standalone reindex endpoint if that ever
    # becomes a real operational problem.
    """

    def __init__(
        self,
        ingest_taxonomia: IngestTaxonomiaUseCase,
        ingest_modus_operandi: IngestModusOperandiUseCase,
        ingest_red_flag: IngestRedFlagUseCase,
        ingest_yellow_flag: IngestYellowFlagUseCase,
        ingest_similar_case: IngestSimilarCaseUseCase,
    ) -> None:
        self._ingest_taxonomia = ingest_taxonomia
        self._ingest_modus_operandi = ingest_modus_operandi
        self._ingest_red_flag = ingest_red_flag
        self._ingest_yellow_flag = ingest_yellow_flag
        self._ingest_similar_case = ingest_similar_case

    def execute(self, record: ConfigurationRecord) -> None:
        agent = record.agent
        taxonomy_by_id = {t.id: t for t in agent.taxonomies}

        taxonomia_os_id: dict[str, UUID] = {}
        for taxonomy in agent.taxonomies:
            text = f"{taxonomy.code} — {taxonomy.name}: {taxonomy.description}"
            if taxonomy.examples:
                text += ". Ejemplos: " + "; ".join(taxonomy.examples)
            created = self._ingest_taxonomia.execute(
                IngestTaxonomiaInput(
                    text=text,
                    segmento=taxonomy.segmento,
                    configuration=record.configuration_id,
                    version=record.version,
                    activate=record.active,
                )
            )
            taxonomia_os_id[taxonomy.id] = created.id

        modus_operandi_os_id: dict[str, UUID] = {}
        for mo in agent.modus_operandi:
            taxonomy = taxonomy_by_id.get(mo.taxonomy_id)
            if taxonomy is None:
                raise ValueError(
                    f"modus operandi {mo.id!r} references unknown "
                    f"taxonomy_id {mo.taxonomy_id!r}"
                )
            created = self._ingest_modus_operandi.execute(
                IngestModusOperandiInput(
                    text=f"{mo.title}: {mo.narrative}",
                    segmento=mo.segmento,
                    configuration=record.configuration_id,
                    version=record.version,
                    taxonomia_id=taxonomia_os_id[mo.taxonomy_id],
                    taxonomia=taxonomy.name,
                    activate=record.active,
                )
            )
            modus_operandi_os_id[mo.id] = created.id

        for red_flag in agent.red_flags:
            self._ingest_red_flag.execute(
                IngestRedFlagInput(
                    text=f"{red_flag.name}: {red_flag.description}",
                    segmento=red_flag.segmento,
                    configuration=record.configuration_id,
                    version=record.version,
                    modus_operandi_id=self._resolve_modus_operandi(
                        modus_operandi_os_id, red_flag.modus_operandi_id
                    ),
                    taxonomia_id=self._resolve_taxonomia(
                        taxonomia_os_id, red_flag.taxonomy_id
                    ),
                    activate=record.active,
                )
            )

        for yellow_flag in agent.yellow_flags:
            self._ingest_yellow_flag.execute(
                IngestYellowFlagInput(
                    text=f"{yellow_flag.name}: {yellow_flag.description}",
                    segmento=yellow_flag.segmento,
                    configuration=record.configuration_id,
                    version=record.version,
                    modus_operandi_id=self._resolve_modus_operandi(
                        modus_operandi_os_id, yellow_flag.modus_operandi_id
                    ),
                    taxonomia_id=self._resolve_taxonomia(
                        taxonomia_os_id, yellow_flag.taxonomy_id
                    ),
                    activate=record.active,
                )
            )

        for example_case in agent.example_cases:
            self._ingest_similar_case.execute(
                IngestSimilarCaseInput(
                    text=example_case.text,
                    segmento=example_case.segmento,
                    configuration=record.configuration_id,
                    version=record.version,
                    modus_operandi_id=self._resolve_modus_operandi(
                        modus_operandi_os_id, example_case.modus_operandi_id
                    ),
                    taxonomia_id=self._resolve_taxonomia(
                        taxonomia_os_id, example_case.taxonomy_id
                    ),
                    activate=record.active,
                )
            )

    @staticmethod
    def _resolve_modus_operandi(
        modus_operandi_os_id: dict[str, UUID], modus_operandi_id: str
    ) -> UUID:
        resolved = modus_operandi_os_id.get(modus_operandi_id)
        if resolved is None:
            raise ValueError(
                f"references unknown modus_operandi_id {modus_operandi_id!r}"
            )
        return resolved

    @staticmethod
    def _resolve_taxonomia(
        taxonomia_os_id: dict[str, UUID], taxonomy_id: str
    ) -> UUID:
        resolved = taxonomia_os_id.get(taxonomy_id)
        if resolved is None:
            raise ValueError(f"references unknown taxonomy_id {taxonomy_id!r}")
        return resolved
