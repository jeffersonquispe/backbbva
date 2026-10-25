from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.application.ports.agent_confirmation_port import (
    AgentConfirmation,
    AgentConfirmationRepository,
)
from src.application.ports.agent_message_port import AgentMessageRepository
from src.application.ports.agent_package_port import (
    AgentPackage,
    AgentPackageRepository,
)
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
    AgentStructuredGenerator,
)
from src.application.ports.agent_verification_port import (
    AgentVerification,
    AgentVerificationRepository,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.flag_library_port import (
    FlagLibraryRepository,
    FlagLibraryRevisionConflict,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.domain.configurations.entities import FlagType

PROMPT_NAME = "agent.flag.generate"
OPEN_STATUSES = {
    AgentSessionStatus.DRAFT,
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.PAUSED,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.WAITING_APPROVAL,
}
FIELDS = (
    "flag_type",
    "name",
    "description",
    "evolved_variables",
    "modus_operandi_library_ids",
)


class FlagDraftNotFoundError(Exception):
    pass


class FlagDraftPolicyError(Exception):
    pass


class FlagDraftConflictError(Exception):
    pass


@dataclass(frozen=True)
class GenerateFlagDraftInput:
    session_id: str
    owner_id: str
    client_message_id: str
    operation: str
    target_id: str | None = None


@dataclass(frozen=True)
class FlagDraftResult:
    package: AgentPackage
    verifications: tuple[AgentVerification, ...]


class GenerateFlagDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        messages: AgentMessageRepository,
        prompts: AgentPromptRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        entries: FlagLibraryRepository,
        modus_operandi: ModusOperandiLibraryRepository,
        settings: AssistantOptimizerSettingsPort,
        generator: AgentStructuredGenerator,
        masker: PersonalDataMasker,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions, self._messages, self._prompts = sessions, messages, prompts
        self._packages, self._verifications, self._entries = (
            packages,
            verifications,
            entries,
        )
        self._modus, self._settings, self._generator = (
            modus_operandi,
            settings,
            generator,
        )
        self._masker, self._clock, self._ids = masker, clock, ids

    def execute(self, request: GenerateFlagDraftInput) -> FlagDraftResult:
        session = self._sessions.get(request.session_id)
        if (
            session is None
            or session.owner_id != request.owner_id
            or session.mode != "assistant"
        ):
            raise FlagDraftNotFoundError("assistant session not found")
        settings = self._settings.get()
        if session.status not in OPEN_STATUSES or not settings.assistant_enabled:
            raise FlagDraftPolicyError("assistant session is closed or disabled")
        if request.operation not in {"create", "update"} or (
            (request.operation == "update") != bool(request.target_id)
        ):
            raise FlagDraftPolicyError("invalid operation or target")
        message = self._messages.get_by_client_message_id(
            request.session_id, request.client_message_id
        )
        if (
            message is None
            or message.role != "user"
            or message.author_id != request.owner_id
        ):
            raise FlagDraftNotFoundError("source message not found")
        source = self._masker.mask(message.content).text
        if len(source) > settings.assistant_max_message_chars:
            raise FlagDraftPolicyError("source message exceeds configured limit")
        current = self._entries.get(request.target_id) if request.target_id else None
        if request.target_id and current is None:
            raise FlagDraftNotFoundError("flag not found")
        active = self._prompts.get_active(PROMPT_NAME)
        if active is None:
            raise FlagDraftPolicyError("flag prompt unavailable")
        pinned = session.prompt_versions.get(PROMPT_NAME, {}).get("version")
        prompt = self._prompts.get_version(
            PROMPT_NAME, int(pinned) if pinned is not None else active.version
        )
        if prompt is None:
            raise FlagDraftPolicyError("flag prompt version unavailable")
        old = _entity(current) if current else None
        related_modus_operandi = [
            {
                "id": entry.id,
                "title": entry.title,
                "taxonomy_library_id": entry.taxonomy_library_id,
                "active": entry.active,
            }
            for entry in self._modus.list()[:50]
            if entry.active
        ]
        raw = self._generator.generate(
            AgentStructuredGenerationInput(
                system_prompt=prompt.content,
                persisted_context=json.dumps(
                    {
                        "operation": request.operation,
                        "current_entry": old,
                        "flag_type_enum": ["red", "yellow"],
                        "related_modus_operandi": related_modus_operandi,
                    },
                    ensure_ascii=False,
                ),
                masked_user_message=source,
            )
        )
        try:
            payload = json.loads(_strip_fence(raw))
        except (ValueError, TypeError) as error:
            raise FlagDraftPolicyError("generator returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict):
            raise FlagDraftPolicyError("generator returned invalid draft")
        if old is not None:
            payload["draft"] = {
                **old,
                **{k: v for k, v in payload["draft"].items() if v is not None},
            }
        clean, leaked = _mask_tree(payload["draft"], self._masker)
        draft = _normalize(clean)
        checks = _verify(
            draft,
            target_id=request.target_id,
            entries=self._entries,
            modus_operandi=self._modus,
            leaked=leaked,
        )
        provenance = _provenance(
            payload.get("field_provenance"), source, message.message_id
        )
        now, package_id, item_id = (
            self._clock.now(),
            str(self._ids.new_id()),
            str(self._ids.new_id()),
        )
        item = {
            "item_id": item_id,
            "item_type": "library_flag",
            "operation": request.operation,
            "target_ref": request.target_id,
            "base_version": current.updated_at.isoformat() if current else None,
            "draft": draft,
            "diff": _diff(old, draft),
            "field_provenance": provenance,
            "source_message_id": message.message_id,
            "verification_status": "PASS"
            if all(c[1] == "PASS" for c in checks)
            else "FAIL",
            "approval_status": "PENDING",
            "questions": _questions(payload.get("questions"), self._masker),
        }
        content = {
            "items": [item],
            "prompt_ref": {
                "name": prompt.name,
                "version": prompt.version,
                "hash": prompt.content_hash,
            },
        }
        package = self._packages.create(
            AgentPackage(
                package_id=package_id,
                session_id=request.session_id,
                iteration_number=1,
                status="SEALED",
                content=content,
                content_hash=_hash(content),
                created_at=now,
                sealed_at=now,
            )
        )
        saved = tuple(
            self._verifications.create(
                AgentVerification(
                    verification_id=str(self._ids.new_id()),
                    subject_id=package_id,
                    verifier=name,
                    status=status,
                    safe_metrics={"check": name},
                    error_code=error,
                    created_at=now,
                )
            )
            for name, status, error in checks
        )
        return FlagDraftResult(package, saved)


@dataclass(frozen=True)
class ConfirmFlagDraftInput:
    session_id: str
    owner_id: str
    role: str
    package_id: str
    item_id: str


class ConfirmFlagDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        confirmations: AgentConfirmationRepository,
        entries: FlagLibraryRepository,
        modus_operandi: ModusOperandiLibraryRepository,
        create_entry: Any,
        update_entry: Any,
        synchronize_new_asset: Callable[[FlagType, str], None],
        audit: AuditPort,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions, self._packages, self._verifications = (
            sessions,
            packages,
            verifications,
        )
        self._confirmations, self._entries, self._modus = (
            confirmations,
            entries,
            modus_operandi,
        )
        self._create, self._update, self._sync = (
            create_entry,
            update_entry,
            synchronize_new_asset,
        )
        self._audit, self._clock, self._ids = audit, clock, ids

    def execute(self, request: ConfirmFlagDraftInput) -> dict[str, str]:
        session, package = (
            self._sessions.get(request.session_id),
            self._packages.get(request.package_id),
        )
        if (
            session is None
            or session.owner_id != request.owner_id
            or package is None
            or package.session_id != request.session_id
        ):
            raise FlagDraftNotFoundError("draft not found")
        item = next(
            (
                r
                for r in package.content.get("items", [])
                if isinstance(r, dict) and r.get("item_id") == request.item_id
            ),
            None,
        )
        if item is None:
            raise FlagDraftNotFoundError("draft item not found")
        checks = self._verifications.list_for_subject(package.package_id)
        if (
            item.get("item_type") != "library_flag"
            or item.get("verification_status") != "PASS"
            or not checks
            or any(c.status != "PASS" for c in checks)
        ):
            raise FlagDraftPolicyError("draft has blocking verifications")
        draft, operation, target = (
            item.get("draft"),
            item.get("operation"),
            item.get("target_ref"),
        )
        if not isinstance(draft, dict) or operation not in {"create", "update"}:
            raise FlagDraftPolicyError("invalid draft")
        name, description = draft.get("name"), draft.get("description")
        if not isinstance(name, str) or not isinstance(description, str):
            raise FlagDraftPolicyError("invalid flag metadata")
        raw_flag_type = draft.get("flag_type")
        if not isinstance(raw_flag_type, str):
            raise FlagDraftPolicyError("invalid flag type")
        try:
            flag_type = FlagType(raw_flag_type)
        except (TypeError, ValueError) as error:
            raise FlagDraftPolicyError("invalid flag type") from error
        variables, links = (
            draft.get("evolved_variables"),
            draft.get("modus_operandi_library_ids"),
        )
        if (
            not isinstance(variables, list)
            or not all(isinstance(v, str) for v in variables)
            or not isinstance(links, list)
            or not all(isinstance(v, str) for v in links)
        ):
            raise FlagDraftPolicyError("invalid flag collections")
        current = self._entries.get(target) if isinstance(target, str) else None
        if operation == "update":
            if current is None or current.updated_at.isoformat() != item.get(
                "base_version"
            ):
                raise FlagDraftConflictError("base flag changed")
            if links != current.modus_operandi_library_ids:
                raise FlagDraftConflictError("flag modus-operandi links are immutable")
        _assert_references(links, self._modus)
        if _has_duplicate(self._entries, name, flag_type, target):
            raise FlagDraftConflictError("flag already exists")
        now, confirmation_id = self._clock.now(), str(self._ids.new_id())
        self._confirmations.create(
            AgentConfirmation(
                confirmation_id=confirmation_id,
                session_id=request.session_id,
                package_id=package.package_id,
                item_id=request.item_id,
                action=operation,
                content_hash=_hash(item),
                confirmed_by=request.owner_id,
                confirmed_at=now,
                role=request.role,
                base_version=item.get("base_version"),
                verification_states={c.verifier: c.status for c in checks},
                source_message_id=item.get("source_message_id"),
            )
        )
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=request.owner_id,
                worker_name=None,
                action="agent.flag.confirmed",
                entity_type="library_flag",
                entity_id=target,
                correlation_id=package.package_id,
                parent_id=request.item_id,
                occurred_at=now,
                outcome="approved",
            )
        )
        if operation == "create":
            applied = self._create.execute(
                flag_type, name, description, variables, links
            )
            self._sync(applied.flag_type, applied.id)
        else:
            try:
                applied = self._update.execute(
                    target,
                    flag_type=flag_type,
                    name=name,
                    description=description,
                    evolved_variables=variables,
                    modus_operandi_library_ids=links,
                    expected_updated_at=current.updated_at if current else None,
                )
            except FlagLibraryRevisionConflict as error:
                raise FlagDraftConflictError("base flag changed") from error
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=request.owner_id,
                worker_name=None,
                action="agent.flag.applied",
                entity_type="library_flag",
                entity_id=applied.id,
                correlation_id=package.package_id,
                parent_id=request.item_id,
                occurred_at=now,
                outcome="success",
            )
        )
        return {
            "confirmation_id": confirmation_id,
            "package_id": package.package_id,
            "item_id": request.item_id,
            "entity_id": applied.id,
        }


