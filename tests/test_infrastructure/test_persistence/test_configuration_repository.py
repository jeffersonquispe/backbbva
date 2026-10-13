from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from src.application.ports.configuration_port import (
    AdversarialConfig,
    AgentSettings,
    AnalystConfig,
    ClassificationConfig,
    ConfigurationRecord,
    DeterministicConfig,
    DelegatedResearchSettings,
    DeterministicRule,
    DayProfile,
    DistributionValue,
    DocumentationConfig,
    DocumentationStrategy,
    ExampleCase,
    ExecutorConfig,
    FilterCondition,
    Flag,
    FlagType,
    GeneralSettings,
    InfraSettings,
    HistoryPandasResearchConfig,
    ModusOperandi,
    MonitoringSettings,
    ProfilingConfig,
    ProfilingPromptMode,
    ProfilingStrategy,
    ProfilingStrategyKey,
    PromptField,
    Rubric,
    RuleCondition,
    SamplingCriterion,
    SegmentSettings,
    Taxonomy,
    TestCleanupPolicy,
    TestSettings,
    VectorStoreResearchConfig,
    VoicebotCategoryPrompt,
    VoicebotConfig,
    default_segments,
)
from src.application.ports.tag_catalog_port import TagCategory
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    _config_key,
    _criterion_key,
    _group_key,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_item_mapping import (
    _day_profile_from_item,
    _distribution_value_from_item,
    _evaluation_from_item,
    _example_case_from_item,
    _filter_condition_from_item,
    _flag_from_item,
    _from_item,
    _general_from_item,
    _infra_from_item,
    _modus_operandi_from_item,
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
        active=True,
        description="desc",
        created_by="carlos",
        ever_activated=True,
        ever_tested=True,
        activated_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )

    restored = _from_item(_to_item(record))

    assert restored.configuration_id == "cfg-1"
    assert restored.version == 1
    assert restored.name == "Producción"
    assert restored.description == "desc"
    assert restored.active is True
    assert restored.ever_activated is True
    assert restored.ever_tested is True
    assert restored.activated_at == record.activated_at
    assert restored.created_by == "carlos"
    assert restored.general == GeneralSettings()
    assert restored.infra == InfraSettings()
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
                watchlist_enabled=True,
                use_xgboost_model=True,
                xgboost_model_id="model-1",
                watchlist_ids=["wl-1"],
                watchlist_compare_field="documento",
                prompt="clasifica esta alerta",
                prompt_vars=["Saldo"],
                delegated_research=DelegatedResearchSettings(
                    vector_store=VectorStoreResearchConfig(
                        enabled=True,
                        vector_store_instance_id="research-vs-1",
                        similarity_threshold=0.82,
                    ),
                    history_pandas=HistoryPandasResearchConfig(
                        enabled=True,
                        allowed_columns=["amount", "channel"],
                        max_history_rows=250,
                        window_days=15,
                    ),
                ),
            ),
            adversarial=AdversarialConfig(
                prompt="ataca esta clasificación",
                prompt_vars=["Última transacción"],
                max_cycles=3,
                feed_feedback_to_classification=False,
            ),
            executor=ExecutorConfig(
                aric_marking=PromptField(
                    prompt="marca esta alerta",
                    prompt_vars=["Saldo"],
                ),
                voicebot_call=VoicebotConfig(
                    base_prompt="hola, soy el asistente",
                    base_prompt_vars=["Saldo"],
                ),
                documentador=DocumentationConfig(
                    strategy=DocumentationStrategy.AGENT,
                    template="plantilla",
                    template_vars=["Saldo"],
                    agent_prompt="documenta esta alerta",
                    agent_prompt_vars=["Última transacción"],
                ),
                analyst_escalation=PromptField(
                    prompt="escala esta alerta",
                    prompt_vars=["Última transacción"],
                ),
            ),
            rubrics=[Rubric(id="fraud-score", name="estafa_score", conditions=[RuleCondition(id="device", variable="device", comparison="neq", values=["iphone"], score=5.5)])],
        ),
    )
    # taxonomies/modus_operandi/flags/example_cases/
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
    assert restored.agent.executor.voicebot_call.category_prompts == []
    assert restored.agent.classification.use_xgboost_model is True
    assert restored.agent.classification.xgboost_model_id == "model-1"
    assert restored.agent.classification.watchlist_enabled is True
    assert restored.agent.classification.watchlist_ids == ["wl-1"]
    assert restored.agent.classification.watchlist_compare_field == "documento"
    assert restored.agent.classification.prompt == "clasifica esta alerta"
    assert restored.agent.classification.delegated_research.vector_store.enabled is True
    assert restored.agent.classification.delegated_research.vector_store.vector_store_instance_id == "research-vs-1"
    assert restored.agent.classification.delegated_research.vector_store.similarity_threshold == 0.82
    assert restored.agent.classification.delegated_research.history_pandas.allowed_columns == ["amount", "channel"]
    assert restored.agent.classification.delegated_research.history_pandas.max_history_rows == 250
    assert restored.agent.classification.delegated_research.history_pandas.window_days == 15
    assert restored.agent.adversarial.max_cycles == 3
    assert restored.agent.adversarial.feed_feedback_to_classification is False
    assert restored.agent.executor.aric_marking.prompt == "marca esta alerta"
    assert restored.agent.executor.voicebot_call.base_prompt == "hola, soy el asistente"
    assert restored.agent.executor.documentador.strategy == DocumentationStrategy.AGENT
    assert restored.agent.executor.documentador.agent_prompt == "documenta esta alerta"
    assert restored.agent.executor.analyst_escalation.prompt == "escala esta alerta"


