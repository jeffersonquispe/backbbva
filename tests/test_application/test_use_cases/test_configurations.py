from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.errors import ConfigurationWriteConflict
from src.application.ports.clock_port import Clock
from src.application.ports.configuration_deploy_request_port import (
    ConfigurationDeployRequest,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.test_run_port import (
    TestRunConfig as RunConfig,
)
from src.application.ports.test_run_port import (
    TestRunRecord as RunRecord,
)
from src.application.ports.test_run_port import (
    TestRunStatus as RunStatus,
)
from src.application.use_cases.configurations.activate_configuration import (
    ActivateConfigurationUseCase,
    ConfigurationActivationConflictError,
    ConfigurationNotFoundError,
    ConfigurationNotTestedError,
)
from src.application.use_cases.configurations.create_configuration import (
    ConfigurationMergeConflictError,
    ConfigurationVersionConflictError,
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.get_active_configuration import (
    GetActiveConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration import (
    GetConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration_graph import (
    GetConfigurationGraphUseCase,
)
from src.application.use_cases.configurations.list_configuration_versions import (
    ListConfigurationVersionsUseCase,
)
from src.application.use_cases.configurations.list_configurations import (
    ListConfigurationsUseCase,
)
from src.domain.configurations.entities import (
    AgentSettings,
    ConfigurationRecord,
    ConfigurationRef,
    FilterCondition,
    FilterGroup,
    GeneralSettings,
    InfraSettings,
    LogicalOperator,
    MonitoringSettings,
    SegmentSettings,
    TagCategory,
    default_segments,
)
from src.domain.configurations.entities import (
    TestSettings as ConfigSettings,
)


class FixedClock(Clock):
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


class FixedIdGenerator(IdGenerator):
    def __init__(self, generated_id: uuid.UUID) -> None:
        self.generated_id = generated_id

    def new_id(self) -> uuid.UUID:
        return self.generated_id


class InMemoryConfigurationRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[str, int], ConfigurationRecord] = {}

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        key = (config.configuration_id, config.version)
        if key in self.items:
            raise ConfigurationWriteConflict(f"{key} already exists")
        self.items[key] = config
        return config

    def get(self, configuration_id: str, version: int) -> ConfigurationRecord | None:
        return self.items.get((configuration_id, version))

    def list_all_versions(self) -> list[ConfigurationRecord]:
        return list(self.items.values())

    def get_latest_version(self, configuration_id: str) -> ConfigurationRecord | None:
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
            config for (cid, _), config in self.items.items() if cid == configuration_id
        ]

    def activate(
        self,
        configuration_id: str,
        version: int,
        expected_current: tuple[str, int] | None = None,
    ) -> ConfigurationRecord:
        current_active = self.get_active()
        current_key = (
            (current_active.configuration_id, current_active.version)
            if current_active is not None
            else None
        )
        if expected_current is not None and current_key != expected_current:
            raise ConfigurationWriteConflict("stale active configuration")
        if current_active is not None and (
            current_active.configuration_id,
            current_active.version,
        ) != (configuration_id, version):
            self.items[(current_active.configuration_id, current_active.version)] = (
                _with_active(current_active, False)
            )
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
        ever_activated=config.ever_activated
        if ever_activated is None
        else ever_activated,
        schema_version_at_creation=config.schema_version_at_creation,
        general=config.general,
        infra=config.infra,
        test=config.test,
        created_at=config.created_at,
        updated_at=datetime.now(UTC),
        activated_at=(
            datetime.now(UTC)
            if active and not config.activated_at
            else config.activated_at
        ),
        created_by=config.created_by,
        segments=config.segments,
    )


class InMemoryConfigurationDeployRequestRepository:
    def __init__(self, requests: list[ConfigurationDeployRequest]) -> None:
        self.requests = requests

    def list(self) -> list[ConfigurationDeployRequest]:
        return list(self.requests)


class InMemoryTestRunRepository:
    def __init__(self) -> None:
        self._runs: list[RunRecord] = []

    def add_succeeded(self, configuration_id: str, version: int) -> None:
        self._runs.append(
            RunRecord(
                id=uuid.uuid4(),
                name="run",
                dataset_name="dataset",
                config=RunConfig(
                    configuration_ref=ConfigurationRef(configuration_id, version)
                ),
                status=RunStatus.SUCCEEDED,
                total=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    def create(self, run: RunRecord) -> RunRecord:
        self._runs.append(run)
        return run

    def get(self, run_id: uuid.UUID) -> RunRecord | None:
        return next((r for r in self._runs if r.id == run_id), None)

    def update(self, run_id, *, status=None, finished_at=None):
        raise NotImplementedError

    def list(self) -> list[RunRecord]:
        return list(self._runs)

    def delete(self, run_id: uuid.UUID) -> None:
        self._runs = [r for r in self._runs if r.id != run_id]


def _create_use_case(
    repo: InMemoryConfigurationRepository,
) -> CreateConfigurationUseCase:
    return CreateConfigurationUseCase(repo)


def _activate_use_case(
    repo: InMemoryConfigurationRepository,
    test_run_repo: InMemoryTestRunRepository | None = None,
) -> ActivateConfigurationUseCase:
    return ActivateConfigurationUseCase(
        repo, test_run_repo or InMemoryTestRunRepository()
    )


def test_create_configuration_starts_new_lineage_at_version_1_inactive() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    record = use_case.execute(CreateConfigurationInput(name="Producción"))

    assert record.version == 1
    assert record.active is False
    assert record.general == GeneralSettings()
    assert record.infra == InfraSettings()
    assert record.test == ConfigSettings()
    assert record.segments == default_segments()
    assert set(record.segments) == {"canales_digitales", "tarjetas"}
    assert all(not s.enabled for s in record.segments.values())
    assert all(s.monitoring == MonitoringSettings() for s in record.segments.values())
    assert all(s.agent == AgentSettings() for s in record.segments.values())


def test_create_configuration_uses_injected_clock_and_id_generator() -> None:
    repo = InMemoryConfigurationRepository()
    instant = datetime(2025, 2, 3, 4, 5, tzinfo=UTC)
    generated_id = uuid.UUID("00000000-0000-0000-0000-000000000123")
    use_case = CreateConfigurationUseCase(
        repo,
        clock=FixedClock(instant),
        id_generator=FixedIdGenerator(generated_id),
    )

    record = use_case.execute(CreateConfigurationInput(name="Inyectada"))

    assert record.configuration_id == str(generated_id)
    assert record.created_at == instant
    assert record.updated_at == instant


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
    assert v1.parent_ref is None
    assert v2.parent_ref is not None
    assert (v2.parent_ref.configuration_id, v2.parent_ref.version) == (
        v1.configuration_id,
        v1.version,
    )
    # v1 untouched by creating v2.
    assert repo.get(v1.configuration_id, 1) == v1


def test_create_configuration_branch_records_parent_version() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)
    root = use_case.execute(CreateConfigurationInput(name="Producción"))

    branch = use_case.execute(
        CreateConfigurationInput(
            name="Canary",
            parent_ref=ConfigurationRef(root.configuration_id, root.version),
        )
    )

    assert branch.configuration_id != root.configuration_id
    assert branch.version == 1
    assert branch.parent_ref == ConfigurationRef(root.configuration_id, root.version)


def test_create_configuration_merges_independent_stale_channel_edits() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    v1 = use_case.execute(CreateConfigurationInput(name="Producción"))
    # One editor changes the digital channel while another edits cards from
    # the same base version. Saving the stale draft should retain both edits.
    digital = replace(v1.segments["canales_digitales"], enabled=True)
    cards = replace(v1.segments["tarjetas"], enabled=True)
    v2 = use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            based_on_version=1,
            segments={**v1.segments, "canales_digitales": digital},
        )
    )
    v3 = use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            based_on_version=1,
            segments={**v1.segments, "tarjetas": cards},
        )
    )

    assert v2.version == 2
    assert v3.version == 3
    assert v3.segments["canales_digitales"].enabled is True
    assert v3.segments["tarjetas"].enabled is True
    assert repo.get(v1.configuration_id, 1).segments["canales_digitales"].enabled is False