def _entity(entry: Any) -> dict[str, Any]:
    return {
        "flag_type": entry.flag_type.value,
        "name": entry.name,
        "description": entry.description,
        "evolved_variables": list(entry.evolved_variables),
        "modus_operandi_library_ids": list(entry.modus_operandi_library_ids),
    }


def _normalize(value: dict[str, Any]) -> dict[str, Any]:
    raw_flag_type = value.get("flag_type")
    try:
        flag_type = (
            FlagType(raw_flag_type).value if isinstance(raw_flag_type, str) else None
        )
    except (TypeError, ValueError):
        flag_type = None
    return {
        "flag_type": flag_type,
        "name": value.get("name", "").strip()
        if isinstance(value.get("name"), str)
        else "",
        "description": value.get("description", "").strip()
        if isinstance(value.get("description"), str)
        else "",
        "evolved_variables": [
            v.strip()
            for v in value.get("evolved_variables", [])
            if isinstance(v, str) and v.strip()
        ]
        if isinstance(value.get("evolved_variables", []), list)
        else [],
        "modus_operandi_library_ids": list(
            dict.fromkeys(value.get("modus_operandi_library_ids", []))
        )
        if isinstance(value.get("modus_operandi_library_ids", []), list)
        and all(isinstance(v, str) for v in value.get("modus_operandi_library_ids", []))
        else [],
    }


