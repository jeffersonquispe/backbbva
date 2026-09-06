from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    ConfigurationRef,
    ExampleCase,
    FilterCondition,
    FilterGroup,
    Flag,
    FlagType,
    GeneralSettings,
    InfraSettings,
    LogicalOperator,
    ModusOperandi,
    MonitoringSettings,
    OpsSettings,
    SegmentSettings,
    Taxonomy,
    TestSettings,
    default_segments,
)
from src.application.ports.tag_catalog_port import TagCategory
from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.test_run_port import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)
from src.application.use_cases.configurations.activate_configuration import (
    ActivateConfigurationUseCase,
    ConfigurationNotFoundError,
    ConfigurationNotTestedError,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationVersionConflictError,
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.get_active_configuration import (
    GetActiveConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration import (
    GetConfigurationUseCase,
)
from src.application.use_cases.configurations.index_configuration_knowledge import (
    IndexConfigurationKnowledgeUseCase,
)
from src.application.use_cases.configurations.list_configuration_versions import (
    ListConfigurationVersionsUseCase,
)
from src.application.use_cases.configurations.list_configurations import (
    ListConfigurationsUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_flag import IngestFlagUseCase
from src.application.use_cases.fraud_knowledge.ingest_modus_operandi import (
    IngestModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_similar_case import (
    IngestSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.ingest_taxonomia import (
    IngestTaxonomiaUseCase,
)


class InMemoryConfigurationRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[str, int], ConfigurationRecord] = {}

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        self.items[(config.configuration_id, config.version)] = config
        return config

    def update(self, config: ConfigurationRecord) -> ConfigurationRecord:
        self.items[(config.configuration_id, config.version)] = config
        return config

    def get(self, configuration_id: str, version: int) -> ConfigurationRecord | None:
        return self.items.get((configuration_id, version))

    def get_latest_version(
        self, configuration_id: str
    ) -> ConfigurationRecord | None:
        versions = self.list_versions(configuration_id)
        if not versions:
            return None
        return max(versions, key=lambda config: config.version)

    def get_active(self) -> ConfigurationRecord | None:
        for config in self.items.values():
            if config.active:
                return config
        return None

    def list_latest(self) -> list[ConfigurationRecord]:
        by_lineage: dict[str, ConfigurationRecord] = {}
        for config in self.items.values():
            current = by_lineage.get(config.configuration_id)
            if current is None or config.version > current.version:
                by_lineage[config.configuration_id] = config
        return list(by_lineage.values())

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]:
        return [
            config
            for (cid, _), config in self.items.items()
            if cid == configuration_id
        ]

    def activate(self, configuration_id: str, version: int) -> ConfigurationRecord:
        current_active = self.get_active()
        if current_active is not None and (
            current_active.configuration_id,
            current_active.version,
        ) != (configuration_id, version):
            self.items[
                (current_active.configuration_id, current_active.version)
            ] = _with_active(current_active, False)
        target = self.items[(configuration_id, version)]
        activated = _with_active(target, True, ever_activated=True)
        self.items[(configuration_id, version)] = activated
        return activated


def _with_active(
    config: ConfigurationRecord, active: bool, *, ever_activated: bool | None = None
) -> ConfigurationRecord:
    return ConfigurationRecord(
        configuration_id=config.configuration_id,
        version=config.version,
        name=config.name,
        description=config.description,
        active=active,
        ever_activated=config.ever_activated if ever_activated is None else ever_activated,
        general=config.general,
        infra=config.infra,
        ops=config.ops,
        test=config.test,
        created_at=config.created_at,
        updated_at=datetime.now(timezone.utc),
        created_by=config.created_by,
        segments=config.segments,
    )


# --- Fraud-knowledge fakes, same pattern as
# tests/test_application/test_use_cases/test_fraud_knowledge/test_ingest_fraud_knowledge.py
# (this codebase has no shared conftest - local fakes per test file).


class InMemoryFraudKnowledgeRepository:
    def __init__(self) -> None:
        self._documents: dict[uuid.UUID, FraudKnowledgeDocument] = {}

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def get(self, document_id: uuid.UUID) -> FraudKnowledgeDocument | None:
        return self._documents.get(document_id)

    def update(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        self._documents.pop(document_id, None)

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        channel: str | None = None,
        configuration: str | None = None,
        version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        results = list(self._documents.values())
        if document_type is not None:
            results = [d for d in results if d.type == document_type]
        if channel is not None:
            results = [d for d in results if d.segmento == channel]
        if configuration is not None:
            results = [d for d in results if d.configuration == configuration]
        if version is not None:
            results = [d for d in results if d.version == version]
        return results


class InMemoryTestRunRepository:
    def __init__(self) -> None:
        self._runs: list[TestRunRecord] = []

    def add_succeeded(self, configuration_id: str, version: int) -> None:
        self._runs.append(
            TestRunRecord(
                id=uuid.uuid4(),
                name="run",
                dataset_name="dataset",
                config=TestRunConfig(
                    configuration_ref=ConfigurationRef(configuration_id, version)
                ),
                status=TestRunStatus.SUCCEEDED,
                total=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )

    def create(self, run: TestRunRecord) -> TestRunRecord:
        self._runs.append(run)
        return run

    def get(self, run_id: uuid.UUID) -> TestRunRecord | None:
        return next((r for r in self._runs if r.id == run_id), None)

    def update(self, run_id, *, status=None, finished_at=None):
        raise NotImplementedError

    def list(self) -> list[TestRunRecord]:
        return list(self._runs)

    def delete(self, run_id: uuid.UUID) -> None:
        self._runs = [r for r in self._runs if r.id != run_id]


class ScriptedEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3] for _ in texts],
            model="fake-embedding-model",
            dimensions=3,
        )


class ScriptedEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def create(
        self, *, model: str, monitoring: MonitoringPort, operation_name: str
    ) -> EmbeddingUnitOfWork:
        return ScriptedEmbeddingUnitOfWork()


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None:
        pass

    def write_result(self, data) -> None:
        pass

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


def _index_use_case(
    fraud_repo: InMemoryFraudKnowledgeRepository,
) -> IndexConfigurationKnowledgeUseCase:
    embedding_factory = ScriptedEmbeddingUnitOfWorkFactory()
    monitoring = NullMonitoringPort()
    kwargs = dict(
        repository=fraud_repo,
        embedding_unit_of_work_factory=embedding_factory,
        monitoring=monitoring,
        embedding_model="fake-deployment",
    )
    return IndexConfigurationKnowledgeUseCase(
        ingest_taxonomia=IngestTaxonomiaUseCase(**kwargs),
        ingest_modus_operandi=IngestModusOperandiUseCase(**kwargs),
        ingest_flag=IngestFlagUseCase(**kwargs),
        ingest_similar_case=IngestSimilarCaseUseCase(**kwargs),
    )


def _create_use_case(
    repo: InMemoryConfigurationRepository,
    fraud_repo: InMemoryFraudKnowledgeRepository | None = None,
) -> CreateConfigurationUseCase:
    return CreateConfigurationUseCase(
        repo, _index_use_case(fraud_repo or InMemoryFraudKnowledgeRepository()),
        InMemoryTestRunRepository(),
    )


def _activate_use_case(
    repo: InMemoryConfigurationRepository,
    fraud_repo: InMemoryFraudKnowledgeRepository | None = None,
    test_run_repo: InMemoryTestRunRepository | None = None,
) -> ActivateConfigurationUseCase:
    return ActivateConfigurationUseCase(
        repo,
        fraud_repo or InMemoryFraudKnowledgeRepository(),
        test_run_repo or InMemoryTestRunRepository(),
    )


def test_create_configuration_starts_new_lineage_at_version_1_inactive() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    record = use_case.execute(CreateConfigurationInput(name="Producción"))

    assert record.version == 1
    assert record.active is False
    assert record.general == GeneralSettings()
    assert record.infra == InfraSettings()
    assert record.ops == OpsSettings()
    assert record.test == TestSettings()
    assert record.segments == default_segments()
    assert set(record.segments) == {"canales_digitales", "tarjetas"}
    assert all(not s.enabled for s in record.segments.values())
    assert all(s.monitoring == MonitoringSettings() for s in record.segments.values())
    assert all(s.agent == AgentSettings() for s in record.segments.values())


def test_create_configuration_with_custom_segment_filter_tree() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    segments = {
        "tarjetas": SegmentSettings(
            enabled=True,
            filter=FilterGroup(
                id="root",
                operator=LogicalOperator.OR,
                conditions=[
                    FilterCondition(
                        id="c1",
                        category=TagCategory.EVENT_TYPE,
                        values=["authentication"],
                    )
                ],
                groups=[
                    FilterGroup(
                        id="g1",
                        operator=LogicalOperator.AND,
                        conditions=[
                            FilterCondition(
                                id="c2",
                                category=TagCategory.TRIGGERED_RULE,
                                values=["CUSTOMER - dg_no_digital"],
                            )
                        ],
                    )
                ],
            ),
        )
    }

    record = use_case.execute(
        CreateConfigurationInput(name="Producción", segments=segments)
    )

    tarjetas = record.segments["tarjetas"]
    assert tarjetas.enabled is True
    assert tarjetas.filter.operator == LogicalOperator.OR
    assert tarjetas.filter.conditions[0].category == TagCategory.EVENT_TYPE
    assert tarjetas.filter.groups[0].conditions[0].values == [
        "CUSTOMER - dg_no_digital"
    ]


def test_create_configuration_appends_new_version_to_existing_lineage() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    v1 = use_case.execute(CreateConfigurationInput(name="Producción"))
    v2 = use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            infra=InfraSettings(max_instances=12, auto_scale=False),
        )
    )

    assert v2.configuration_id == v1.configuration_id
    assert v2.version == 2
    assert v2.active is False
    assert v2.infra.max_instances == 12
    # v1 untouched by creating v2.
    assert repo.get(v1.configuration_id, 1) == v1


