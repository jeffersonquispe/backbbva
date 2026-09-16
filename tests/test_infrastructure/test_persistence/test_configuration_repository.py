from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from src.application.ports.configuration_port import (
    AdversarialConfig,
    AgentSettings,
    AnalystCapacity,
    AnalystConfig,
    AnalystPlaybook,
    BuiltInTool,
    ClassificationConfig,
    ConfigurationRecord,
    DeterministicConfig,
    DeterministicRule,
    DayProfile,
    DistributionValue,
    DocumentationConfig,
    DocumentationStrategy,
    ExampleCase,
    FilterCondition,
    Flag,
    FlagType,
    GeneralSettings,
    InfraSettings,
    ModusOperandi,
    MonitoringSettings,
    OpsSettings,
    ProfilingConfig,
    ProfilingPromptMode,
    ProfilingStrategy,
    ProfilingStrategyKey,
    ResolutionTag,
    Rubric,
    RuleCondition,
    SamplingCriterion,
    SamplingIntervalUnit,
    SegmentSettings,
    ShortageBehavior,
    Taxonomy,
    TestCleanupPolicy,
    TestSettings,
    VectorStoreTool,
    VoicebotCategoryPrompt,
    VoicebotConfig,
    default_segments,
)
from src.application.ports.tag_catalog_port import TagCategory
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    _config_key,
    _criterion_key,
    _day_profile_from_item,
    _distribution_value_from_item,
    _evaluation_from_item,
    _example_case_from_item,
    _filter_condition_from_item,
    _flag_from_item,
    _from_item,
    _general_from_item,
    _group_key,
    _infra_from_item,
    _modus_operandi_from_item,
    _operations_payload,
    _ops_from_item,
    _playbook_from_item,
    _profiling_strategy_from_item,
    _sampling_criterion_from_item,
    _segment_settings_from_item,
    _segment_to_item,
    _taxonomy_from_item,
    _to_item,
    _voicebot_category_prompt_from_item,
)

# A segment row's `id` is a real uuid (born in create()) - any opaque string
# works to exercise the pure FK-string builders/decoders below, so tests
# use a fixed placeholder rather than generating one.
_SEGMENT_ID = "5d1f7e2a-2222-4b3b-9a3a-111111111111"


def _base_record(**overrides) -> ConfigurationRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        configuration_id="cfg-1",
        version=1,
        name="Producción",
        description="",
        active=False,
        general=GeneralSettings(),
        infra=InfraSettings(),
        ops=OpsSettings(),
        test=TestSettings(),
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return ConfigurationRecord(**defaults)


def test_owner_item_round_trips_through_to_item_and_from_item() -> None:
    # general/infra/ops/test/segments all live in their own tables now (see
    # DynamoConfigurationRepository) - _to_item/_from_item only carry
    # name/description/active/timestamps, exercised here; every extracted
    # section has its own round-trip test below.
    record = _base_record(
        active=True, description="desc", created_by="carlos", ever_activated=True, ever_tested=True
    )

    restored = _from_item(_to_item(record))

    assert restored.configuration_id == "cfg-1"
    assert restored.version == 1
    assert restored.name == "Producción"
    assert restored.description == "desc"
    assert restored.active is True
    assert restored.ever_activated is True
    assert restored.ever_tested is True
    assert restored.created_by == "carlos"
    assert restored.general == GeneralSettings()
    assert restored.infra == InfraSettings()
    assert restored.ops == OpsSettings()
    assert restored.test == TestSettings()
    # ConfigurationRecord.segments defaults via default_factory here since
    # _to_item/_from_item no longer carry it - DynamoConfigurationRepository
    # ._hydrate replaces this placeholder with rows queried from
    # configuration_segments right after _from_item.
    assert restored.segments == default_segments()