def _verify(
    draft: dict[str, Any],
    *,
    target_id: str | None,
    entries: FlagLibraryRepository,
    modus_operandi: ModusOperandiLibraryRepository,
    leaked: int,
) -> list[tuple[str, str, str | None]]:
    name, description, variables, links = (
        draft.get(k)
        for k in (
            "name",
            "description",
            "evolved_variables",
            "modus_operandi_library_ids",
        )
    )
    raw_flag_type = draft.get("flag_type")
    try:
        flag_type = FlagType(raw_flag_type) if isinstance(raw_flag_type, str) else None
    except (TypeError, ValueError):
        flag_type = None
    schema = (
        isinstance(name, str)
        and 1 <= len(name.strip()) <= 200
        and isinstance(description, str)
        and len(description) <= 2000
        and flag_type is not None
        and isinstance(variables, list)
        and all(isinstance(v, str) and v.strip() for v in variables)
        and isinstance(links, list)
        and all(isinstance(v, str) and v for v in links)
        and len(set(links)) == len(links)
    )
    refs = False
    if isinstance(links, list) and all(isinstance(v, str) for v in links):
        refs = all(
            (entry := modus_operandi.get(link)) is not None and entry.active
            for link in links
        )
        if target_id:
            current = entries.get(target_id)
            refs = (
                refs
                and current is not None
                and links == current.modus_operandi_library_ids
            )
    duplicate = (
        isinstance(name, str)
        and flag_type is not None
        and _has_duplicate(entries, name, flag_type, target_id)
    )
    return [
        (
            "schema",
            "PASS" if schema else "FAIL",
            None if schema else "DRAFT_SCHEMA_INVALID",
        ),
        (
            "parent_references",
            "PASS" if refs else "FAIL",
            None if refs else "FLAG_REFERENCE_INVALID",
        ),
        (
            "duplicates",
            "FAIL" if duplicate else "PASS",
            "DUPLICATE_FLAG" if duplicate else None,
        ),
        (
            "leakage",
            "FAIL" if leaked else "PASS",
            "PERSONAL_DATA_REDACTED" if leaked else None,
        ),
    ]


