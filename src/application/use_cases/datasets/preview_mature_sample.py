from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.dtos.mature_sample_dtos import MatureSamplePreview
from src.application.ports.alert_port import AlertRepository
from src.application.ports.alert_schema_port import (
    AlertSchemaFieldType,
    AlertSchemaRepository,
    AlertSchemaStatus,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_sampler_state_port import (
    DatasetSamplerStateRepository,
)
from src.application.ports.mature_sampler_schema_mapping_port import (
    MatureSamplerSchemaMappingRepository,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.domain.alerts.entities import AlertRecord
from src.domain.datasets.mature_sampling import (
    alert_field_date,
    is_mature,
    mapped_alert_label,
    stratum_key,
)

_PREVIEW_READ_LIMIT = 20_000
_ALERT_PAGE_SIZE = 500


class PreviewMatureSampleUseCase:
    def __init__(
        self,
        alerts: AlertRepository,
        operational_settings: OperationalSettingsRepository,
        sampler_settings: AssistantOptimizerSettingsPort,
        schemas: AlertSchemaRepository,
        sampler_state: DatasetSamplerStateRepository,
        schema_mapping: MatureSamplerSchemaMappingRepository,
        clock: Clock,
        timezone_name: str,
    ) -> None:
        self._alerts = alerts
        self._operational_settings = operational_settings
        self._sampler_settings = sampler_settings
        self._schemas = schemas
        self._sampler_state = sampler_state
        self._schema_mapping = schema_mapping
        self._clock = clock
        self._timezone = ZoneInfo(timezone_name)

    def execute(self, *, as_of: date | None = None) -> MatureSamplePreview:
        now = self._clock.now().astimezone(self._timezone)
        today = as_of or now.date()
        settings = self._sampler_settings.get()
        mapping = self._schema_mapping.get()
        if not _schema_mapping_is_configured(mapping):
            raise ValueError(
                "Configura la marca inicial, sus fechas y la etiqueta vigente con su mapeo"
            )
        self._validate_schema_mapping(mapping, settings.sampler_compatible_schema_versions)
        maturity = self._operational_settings.get().maturing_days
        period_end = today - timedelta(days=maturity)
        period_start = period_end - timedelta(days=settings.sampler_period_days - 1)
        fields = settings.sampler_strata
        self.validate_selected_fields(
            fields, settings.sampler_compatible_schema_versions
        )
        eligible = collect_mature_alerts(
            self._alerts,
            period_start=period_start,
            period_end=period_end,
            as_of=today,
            maturing_days=maturity,
            target_field=mapping.target_field,
            marking_date_field=mapping.marking_date_field,
            label_value_mapping=mapping.label_value_mapping or {},
            max_read=_PREVIEW_READ_LIMIT,
            limit_error="La vista previa excede el límite de lectura de alertas",
        )

        counts = Counter(
            " | ".join(stratum_key(alert, tuple(fields))) for alert in eligible
        )
        triggers = self._active_triggers(
            eligible,
            settings=settings,
            as_of=today,
            now=now,
            current_strata=dict(counts),
            mapping=mapping,
        )

        sample_size = _estimated_sample_size(settings, len(eligible))
        return MatureSamplePreview(
            eligible_alerts=len(eligible),
            estimated_sample_size=sample_size,
            counts_by_stratum=dict(sorted(counts.items())),
            active_triggers=triggers if settings.sampler_enabled else [],
        )

    def _selected_schema_field_pool(self, compatible_versions: tuple[str, ...]) -> set[str]:
        versions = self._schemas.list_versions()
        if compatible_versions:
            requested = {int(version) for version in compatible_versions}
            versions = [version for version in versions if version.version in requested]
        else:
            active = self._schemas.get_active()
            versions = [active] if active else []
        return {
            field.field
            for version in versions
            if version is not None
            and version.status in {AlertSchemaStatus.ACTIVE, AlertSchemaStatus.HISTORICAL}
            for field in version.fields
            if field.is_alert and not field.is_sensible and not field.is_label
        }

    def available_fields(self) -> list[str]:
        settings = self._sampler_settings.get()
        return sorted(
            self._selected_schema_field_pool(
                settings.sampler_compatible_schema_versions
            )
        )

    def validate_selected_fields(
        self, selected_fields: tuple[str, ...], compatible_versions: tuple[str, ...]
    ) -> None:
        unsupported = set(selected_fields) - self._selected_schema_field_pool(
            compatible_versions
        )
        if unsupported:
            raise ValueError(
                "Los campos de estratificación deben seleccionarse del esquema "
                f"compatible: {', '.join(sorted(unsupported))}"
            )

    def _validate_schema_mapping(
        self, mapping, compatible_versions: tuple[str, ...]
    ) -> None:
        versions = self._schemas.list_versions()
        if compatible_versions:
            selected = {int(value) for value in compatible_versions}
            versions = [version for version in versions if version.version in selected]
        else:
            active = self._schemas.get_active()
            versions = [active] if active else []
        fields = [
            field
            for version in versions
            if version is not None
            and version.status in {AlertSchemaStatus.ACTIVE, AlertSchemaStatus.HISTORICAL}
            for field in version.fields
            if field.is_alert and not field.is_sensible
        ]
        if not any(
            field.field == mapping.initial_mark_field
            and not field.is_label
            and field.type
            in {
                AlertSchemaFieldType.STRING,
                AlertSchemaFieldType.NUMBER,
                AlertSchemaFieldType.BOOL,
            }
            for field in fields
        ):
            raise ValueError("La marca inicial no pertenece al esquema compatible")
        if not any(
            field.field == mapping.initial_marking_date_field
            and field.type in {AlertSchemaFieldType.DATE, AlertSchemaFieldType.DATETIME}
            and not field.is_label
            for field in fields
        ):
            raise ValueError("La fecha inicial no pertenece al esquema compatible")
        if not any(field.field == mapping.target_field and field.is_label for field in fields):
            raise ValueError("El campo objetivo no pertenece al esquema compatible")
        if not any(
            field.field == mapping.marking_date_field
            and field.type in {AlertSchemaFieldType.DATE, AlertSchemaFieldType.DATETIME}
            and not field.is_label
            for field in fields
        ):
            raise ValueError("La fecha de marcación no pertenece al esquema compatible")
        if mapping.initial_marking_date_field == mapping.marking_date_field:
            raise ValueError("Las fechas inicial y de última marcación deben ser distintas")

    def _active_triggers(
        self,
        eligible: list[AlertRecord],
        *,
        settings,
        as_of: date,
        now: datetime,
        current_strata: dict[str, int],
        mapping,
    ) -> list[str]:
        if not settings.sampler_enabled:
            return []
        state = self._sampler_state.get("current")
        last_completed = state.last_completed_at if state else None
        if last_completed and settings.sampler_cooldown_days:
            if now - last_completed.astimezone(self._timezone) < timedelta(
                days=settings.sampler_cooldown_days
            ):
                return []

        active: list[str] = []
        if settings.sampler_period_trigger_enabled:
            if last_completed is None or as_of - last_completed.astimezone(
                self._timezone
            ).date() >= timedelta(
                days=settings.sampler_period_trigger_interval_days
            ):
                active.append("periodic")

        if settings.sampler_volume_trigger_enabled and last_completed:
            newly_matured = sum(
                1
                for alert in eligible
                if mapped_alert_label(
                    alert, mapping.target_field, mapping.label_value_mapping or {}
                ) in {"fraud", "no_fraud"}
                and (marked_at := alert_field_date(alert, mapping.marking_date_field))
                is not None
                and marked_at >= last_completed.astimezone(self._timezone).date()
            )
            if newly_matured >= settings.sampler_volume_threshold:
                active.append("volume")

        if settings.sampler_statistical_trigger_enabled and state:
            previous = state.latest_strata_counts or {}
            if previous and _population_stability_index(current_strata, previous) >= (
                settings.sampler_statistical_trigger_threshold
            ):
                active.append("statistical")
        return active


def _estimated_sample_size(settings, population: int) -> int:
    """Finite-population estimate at the configured confidence and margin."""
    margin = settings.sampler_error_margin_pct / 100
    confidence = settings.sampler_confidence_pct
    z = 1.96 if confidence >= 95 else 1.645 if confidence >= 90 else 1.0
    if population == 0:
        return 0
    if margin <= 0:
        return population
    base = z * z * 0.25 / (margin * margin)
    return min(population, max(1, round(base / (1 + (base - 1) / population))))


def collect_mature_alerts(
    alerts: AlertRepository,
    *,
    period_start: date,
    period_end: date,
    as_of: date,
    maturing_days: int,
    target_field: str,
    marking_date_field: str,
    label_value_mapping: dict[str, str],
    max_read: int,
    limit_error: str,
) -> list[AlertRecord]:
    eligible: list[AlertRecord] = []
    read_count = 0
    day = period_start
    while day <= period_end:
        before = None
        while read_count < max_read:
            requested = min(_ALERT_PAGE_SIZE, max_read - read_count)
            page = alerts.page_by_created_day(day, before=before, limit=requested)
            if not page:
                break
            read_count += len(page)
            eligible.extend(
                alert
                for alert in page
                if is_mature(
                    alert,
                    as_of=as_of,
                    maturing_days=maturing_days,
                    target_field=target_field,
                    marking_date_field=marking_date_field,
                    label_value_mapping=label_value_mapping,
                )
            )
            if len(page) < requested:
                break
            before = page[-1].created_at
        if read_count >= max_read:
            raise ValueError(limit_error)
        day += timedelta(days=1)
    return eligible


def _population_stability_index(
    current: dict[str, int], previous: dict[str, int]
) -> float:
    keys = set(current) | set(previous)
    current_total = sum(current.values())
    previous_total = sum(previous.values())
    if not keys or current_total <= 0 or previous_total <= 0:
        return 0.0
    epsilon = 1e-6
    score = 0.0
    for key in keys:
        current_share = max(epsilon, current.get(key, 0) / current_total)
        previous_share = max(epsilon, previous.get(key, 0) / previous_total)
        score += (current_share - previous_share) * math.log(
            current_share / previous_share
        )
    return score


def _schema_mapping_is_configured(mapping) -> bool:
    return bool(
        mapping.initial_mark_field
        and mapping.initial_marking_date_field
        and mapping.target_field
        and mapping.marking_date_field
        and mapping.label_value_mapping
    )
