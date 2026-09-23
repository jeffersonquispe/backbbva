from __future__ import annotations

from uuid import UUID

from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    FlagType,
)
from src.application.ports.fraud_knowledge_port import DocumentType
from src.application.use_cases.fraud_knowledge.ingest_flag import (
    IngestFlagInput,
    IngestFlagUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_modus_operandi import (
    IngestModusOperandiInput,
    IngestModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_similar_case import (
    IngestSimilarCaseInput,
    IngestSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_taxonomia import (
    IngestTaxonomiaInput,
    IngestTaxonomiaUseCase,
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
        ingest_flag: IngestFlagUseCase,
        ingest_similar_case: IngestSimilarCaseUseCase,
    ) -> None:
        self._ingest_taxonomia = ingest_taxonomia
        self._ingest_modus_operandi = ingest_modus_operandi
        self._ingest_flag = ingest_flag
        self._ingest_similar_case = ingest_similar_case

    def execute(self, record: ConfigurationRecord) -> None:
        for segment_code, segment_settings in record.segments.items():
            self._index_segment(record, segment_code, segment_settings.agent)

    def _index_segment(
        self, record: ConfigurationRecord, segment_code: str, agent: AgentSettings
    ) -> None:
        taxonomy_by_id = {t.id: t for t in agent.taxonomies}

        taxonomia_os_id: dict[str, UUID] = {}
        for taxonomy in agent.taxonomies:
            # taxonomy.code is a system-generated relational identifier, not a
            # human-authored mnemonic - only name/description are meaningful
            # to index for search.
            text = f"{taxonomy.name}: {taxonomy.description}"
            if taxonomy.examples:
                text += ". Ejemplos: " + "; ".join(taxonomy.examples)
            created = self._ingest_taxonomia.execute(
                IngestTaxonomiaInput(
                    text=text,
                    segmento=segment_code,
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
                    segmento=segment_code,
                    configuration=record.configuration_id,
                    version=record.version,
                    taxonomia_id=taxonomia_os_id[mo.taxonomy_id],
                    taxonomia=taxonomy.name,
                    activate=record.active,
                )
            )
            modus_operandi_os_id[mo.id] = created.id

        for flag in agent.flags:
            self._ingest_flag.execute(
                IngestFlagInput(
                    text=f"{flag.name}: {flag.description}",
                    flag_type=(
                        DocumentType.RED_FLAG
                        if flag.flag_type == FlagType.RED
                        else DocumentType.YELLOW_FLAG
                    ),
                    segmento=segment_code,
                    configuration=record.configuration_id,
                    version=record.version,
                    modus_operandi_ids=[
                        self._resolve_modus_operandi(modus_operandi_os_id, mid)
                        for mid in flag.modus_operandi_ids
                    ],
                    activate=record.active,
                )
            )

        for example_case in agent.example_cases:
            self._ingest_similar_case.execute(
                IngestSimilarCaseInput(
                    text=example_case.text,
                    segmento=segment_code,
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