def _assert_references(
    links: list[str], modus_operandi: ModusOperandiLibraryRepository
) -> None:
    if not all(
        (entry := modus_operandi.get(link)) is not None and entry.active
        for link in links
    ):
        raise FlagDraftConflictError("flag references changed")


def _has_duplicate(
    entries: FlagLibraryRepository,
    name: str,
    flag_type: FlagType,
    target_id: str | None,
) -> bool:
    return any(
        e.id != target_id and e.flag_type == flag_type and _norm(e.name) == _norm(name)
        for e in entries.list()
    )


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _diff(
    old: dict[str, Any] | None, draft: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    return {
        field: {"before": old.get(field) if old else None, "after": draft[field]}
        for field in FIELDS
        if old is None or old.get(field) != draft[field]
    }


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _strip_fence(value: str) -> str:
    result = value.strip()
    if result.startswith("```") and result.endswith("```"):
        result = result[3:-3].strip()
        if result.startswith("json"):
            result = result[4:].strip()
    return result


def _mask_tree(value: Any, masker: PersonalDataMasker) -> tuple[Any, int]:
    if isinstance(value, str):
        masked = masker.mask(value)
        return masked.text, sum(masked.counts.values())
    if isinstance(value, list):
        list_rows = [_mask_tree(v, masker) for v in value]
        return [r[0] for r in list_rows], sum(r[1] for r in list_rows)
    if isinstance(value, dict):
        map_rows = {k: _mask_tree(v, masker) for k, v in value.items()}
        return {k: v[0] for k, v in map_rows.items()}, sum(
            v[1] for v in map_rows.values()
        )
    return value, 0


def _provenance(
    raw: Any, source: str, message_id: str
) -> dict[str, dict[str, str | None]]:
    result = {}
    for field in FIELDS:
        value = raw.get(field, {}) if isinstance(raw, dict) else {}
        quote = value.get("source_quote") if isinstance(value, dict) else None
        valid = isinstance(quote, str) and bool(quote) and quote in source
        result[field] = {
            "source": "user_input" if valid else "inferred",
            "source_message_id": message_id if valid else None,
            "source_quote": quote if valid else None,
        }
    return result


def _questions(raw: Any, masker: PersonalDataMasker) -> list[str]:
    return (
        [masker.mask(v.strip()).text for v in raw if isinstance(v, str) and v.strip()][
            :10
        ]
        if isinstance(raw, list)
        else []
    )