def test_create_configuration_reports_conflicting_stale_channel_edits() -> None:
    repo = InMemoryConfigurationRepository()
    use_case = _create_use_case(repo)

    v1 = use_case.execute(CreateConfigurationInput(name="Producción"))
    use_case.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            based_on_version=1,
            segments={
                **v1.segments,
                "canales_digitales": replace(
                    v1.segments["canales_digitales"], order=3
                ),
            },
        )
    )

    with pytest.raises(ConfigurationMergeConflictError) as error:
        use_case.execute(
            CreateConfigurationInput(
                name="Producción",
                configuration_id=v1.configuration_id,
                based_on_version=1,
                segments={
                    **v1.segments,
                    "canales_digitales": replace(
                        v1.segments["canales_digitales"], order=5
                    ),
                },
            )
        )
    assert "segments.canales_digitales.order" in error.value.paths
    assert repo.get_latest_version(v1.configuration_id).version == 2


def test_create_configuration_rejects_a_racing_duplicate_version() -> None:
    class RacingRepository(InMemoryConfigurationRepository):
        inject_competing_write = False

        def get_latest_version(self, configuration_id: str) -> ConfigurationRecord | None:
            latest = super().get_latest_version(configuration_id)
            if self.inject_competing_write and latest is not None:
                self.inject_competing_write = False
                self.items[(configuration_id, latest.version + 1)] = replace(
                    latest, version=latest.version + 1
                )
            return latest

    repo = RacingRepository()
    use_case = _create_use_case(repo)
    v1 = use_case.execute(CreateConfigurationInput(name="Concurrente"))
    repo.inject_competing_write = True

    with pytest.raises(ConfigurationVersionConflictError, match="changed while"):
        use_case.execute(
            CreateConfigurationInput(
                name="Concurrente editada",
                configuration_id=v1.configuration_id,
                based_on_version=1,
            )
        )
    assert repo.get_latest_version(v1.configuration_id).version == 2