def test_create_configuration_rejects_stale_based_on_version() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    v1 = use_case.execute(CreateConfigurationInput(name="Producción"))
    # Someone else appends v2 while our draft still thinks v1 is latest.
    use_case.execute(
        CreateConfigurationInput(
            name="Producción", configuration_id=v1.configuration_id
        )
    )

    with pytest.raises(ConfigurationVersionConflictError):
        use_case.execute(
            CreateConfigurationInput(
                name="Producción",
                configuration_id=v1.configuration_id,
                based_on_version=1,
            )
        )
    # The conflict must not have created a v3 out of the stale draft.
    assert repo.get_latest_version(v1.configuration_id).version == 2


def test_create_configuration_with_matching_based_on_version_overwrites_never_activated_version() -> (
    None
):
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    v1 = use_case.execute(CreateConfigurationInput(name="Producción"))
    saved = use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            based_on_version=1,
            infra=InfraSettings(max_instances=12, auto_scale=False),
        )
    )

    # Small edits on a version that never reached production overwrite that
    # same version in place, instead of piling up a new one for every save.
    assert saved.version == 1
    assert saved.infra.max_instances == 12
    assert repo.get_latest_version(v1.configuration_id).version == 1
    assert repo.get_latest_version(v1.configuration_id).infra.max_instances == 12