def test_segment_round_trips_through_its_own_table_item() -> None:
    segment = SegmentSettings(
        enabled=True,
        monitoring=MonitoringSettings(
            prompt_clasificacion="clasifica",
            prompt_clasificacion_vars=["Saldo"],
            max_samples=42,
        ),
        agent=AgentSettings(
            deterministic=DeterministicConfig(
                alert_filter={"id": "scope", "operator": "and", "conditions": [], "groups": []},
                field_enrichment={"schema_version": 2, "mappings": {"timezone": "America/Bogota"}, "recipes": []},
                rules=[DeterministicRule(id="hard-rule", variable="amount", comparison="gt", values=["3000"], score=10.5, decision="risk")],
            ),
            profiling=ProfilingConfig(
                # Unlike the other collections below, field_enrichment is a
                # plain dict (a FeatureConfiguration - see feature_recipe.py)
                # and travels inline on this item, not in its own table - a
                # float in a recipe step exercises the to_dynamodb/
                # from_dynamodb Decimal round-trip a real DynamoDB put_item
                # would otherwise reject.
                field_enrichment={
                    "schema_version": 2,
                    "mappings": {"timezone": "America/Bogota", "history": "history"},
                    "recipes": [
                        {
                            "id": "r1",
                            "name": "saldo_enriquecido",
                            "enabled": True,
                            "output_type": "number",
                            "source": "current",
                            "path": "saldo",
                            "missing": {"policy": "missing"},
                            "steps": [
                                {"id": "s1", "operation": "add", "value": 1_000_000.5}
                            ],
                        }
                    ],
                },
                strategies=[
                    ProfilingStrategy(
                        key=ProfilingStrategyKey.USUARIO,
                        main_prompt="perfil",
                    ),
                    ProfilingStrategy(key=ProfilingStrategyKey.TRANSACCION),
                    ProfilingStrategy(key=ProfilingStrategyKey.TRANSACCIONAL),
                ],
            ),
            classification=ClassificationConfig(
                vector_store_tools=[
                    VectorStoreTool.TAXONOMIA,
                    VectorStoreTool.RED_FLAG,
                ],
                built_in_tools=[BuiltInTool.BLACKLIST],
                prompt="clasifica esta alerta",
                prompt_vars=["Saldo"],
            ),
            adversarial=AdversarialConfig(
                prompt="ataca esta clasificación",
                prompt_vars=["Última transacción"],
                max_cycles=3,
                feed_feedback_to_classification=False,
            ),
            analyst=AnalystConfig(
                voicebot=VoicebotConfig(
                    base_prompt="hola, soy el asistente",
                    base_prompt_vars=["Saldo"],
                ),
            ),
            documentation=DocumentationConfig(
                strategy=DocumentationStrategy.AGENT,
                template="plantilla",
                template_vars=["Saldo"],
                agent_prompt="documenta esta alerta",
                agent_prompt_vars=["Última transacción"],
            ),
            rubrics=[Rubric(id="fraud-score", name="estafa_score", conditions=[RuleCondition(id="device", variable="device", comparison="neq", values=["iphone"], score=5.5)])],
        ),
    )
    # taxonomies/modus_operandi/flags/example_cases/playbooks/
    # voicebot.category_prompts/monitoring.sampling_criteria/filter/
    # profiling.strategies all live in their own tables (own FK = this row's
    # uuid `id`) - exercised separately below and via the real tables in
    # local/CI. profiling.field_enrichment is the one exception: it's a
    # plain dict, not a dataclass list, so it travels inline on this item.
    item = {
        "config_key": _config_key("cfg-1", 1),
        "id": _SEGMENT_ID,
        "segment_code": "tarjetas",
        **_segment_to_item(segment),
    }

    restored = _segment_settings_from_item(item)

    assert restored.enabled is True
    assert restored.filter.id == "root"  # own tables - placeholder here
    assert restored.monitoring.prompt_clasificacion == "clasifica"
    assert restored.monitoring.prompt_clasificacion_vars == ["Saldo"]
    assert restored.monitoring.max_samples == 42
    assert restored.monitoring.sampling_criteria == []
    # own table now - placeholder (full default chain) here
    assert restored.agent.profiling.strategies == [
        ProfilingStrategy(key=key) for key in ProfilingStrategyKey
    ]
    assert restored.agent.profiling.field_enrichment == segment.agent.profiling.field_enrichment
    assert restored.agent.deterministic == segment.agent.deterministic
    assert restored.agent.rubrics == segment.agent.rubrics
    assert restored.agent.taxonomies == []
    assert restored.agent.modus_operandi == []
    assert restored.agent.flags == []
    assert restored.agent.example_cases == []
    assert restored.agent.analyst.playbooks == []
    assert restored.agent.analyst.voicebot.category_prompts == []
    assert restored.agent.classification.vector_store_tools == [
        VectorStoreTool.TAXONOMIA,
        VectorStoreTool.RED_FLAG,
    ]
    assert restored.agent.classification.built_in_tools == [BuiltInTool.BLACKLIST]
    assert restored.agent.classification.prompt == "clasifica esta alerta"
    assert restored.agent.adversarial.max_cycles == 3
    assert restored.agent.adversarial.feed_feedback_to_classification is False
    assert restored.agent.analyst.voicebot.base_prompt == "hola, soy el asistente"
    assert restored.agent.documentation.strategy == DocumentationStrategy.AGENT
    assert restored.agent.documentation.agent_prompt == "documenta esta alerta"