def test_create_configuration_preserves_every_saved_version() -> None:
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

    assert saved.version == 2
    assert saved.infra.max_instances == 12
    assert repo.get(v1.configuration_id, 1).infra.max_instances == v1.infra.max_instances
    assert repo.get_latest_version(v1.configuration_id).version == 2


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
    assert activated_v1.activated_at is not None
    assert get_active.execute().version == 1

    activated_v2 = activate.execute(v2.configuration_id, 2)
    assert activated_v2.active is True
    active = get_active.execute()
    assert active is not None
    assert active.version == 2
    assert active.activated_at is not None
    # Activating v2 must flip v1 back to inactive - exactly one active
    # configuration at any time, across the whole table.
    assert repo.get(v1.configuration_id, 1).active is False


def test_activation_rejects_a_stale_production_snapshot() -> None:
    repo = InMemoryConfigurationRepository()
    test_runs = InMemoryTestRunRepository()
    create = _create_use_case(repo)
    activate = _activate_use_case(repo, test_run_repo=test_runs)
    v1 = create.execute(CreateConfigurationInput(name="Producción"))
    v2 = create.execute(
        CreateConfigurationInput(name="Canary", configuration_id=v1.configuration_id)
    )
    test_runs.add_succeeded(v1.configuration_id, 1)
    test_runs.add_succeeded(v2.configuration_id, 2)
    activate.execute(v1.configuration_id, 1)

    with pytest.raises(ConfigurationActivationConflictError, match="stale active"):
        activate.execute(
            v2.configuration_id,
            2,
            expected_current=("different-config", 1),
        )
    assert repo.get_active().version == 1


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
    assert versions[0].parent_ref is None
    assert versions[1].parent_ref is not None
    assert versions[1].parent_ref.version == versions[0].version


def test_get_configuration_by_id_and_version() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    get_config = GetConfigurationUseCase(repo)

    record = create.execute(CreateConfigurationInput(name="Producción"))

    found = get_config.execute(record.configuration_id, record.version)
    assert found == record
    assert get_config.execute(record.configuration_id, 999) is None


def test_tested_latest_configuration_is_preserved_after_test_history_deleted() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    original = create.execute(CreateConfigurationInput(name="Protected"))
    original.ever_tested = True
    saved = create.execute(
        CreateConfigurationInput(
            name="Changed",
            configuration_id=original.configuration_id,
            based_on_version=1,
        )
    )
    assert saved.version == 2
    assert repo.get(original.configuration_id, 1).name == "Protected"
    assert saved.ever_tested is False