def test_create_configuration_mints_new_version_once_latest_was_activated() -> None:
    repo = InMemoryConfigurationRepository()
    test_run_repo = InMemoryTestRunRepository()
    create = _create_use_case(repo)
    activate = _activate_use_case(repo, test_run_repo=test_run_repo)

    v1 = create.execute(CreateConfigurationInput(name="Producción"))
    test_run_repo.add_succeeded(v1.configuration_id, 1)
    activate.execute(v1.configuration_id, 1)

    v2 = create.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            based_on_version=1,
            infra=InfraSettings(max_instances=12),
        )
    )

    # Once a version has ever gone to production it's frozen - the next
    # save mints version+1 instead of overwriting it.
    assert v2.version == 2
    assert v2.active is False
    frozen_v1 = repo.get(v1.configuration_id, 1)
    assert frozen_v1.infra.max_instances == InfraSettings().max_instances
    assert frozen_v1.ever_activated is True


def test_activate_enforces_single_active_invariant_across_activations() -> None:
    repo = InMemoryConfigurationRepository()
    test_run_repo = InMemoryTestRunRepository()
    create = _create_use_case(repo)
    activate = _activate_use_case(repo, test_run_repo=test_run_repo)
    get_active = GetActiveConfigurationUseCase(repo)

    assert get_active.execute() is None

    v1 = create.execute(CreateConfigurationInput(name="Producción"))
    v2 = create.execute(
        CreateConfigurationInput(
            name="Producción", configuration_id=v1.configuration_id
        )
    )
    test_run_repo.add_succeeded(v1.configuration_id, 1)
    test_run_repo.add_succeeded(v2.configuration_id, 2)

    activated_v1 = activate.execute(v1.configuration_id, 1)
    assert activated_v1.active is True
    assert get_active.execute().version == 1

    activated_v2 = activate.execute(v2.configuration_id, 2)
    assert activated_v2.active is True
    active = get_active.execute()
    assert active is not None
    assert active.version == 2
    # Activating v2 must flip v1 back to inactive - exactly one active
    # configuration at any time, across the whole table.
    assert repo.get(v1.configuration_id, 1).active is False


def test_activate_unknown_configuration_raises() -> None:
    repo = InMemoryConfigurationRepository()
    activate = _activate_use_case(repo)

    with pytest.raises(ConfigurationNotFoundError):
        activate.execute("missing", 1)