def test_default_segment_round_trips_through_its_own_table_item() -> None:
    item = {
        "config_key": _config_key("cfg-1", 1),
        "id": _SEGMENT_ID,
        "segment_code": "canales_digitales",
        **_segment_to_item(SegmentSettings()),
    }

    restored = _segment_settings_from_item(item)

    assert restored.enabled is False
    assert restored.monitoring == MonitoringSettings()
    assert restored.agent == AgentSettings()


def test_fk_keys_scope_by_configuration_version_group_and_criterion() -> None:
    assert _config_key("cfg-1", 1) == "cfg-1#000001"
    assert _config_key("cfg-1", 2) != _config_key("cfg-1", 1)

    assert _group_key(_SEGMENT_ID, "g1") == f"{_SEGMENT_ID}#g1"
    assert _group_key(_SEGMENT_ID, "g1") != _group_key(_SEGMENT_ID, "g2")

    assert _criterion_key(_SEGMENT_ID, "sc-1") == f"{_SEGMENT_ID}#sc-1"
    assert _criterion_key(_SEGMENT_ID, "sc-1") != _criterion_key(_SEGMENT_ID, "sc-2")


def test_general_round_trips_through_its_own_table_item() -> None:
    general = GeneralSettings(
        agent_enabled=False,
        migration_window_enabled=True,
        migration_window_datetime="2026-01-01T03:00",
    )
    item = {
        "configuration_id": "cfg-1",
        "version": 1,
        **asdict(general),
    }

    assert _general_from_item(item) == general


def test_infra_round_trips_through_its_own_table_item() -> None:
    infra = InfraSettings(max_instances=16, auto_scale=False)
    item = {"configuration_id": "cfg-1", "version": 1, **asdict(infra)}

    assert _infra_from_item(item) == infra


def test_operations_round_trips_through_its_own_table_item_minus_profiles() -> None:
    ops = OpsSettings(
        voicebot_max_concurrent_calls=99,
        analyst_capacity=AnalystCapacity(
            profiles=[
                DayProfile(
                    id="regular",
                    name="Día regular",
                    description="",
                    hourly=[4] * 24,
                )
            ],
            default_profile_id="regular",
            day_overrides={15: "pago"},
        ),
        queue_max_lifetime_value=120,
        queue_max_lifetime_unit=SamplingIntervalUnit.HOURS,
        queue_discard_amount_threshold=15000,
        voicebot_shortage_behavior=ShortageBehavior(
            resolution_tag=ResolutionTag.BLOCK_HARD, resolution_method_id="rm-1"
        ),
        analyst_shortage_behavior=ShortageBehavior(
            resolution_tag=ResolutionTag.BLOCK_SOFT, resolution_method_id="rm-2"
        ),
    )
    item = {
        "configuration_id": "cfg-1",
        "version": 1,
        **_operations_payload(ops),
    }

    restored = _ops_from_item(item)

    # profiles live in configuration_analyst_profiles now - the repository
    # fills this back in after _ops_from_item via a separate query.
    assert restored.analyst_capacity.profiles == []
    assert restored.analyst_capacity.default_profile_id == "regular"
    assert restored.analyst_capacity.day_overrides == {15: "pago"}
    assert restored.voicebot_max_concurrent_calls == 99
    assert restored.queue_max_lifetime_value == 120
    assert restored.queue_max_lifetime_unit == SamplingIntervalUnit.HOURS
    assert restored.queue_discard_amount_threshold == 15000
    assert restored.voicebot_shortage_behavior.resolution_tag == ResolutionTag.BLOCK_HARD
    assert restored.voicebot_shortage_behavior.resolution_method_id == "rm-1"
    assert restored.analyst_shortage_behavior.resolution_tag == ResolutionTag.BLOCK_SOFT
    assert restored.analyst_shortage_behavior.resolution_method_id == "rm-2"


