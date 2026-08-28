from __future__ import annotations

from src.application.ports.configuration_port import (
    AgentSettings,
    FilterCondition,
    FilterGroup,
    LogicalOperator,
    MonitoringSettings,
    SegmentCode,
    SegmentSettings,
)
from src.application.ports.tag_catalog_port import TagCategory
from src.application.use_cases.alerts.resolve_alert_segment import (
    ResolveAlertSegmentUseCase,
)


def _segment(*, enabled: bool, filter: FilterGroup) -> SegmentSettings:
    return SegmentSettings(
        enabled=enabled,
        filter=filter,
        monitoring=MonitoringSettings(),
        agent=AgentSettings(),
    )


def _condition(category: TagCategory, values: list[str], id: str = "c1") -> FilterCondition:
    return FilterCondition(id=id, category=category, values=values)


def test_single_condition_matches_and_does_not_match() -> None:
    use_case = ResolveAlertSegmentUseCase()
    matching_filter = FilterGroup(
        id="root",
        conditions=[_condition(TagCategory.EVENT_TYPE, ["login"])],
    )
    segments = {
        SegmentCode.TARJETAS.value: _segment(enabled=True, filter=matching_filter),
    }

    assert (
        use_case.execute({"event_type": "login"}, segments)
        == SegmentCode.TARJETAS.value
    )
    assert use_case.execute({"event_type": "logout"}, segments) is None


def test_and_group_requires_all_children() -> None:
    use_case = ResolveAlertSegmentUseCase()
    filter_group = FilterGroup(
        id="root",
        operator=LogicalOperator.AND,
        conditions=[
            _condition(TagCategory.EVENT_TYPE, ["login"], id="c1"),
            _condition(TagCategory.INTEGRATION_POINT, ["web"], id="c2"),
        ],
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=filter_group)}

    assert (
        use_case.execute(
            {"event_type": "login", "integration_point": "web"}, segments
        )
        == SegmentCode.TARJETAS.value
    )
    assert (
        use_case.execute(
            {"event_type": "login", "integration_point": "mobile"}, segments
        )
        is None
    )


def test_or_group_requires_any_child() -> None:
    use_case = ResolveAlertSegmentUseCase()
    filter_group = FilterGroup(
        id="root",
        operator=LogicalOperator.OR,
        conditions=[
            _condition(TagCategory.EVENT_TYPE, ["login"], id="c1"),
            _condition(TagCategory.INTEGRATION_POINT, ["web"], id="c2"),
        ],
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=filter_group)}

    assert (
        use_case.execute(
            {"event_type": "logout", "integration_point": "web"}, segments
        )
        == SegmentCode.TARJETAS.value
    )
    assert (
        use_case.execute(
            {"event_type": "logout", "integration_point": "mobile"}, segments
        )
        is None
    )


def test_nested_group_matches() -> None:
    use_case = ResolveAlertSegmentUseCase()
    inner = FilterGroup(
        id="inner",
        operator=LogicalOperator.OR,
        conditions=[_condition(TagCategory.EVENT_TYPE, ["login"], id="c2")],
    )
    outer = FilterGroup(
        id="root",
        operator=LogicalOperator.AND,
        conditions=[_condition(TagCategory.INTEGRATION_POINT, ["web"], id="c1")],
        groups=[inner],
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=outer)}

    assert (
        use_case.execute(
            {"event_type": "login", "integration_point": "web"}, segments
        )
        == SegmentCode.TARJETAS.value
    )
    assert (
        use_case.execute(
            {"event_type": "logout", "integration_point": "web"}, segments
        )
        is None
    )


def test_empty_filter_group_matches_everything() -> None:
    use_case = ResolveAlertSegmentUseCase()
    segments = {
        SegmentCode.TARJETAS.value: _segment(
            enabled=True, filter=FilterGroup(id="root")
        )
    }

    assert use_case.execute({}, segments) == SegmentCode.TARJETAS.value


def test_disabled_segment_never_matches() -> None:
    use_case = ResolveAlertSegmentUseCase()
    segments = {
        SegmentCode.TARJETAS.value: _segment(
            enabled=False, filter=FilterGroup(id="root")
        )
    }

    assert use_case.execute({}, segments) is None


def test_tie_break_returns_first_declared_segment_code() -> None:
    use_case = ResolveAlertSegmentUseCase()
    catch_all = FilterGroup(id="root")
    segments = {
        SegmentCode.TARJETAS.value: _segment(enabled=True, filter=catch_all),
        SegmentCode.CANALES_DIGITALES.value: _segment(enabled=True, filter=catch_all),
    }

    assert use_case.execute({}, segments) == SegmentCode.CANALES_DIGITALES.value


def test_no_match_returns_none() -> None:
    use_case = ResolveAlertSegmentUseCase()
    filter_group = FilterGroup(
        id="root", conditions=[_condition(TagCategory.EVENT_TYPE, ["login"])]
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=filter_group)}

    assert use_case.execute({"event_type": "other"}, segments) is None


def test_rules_normalization_list_of_dicts_shape() -> None:
    use_case = ResolveAlertSegmentUseCase()
    filter_group = FilterGroup(
        id="root",
        conditions=[_condition(TagCategory.TRIGGERED_RULE, ["CUSTOMER - dg_no_digital"])],
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=filter_group)}

    mandatory_fields = {"rules": [{"name": "CUSTOMER - dg_no_digital"}]}
    assert (
        use_case.execute(mandatory_fields, segments) == SegmentCode.TARJETAS.value
    )


def test_rules_normalization_bracketed_string_shape() -> None:
    use_case = ResolveAlertSegmentUseCase()
    filter_group = FilterGroup(
        id="root",
        conditions=[_condition(TagCategory.TRIGGERED_RULE, ["CUSTOMER - Score1000Net"])],
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=filter_group)}

    mandatory_fields = {"rules": "[CUSTOMER - Score1000Net]"}
    assert (
        use_case.execute(mandatory_fields, segments) == SegmentCode.TARJETAS.value
    )


def test_missing_fields_never_crash_and_produce_no_match() -> None:
    use_case = ResolveAlertSegmentUseCase()
    filter_group = FilterGroup(
        id="root",
        conditions=[_condition(TagCategory.EVENT_TYPE, ["login"])],
    )
    segments = {SegmentCode.TARJETAS.value: _segment(enabled=True, filter=filter_group)}

    assert use_case.execute({}, segments) is None