def test_segment_hydration_tolerates_pre_migration_agent_field_names() -> None:
    # Regression: _agent_from_item splats each stored sub-dict as kwargs,
    # so a row written before a field rename/removal still carries the old
    # key and would otherwise raise "unexpected keyword argument" on every
    # hydration - this took down aria-api's startup seeding locally.
    item = {
        "config_key": _config_key("cfg-1", 1),
        "id": _SEGMENT_ID,
        "segment_code": "tarjetas",
        **_segment_to_item(SegmentSettings()),
    }
    for step in ("detector", "classification", "adversarial", "detector_adversarial"):
        item["agent"][step]["vector_store_instance_ids"] = ["stale-a"]
    item["agent"]["detector"]["enable_pandas_history_tool"] = True
    item["agent"]["classification"]["delegated_research"]["priority"] = "pandas_first"

    restored = _segment_settings_from_item(item)

    assert restored.agent.classification.delegated_research.vector_store.enabled is False


def test_legacy_direct_vector_store_selection_becomes_the_research_tool() -> None:
    # "Base de conocimiento" (top-level vector_store_enabled/_instance_id)
    # was unified into the vector-store research tool - a saved selection must
    # survive the migration instead of silently turning off.
    item = {
        "config_key": _config_key("cfg-1", 1),
        "id": _SEGMENT_ID,
        "segment_code": "tarjetas",
        **_segment_to_item(SegmentSettings()),
    }
    item["agent"]["adversarial"]["vector_store_enabled"] = True
    item["agent"]["adversarial"]["vector_store_instance_id"] = "vs-legacy"

    restored = _segment_settings_from_item(item)

    vector_store = restored.agent.adversarial.delegated_research.vector_store
    assert vector_store.enabled is True
    assert vector_store.vector_store_instance_id == "vs-legacy"
    assert restored.agent.classification.delegated_research.vector_store.enabled is False


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
        migration_window_enabled=True,
        migration_window_datetime="2026-01-01T03:00",
    )
    item = {
        "configuration_id": "cfg-1",
        "version": 1,
        **asdict(general),
    }

    assert _general_from_item(item) == general


def test_general_ignores_legacy_on_off_switches() -> None:
    # Old rows still carry agent/analyst/voicebot switches - those live in
    # OperationalSettings now, so reading them back must not break.
    item = {
        "configuration_id": "cfg-1",
        "version": 1,
        "agent_enabled": False,
        "analyst_escalation_enabled": False,
        "voicebot_escalation_enabled": False,
        "migration_window_enabled": True,
    }

    assert _general_from_item(item) == GeneralSettings(migration_window_enabled=True)


def test_analyst_prompt_survives_segment_round_trip() -> None:
    segment = SegmentSettings(
        enabled=True,
        agent=AgentSettings(
            analyst=AnalystConfig(prompt="sigue {playbook}", prompt_vars=["playbook"])
        ),
    )
    item = {
        "config_key": _config_key("cfg-1", 1),
        "id": _SEGMENT_ID,
        "segment_code": "tarjetas",
        **_segment_to_item(segment),
    }

    restored = _segment_settings_from_item(item)

    assert restored.agent.analyst == AnalystConfig(
        prompt="sigue {playbook}", prompt_vars=["playbook"]
    )


def test_infra_round_trips_through_its_own_table_item() -> None:
    infra = InfraSettings(max_instances=16, auto_scale=False)
    item = {"configuration_id": "cfg-1", "version": 1, **asdict(infra)}

    assert _infra_from_item(item) == infra


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