def test_activate_without_succeeded_test_run_raises() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    activate = _activate_use_case(repo)

    v1 = create.execute(CreateConfigurationInput(name="Producción"))

    with pytest.raises(ConfigurationNotTestedError):
        activate.execute(v1.configuration_id, 1)


def test_activate_ignores_succeeded_test_run_targeting_a_different_version() -> None:
    repo = InMemoryConfigurationRepository()
    test_run_repo = InMemoryTestRunRepository()
    create = _create_use_case(repo)
    activate = _activate_use_case(repo, test_run_repo=test_run_repo)

    v1 = create.execute(CreateConfigurationInput(name="Producción"))
    v2 = create.execute(
        CreateConfigurationInput(
            name="Producción", configuration_id=v1.configuration_id
        )
    )
    # Only v1 has passed a test - v2 must stay blocked even though the
    # lineage as a whole has a succeeded run.
    test_run_repo.add_succeeded(v1.configuration_id, 1)

    with pytest.raises(ConfigurationNotTestedError):
        activate.execute(v2.configuration_id, 2)


def test_list_configurations_returns_one_row_per_lineage_at_latest_version() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    list_configs = ListConfigurationsUseCase(repo)

    prod_v1 = create.execute(CreateConfigurationInput(name="Producción"))
    create.execute(
        CreateConfigurationInput(
            name="Producción", configuration_id=prod_v1.configuration_id
        )
    )
    create.execute(CreateConfigurationInput(name="Staging"))

    summaries = list_configs.execute()

    assert len(summaries) == 2
    by_name = {config.name: config for config in summaries}
    assert by_name["Producción"].version == 2
    assert by_name["Staging"].version == 1


def test_list_configuration_versions_returns_all_versions_sorted() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    list_versions = ListConfigurationVersionsUseCase(repo)

    v1 = create.execute(CreateConfigurationInput(name="Producción"))
    create.execute(
        CreateConfigurationInput(
            name="Producción", configuration_id=v1.configuration_id
        )
    )

    versions = list_versions.execute(v1.configuration_id)

    assert [v.version for v in versions] == [1, 2]


def test_get_configuration_by_id_and_version() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    get_config = GetConfigurationUseCase(repo)

    record = create.execute(CreateConfigurationInput(name="Producción"))

    found = get_config.execute(record.configuration_id, record.version)
    assert found == record
    assert get_config.execute(record.configuration_id, 999) is None


# --- OpenSearch knowledge indexing ------------------------------------


def _agent_with_full_knowledge() -> AgentSettings:
    taxonomy = Taxonomy(
        id="tx-1",
        code="PHISH",
        name="Phishing",
        description="Suplantación de identidad.",
    )
    modus_operandi = ModusOperandi(
        id="mo-1",
        title="Vishing",
        narrative="Llamada suplantando soporte.",
        taxonomy_id="tx-1",
    )
    red_flag = Flag(
        id="rf-1",
        flag_type=FlagType.RED,
        name="Llamada sospechosa",
        description="Llamada de número desconocido.",
        modus_operandi_ids=["mo-1"],
    )
    yellow_flag = Flag(
        id="yf-1",
        flag_type=FlagType.YELLOW,
        name="Cambio reciente de datos",
        description="Cambio de celular en los últimos 7 días.",
        modus_operandi_ids=["mo-1"],
    )
    example_case = ExampleCase(
        id="ec-1",
        text="Cliente reporta llamada de 'soporte' pidiendo el OTP.",
        modus_operandi_id="mo-1",
        taxonomy_id="tx-1",
    )
    return AgentSettings(
        taxonomies=[taxonomy],
        modus_operandi=[modus_operandi],
        flags=[red_flag, yellow_flag],
        example_cases=[example_case],
    )


def test_create_configuration_indexes_full_knowledge_graph_into_opensearch() -> None:
    repo = InMemoryConfigurationRepository()
    fraud_repo = InMemoryFraudKnowledgeRepository()
    use_case = _create_use_case(repo, fraud_repo)

    record = use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            segments={
                "canales_digitales": SegmentSettings(
                    agent=_agent_with_full_knowledge()
                )
            },
        )
    )

    documents = fraud_repo.list()
    assert len(documents) == 5
    assert all(doc.configuration == record.configuration_id for doc in documents)
    assert all(doc.version == record.version for doc in documents)
    # Never active on creation, matches the DynamoDB record's own active=False.
    assert all(doc.activate is False for doc in documents)

    by_type = {doc.type: doc for doc in documents}
    modus_operandi_doc = by_type[DocumentType.MODUS_OPERANDI]
    assert modus_operandi_doc.taxonomia_id == by_type[DocumentType.TAXONOMIA].id
    assert len(modus_operandi_doc.flags) == 2
    assert len(modus_operandi_doc.similar_cases) == 1