def test_evaluation_round_trips_through_its_own_table_item() -> None:
    evaluation = TestSettings(
        max_test_instances=10,
        max_concurrent_experiments=5,
        experiment_timeout_minutes=60,
        max_stored_test_runs=50,
        test_cleanup_policy=TestCleanupPolicy.FAILED_FIRST,
    )
    item = {"configuration_id": "cfg-1", "version": 1, **asdict(evaluation)}

    assert _evaluation_from_item(item) == evaluation


def test_day_profile_round_trips_through_its_own_table_item() -> None:
    profile = DayProfile(
        id="pago", name="Día de pago", description="refuerzo", hourly=[8] * 24
    )
    item = {"config_key": _config_key("cfg-1", 1), **asdict(profile)}

    assert _day_profile_from_item(item) == profile


def test_profiling_strategy_round_trips_through_its_own_table_item() -> None:
    strategy = ProfilingStrategy(
        key=ProfilingStrategyKey.USUARIO,
        main_prompt="perfil",
        main_prompt_vars=["Saldo"],
        main_prompt_mode=ProfilingPromptMode.LLM,
        categorization_prompt="categoriza",
        categorization_prompt_vars=["Saldo"],
        use_pandas_history_mcp=True,
    )
    # Keyed by `key`, not a uuid - a strategy has no separate identity.
    item = {"segment_id": _SEGMENT_ID, **asdict(strategy)}

    assert _profiling_strategy_from_item(item) == strategy


def test_taxonomy_round_trips_through_its_own_table_item() -> None:
    taxonomy = Taxonomy(
        id="tx-1",
        code="X",
        name="X",
        description="desc",
        variables=["Saldo"],
        examples=["ej"],
        active=False,
        segmento="tarjetas",
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(taxonomy)}

    assert _taxonomy_from_item(item) == taxonomy


def test_modus_operandi_round_trips_through_its_own_table_item() -> None:
    modus_operandi = ModusOperandi(
        id="mo-1",
        title="T",
        narrative="N",
        taxonomy_id="tx-1",
        evolved_variables=["Saldo"],
        active=False,
        segmento="tarjetas",
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(modus_operandi)}

    assert _modus_operandi_from_item(item) == modus_operandi


def test_flag_round_trips_through_its_own_table_item() -> None:
    flag = Flag(
        id="fl-1",
        flag_type=FlagType.RED,
        name="F",
        description="",
        evolved_variables=["Saldo"],
        modus_operandi_ids=["mo-1", "mo-2"],
        segmento="tarjetas",
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(flag)}

    assert _flag_from_item(item) == flag


def test_example_case_round_trips_through_its_own_table_item() -> None:
    example_case = ExampleCase(
        id="ex-1",
        text="texto",
        modus_operandi_id="mo-1",
        taxonomy_id="tx-1",
        segmento="tarjetas",
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(example_case)}

    assert _example_case_from_item(item) == example_case


def test_playbook_round_trips_through_its_own_table_item() -> None:
    playbook = AnalystPlaybook(
        id="pb-1",
        name="Escalar a analista",
        strategy="revisar historial",
        resolution_tag=ResolutionTag.SCALE_TO_ANALYST,
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(playbook)}

    assert _playbook_from_item(item) == playbook


def test_voicebot_category_prompt_round_trips_through_its_own_table_item() -> None:
    prompt = VoicebotCategoryPrompt(
        id="vcp-1", taxonomy_id="tx-1", prompt="pregunta sobre X"
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(prompt)}

    assert _voicebot_category_prompt_from_item(item) == prompt


def test_sampling_criterion_round_trips_through_its_own_table_item() -> None:
    criterion = SamplingCriterion(
        id="sc-1",
        name="Monto",
        values=[DistributionValue(id="v-1", label="alto", pct=30)],
    )
    item = {"segment_id": _SEGMENT_ID, **asdict(criterion)}

    assert _sampling_criterion_from_item(item) == criterion


def test_distribution_value_round_trips_through_its_own_table_item() -> None:
    value = DistributionValue(id="v-1", label="alto", pct=30)
    item = {"criterion_key": _criterion_key(_SEGMENT_ID, "sc-1"), **asdict(value)}

    assert _distribution_value_from_item(item) == value


def test_filter_condition_round_trips_through_its_own_table_item() -> None:
    condition = FilterCondition(
        id="c1", category=TagCategory.TRIGGERED_RULE, values=["dg_no_digital"]
    )
    item = {"group_key": _group_key(_SEGMENT_ID, "root"), **asdict(condition)}

    assert _filter_condition_from_item(item) == condition