def test_legacy_test_run_protects_only_its_configuration_version() -> None:
    repo = InMemoryConfigurationRepository()
    runs = InMemoryTestRunRepository()
    create = CreateConfigurationUseCase(repo)
    original = create.execute(CreateConfigurationInput(name="Protected"))
    runs.add_succeeded(original.configuration_id, 1)
    runs._runs[0].status = RunStatus.FAILED
    saved = create.execute(
        CreateConfigurationInput(
            name="Changed",
            configuration_id=original.configuration_id,
            based_on_version=1,
        )
    )
    assert saved.version == 2
    assert repo.get(original.configuration_id, 1).name == "Protected"
    edited = create.execute(
        CreateConfigurationInput(
            name="Editable",
            configuration_id=original.configuration_id,
            based_on_version=2,
        )
    )
    assert edited.version == 3


def _deploy_request(
    record: ConfigurationRecord, message: str, *, status: str, minute: int
) -> ConfigurationDeployRequest:
    moment = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    return ConfigurationDeployRequest(
        id=f"req-{minute}",
        target_configuration_id=record.configuration_id,
        target_version=record.version,
        current_configuration_id=None,
        current_version=None,
        title="t",
        message=message,
        changes=[],
        requested_by="a",
        requested_at=moment,
        status=status,
        approved_at=moment if status == "approved" else None,
    )


def test_configuration_graph_returns_parents_and_the_promotion_comment() -> None:
    repo = InMemoryConfigurationRepository()
    create = _create_use_case(repo)
    root = create.execute(CreateConfigurationInput(name="Producción"))
    child = create.execute(
        CreateConfigurationInput(
            name="Producción", configuration_id=root.configuration_id
        )
    )
    branch = create.execute(
        CreateConfigurationInput(
            name="Canary",
            parent_ref=ConfigurationRef(root.configuration_id, root.version),
        )
    )
    repo.items[(root.configuration_id, root.version)] = replace(
        root, ever_activated=True
    )
    requests = InMemoryConfigurationDeployRequestRepository(
        [
            _deploy_request(root, "primer comentario", status="approved", minute=1),
            _deploy_request(root, "comentario vigente", status="approved", minute=2),
            _deploy_request(root, "sin aprobar", status="pending", minute=3),
            # Never promoted, so its approved comment must not surface.
            _deploy_request(child, "no promovida", status="approved", minute=4),
        ]
    )

    nodes = GetConfigurationGraphUseCase(repo, requests).execute()

    by_key = {(n.record.configuration_id, n.record.version): n for n in nodes}
    assert len(nodes) == 3
    assert by_key[(root.configuration_id, 1)].promotion_comment == "comentario vigente"
    assert by_key[(child.configuration_id, 2)].promotion_comment is None
    assert by_key[(branch.configuration_id, 1)].record.parent_ref == ConfigurationRef(
        root.configuration_id, root.version
    )
    assert by_key[(branch.configuration_id, 1)].promotion_comment is None


# --- vector-store generation pins: saving pins, publishing needs approval ---


class InMemoryVectorStoreGenerationRepository:
    def __init__(self, ready: dict[tuple[str, int], str]) -> None:
        self.status = ready

    def get(self, instance_id: str, generation: int):
        from src.domain.fraud_knowledge.vector_store_generations import (
            VectorStoreGeneration,
            VectorStoreGenerationStatus,
        )

        status = self.status.get((instance_id, generation))
        if status is None:
            return None
        return VectorStoreGeneration(
            instance_id,
            generation,
            VectorStoreGenerationStatus(status),
            "qa",
            datetime.now(UTC),
        )

    def list(self, instance_id=None):
        return [
            self.get(key[0], key[1])
            for key in sorted(self.status)
            if instance_id in (None, key[0])
        ]