def test_create_configuration_indexes_knowledge_per_segment_with_correct_segmento_code() -> (
    None
):
    repo = InMemoryConfigurationRepository()
    fraud_repo = InMemoryFraudKnowledgeRepository()
    use_case = _create_use_case(repo, fraud_repo)

    use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            segments={
                "canales_digitales": SegmentSettings(
                    agent=_agent_with_full_knowledge()
                ),
                "tarjetas": SegmentSettings(
                    agent=_agent_with_full_knowledge()
                ),
            },
        )
    )

    documents = fraud_repo.list()
    assert len(documents) == 10

    canales_docs = fraud_repo.list(channel="canales_digitales")
    tarjetas_docs = fraud_repo.list(channel="tarjetas")
    assert len(canales_docs) == 5
    assert len(tarjetas_docs) == 5
    assert all(doc.segmento == "canales_digitales" for doc in canales_docs)
    assert all(doc.segmento == "tarjetas" for doc in tarjetas_docs)
    # Each segment's ingest gets its own fresh OpenSearch document ids, even
    # though both segments reuse the same domain-level taxonomy/MO ids.
    assert {doc.id for doc in canales_docs}.isdisjoint({doc.id for doc in tarjetas_docs})


def test_create_configuration_with_dangling_taxonomy_reference_raises() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)
    agent = AgentSettings(
        modus_operandi=[
            ModusOperandi(
                id="mo-1", title="x", narrative="y", taxonomy_id="missing-tx"
            )
        ]
    )

    with pytest.raises(ValueError):
        use_case.execute(
            CreateConfigurationInput(
                name="Producción",
                segments={
                    "canales_digitales": SegmentSettings(agent=agent)
                },
            )
        )


def test_activate_flips_opensearch_documents_activate_flag() -> None:
    repo = InMemoryConfigurationRepository()
    fraud_repo = InMemoryFraudKnowledgeRepository()
    test_run_repo = InMemoryTestRunRepository()
    create = _create_use_case(repo, fraud_repo)
    activate = _activate_use_case(repo, fraud_repo, test_run_repo)

    v1 = create.execute(
        CreateConfigurationInput(
            name="Producción",
            segments={
                "canales_digitales": SegmentSettings(
                    agent=_agent_with_full_knowledge()
                )
            },
        )
    )
    v2 = create.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            segments={
                "canales_digitales": SegmentSettings(
                    agent=_agent_with_full_knowledge()
                )
            },
        )
    )
    test_run_repo.add_succeeded(v1.configuration_id, 1)
    test_run_repo.add_succeeded(v2.configuration_id, 2)

    activate.execute(v1.configuration_id, 1)
    assert all(
        doc.activate
        for doc in fraud_repo.list(configuration=v1.configuration_id, version=1)
    )

    activate.execute(v2.configuration_id, 2)
    assert all(
        doc.activate
        for doc in fraud_repo.list(configuration=v2.configuration_id, version=2)
    )
    # v1's documents must flip back to inactive when v2 is activated.
    assert not any(
        doc.activate
        for doc in fraud_repo.list(configuration=v1.configuration_id, version=1)
    )


def test_tested_latest_configuration_is_preserved_after_test_history_deleted() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    original = create.execute(CreateConfigurationInput(name="Protected"))
    original.ever_tested = True
    saved = create.execute(CreateConfigurationInput(
        name="Changed", configuration_id=original.configuration_id, based_on_version=1,
    ))
    assert saved.version == 2
    assert repo.get(original.configuration_id, 1).name == "Protected"
    assert saved.ever_tested is False


def test_legacy_test_run_protects_only_its_configuration_version() -> None:
    repo = InMemoryConfigurationRepository()
    runs = InMemoryTestRunRepository()
    create = CreateConfigurationUseCase(repo, _index_use_case(InMemoryFraudKnowledgeRepository()), runs)
    original = create.execute(CreateConfigurationInput(name="Protected"))
    runs.add_succeeded(original.configuration_id, 1)
    runs._runs[0].status = TestRunStatus.FAILED
    saved = create.execute(CreateConfigurationInput(
        name="Changed", configuration_id=original.configuration_id, based_on_version=1,
    ))
    assert saved.version == 2
    assert repo.get(original.configuration_id, 1).name == "Protected"
    edited = create.execute(CreateConfigurationInput(
        name="Editable", configuration_id=original.configuration_id, based_on_version=2,
    ))
    assert edited.version == 2