class RecordingVectorStoreBuild:
    """Builds the next generation number each time the manifest is pinned."""

    def __init__(self, generations: InMemoryVectorStoreGenerationRepository) -> None:
        self.generations = generations
        self.calls: list[str] = []

    def execute(self, instance_id: str, *, actor: str):
        from types import SimpleNamespace

        self.calls.append(instance_id)
        number = 1 + max(
            (key[1] for key in self.generations.status if key[0] == instance_id),
            default=0,
        )
        self.generations.status[(instance_id, number)] = "ready"
        return SimpleNamespace(generation=self.generations.get(instance_id, number))


def _vector_store_segments(generation: int | None = None) -> dict:
    segments = default_segments()
    research = segments["tarjetas"].agent.classification.delegated_research.vector_store
    research.enabled = True
    research.vector_store_instance_id = "vector-store-v1"
    research.vector_store_generation = generation
    return segments


def _pinning(repo, test_runs, generations):
    from src.application.use_cases.vector_store_instances.pin_configuration_vector_stores import (
        PinConfigurationVectorStoresUseCase,
    )

    build = RecordingVectorStoreBuild(generations)
    pins = PinConfigurationVectorStoresUseCase(build, generations)
    create = CreateConfigurationUseCase(repo, vector_store_pins=pins)
    activate = ActivateConfigurationUseCase(repo, test_runs, vector_store_pins=pins)
    return create, activate, build


def _pinned_generation(record: ConfigurationRecord) -> int | None:
    return record.segments[
        "tarjetas"
    ].agent.classification.delegated_research.vector_store.vector_store_generation


def test_saving_a_configuration_pins_the_vector_store_generation() -> None:
    repo, test_runs = InMemoryConfigurationRepository(), InMemoryTestRunRepository()
    generations = InMemoryVectorStoreGenerationRepository({})
    create, _, build = _pinning(repo, test_runs, generations)

    record = create.execute(
        CreateConfigurationInput(name="Producción", segments=_vector_store_segments())
    )

    assert _pinned_generation(record) == 1
    assert _pinned_generation(repo.get(record.configuration_id, 1)) == 1
    assert build.calls == ["vector-store-v1"]


def test_direct_activation_cannot_publish_a_new_generation() -> None:
    from src.application.use_cases.configurations.activate_configuration import (
        VectorStorePublicationRequiresApprovalError,
    )

    repo, test_runs = InMemoryConfigurationRepository(), InMemoryTestRunRepository()
    generations = InMemoryVectorStoreGenerationRepository(
        {("vector-store-v1", 1): "ready", ("vector-store-v1", 2): "ready"}
    )
    create, activate, _ = _pinning(repo, test_runs, generations)
    v1 = create.execute(
        CreateConfigurationInput(name="Producción", segments=_vector_store_segments(1))
    )
    v2 = create.execute(
        CreateConfigurationInput(
            name="Producción",
            configuration_id=v1.configuration_id,
            segments=_vector_store_segments(2),
        )
    )
    test_runs.add_succeeded(v1.configuration_id, 1)
    test_runs.add_succeeded(v1.configuration_id, 2)
    activate.execute(v1.configuration_id, 1, approved_deploy_request=True)

    with pytest.raises(VectorStorePublicationRequiresApprovalError):
        activate.execute(v2.configuration_id, 2)
    assert repo.get_active().version == 1

    # The same version goes live once its deploy request is approved.
    activate.execute(v2.configuration_id, 2, approved_deploy_request=True)
    assert repo.get_active().version == 2
    assert _pinned_generation(repo.get_active()) == 2


def test_activation_rejects_a_retired_generation_pin() -> None:
    from src.application.use_cases.configurations.activate_configuration import (
        ConfigurationVectorStoreUnavailableError,
    )

    repo, test_runs = InMemoryConfigurationRepository(), InMemoryTestRunRepository()
    generations = InMemoryVectorStoreGenerationRepository(
        {("vector-store-v1", 1): "ready"}
    )
    create, activate, _ = _pinning(repo, test_runs, generations)
    v1 = create.execute(
        CreateConfigurationInput(name="Producción", segments=_vector_store_segments(1))
    )
    test_runs.add_succeeded(v1.configuration_id, 1)
    generations.status[("vector-store-v1", 1)] = "retired"

    with pytest.raises(ConfigurationVectorStoreUnavailableError, match="retired"):
        activate.execute(v1.configuration_id, 1, approved_deploy_request=True)
    assert repo.get_active() is None
