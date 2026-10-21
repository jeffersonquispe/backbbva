from __future__ import annotations

import hashlib
import json
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
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.application.ports.watchlist_port import (
    WatchlistRepository,
    WatchlistRevisionConflict,
    WatchlistType,
)

PROMPT_NAME = "agent.watchlist.generate"
OPEN_STATUSES = {
    AgentSessionStatus.DRAFT,
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.PAUSED,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.WAITING_APPROVAL,
}
FIELDS = ("name", "description", "list_type")


class WatchlistDraftNotFoundError(Exception):
    pass


class WatchlistDraftPolicyError(Exception):
    pass


class WatchlistDraftConflictError(Exception):
    pass


@dataclass(frozen=True)
class GenerateWatchlistDraftInput:
    session_id: str
    owner_id: str
    client_message_id: str
    operation: str
    target_id: str | None = None


@dataclass(frozen=True)
class WatchlistDraftResult:
    package: AgentPackage
    verifications: tuple[AgentVerification, ...]


class GenerateWatchlistDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        messages: AgentMessageRepository,
        prompts: AgentPromptRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        entries: WatchlistRepository,
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
        self._settings, self._generator, self._masker = settings, generator, masker
        self._clock, self._ids = clock, ids

    def execute(self, request: GenerateWatchlistDraftInput) -> WatchlistDraftResult:
        session = self._sessions.get(request.session_id)
        if (
            session is None
            or session.owner_id != request.owner_id
            or session.mode != "assistant"
        ):
            raise WatchlistDraftNotFoundError("assistant session not found")
        settings = self._settings.get()
        if session.status not in OPEN_STATUSES or not settings.assistant_enabled:
            raise WatchlistDraftPolicyError("assistant session is closed or disabled")
        if request.operation not in {"create", "update"} or (
            (request.operation == "update") != bool(request.target_id)
        ):
            raise WatchlistDraftPolicyError("invalid operation or target")
        message = self._messages.get_by_client_message_id(
            request.session_id, request.client_message_id
        )
        if (
            message is None
            or message.role != "user"
            or message.author_id != request.owner_id
        ):
            raise WatchlistDraftNotFoundError("source message not found")
        source = self._masker.mask(message.content).text
        if len(source) > settings.assistant_max_message_chars:
            raise WatchlistDraftPolicyError("source message exceeds configured limit")
        current = self._entries.get(request.target_id) if request.target_id else None
        if request.target_id and current is None:
            raise WatchlistDraftNotFoundError("watchlist not found")
        active = self._prompts.get_active(PROMPT_NAME)
        if active is None:
            raise WatchlistDraftPolicyError("watchlist prompt unavailable")
        pinned = session.prompt_versions.get(PROMPT_NAME, {}).get("version")
        prompt = self._prompts.get_version(
            PROMPT_NAME, int(pinned) if pinned is not None else active.version
        )
        if prompt is None:
            raise WatchlistDraftPolicyError("watchlist prompt version unavailable")
        old = _entity(current) if current else None
        raw = self._generator.generate(
            AgentStructuredGenerationInput(
                system_prompt=prompt.content,
                persisted_context=json.dumps(
                    {"operation": request.operation, "current_entry": old},
                    ensure_ascii=False,
                ),
                masked_user_message=source,
            )
        )
        try:
            payload = json.loads(_strip_fence(raw))
        except (ValueError, TypeError) as error:
            raise WatchlistDraftPolicyError(
                "generator returned invalid JSON"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict):
            raise WatchlistDraftPolicyError("generator returned invalid draft")
        if old is not None:
            payload["draft"] = {
                **old,
                **{k: v for k, v in payload["draft"].items() if v is not None},
            }
        clean, leaked = _mask_tree(payload["draft"], self._masker)
        draft = _normalize(clean)
        provenance = _provenance(
            payload.get("field_provenance"), source, message.message_id
        )
        checks = _verify(
            draft, target_id=request.target_id, entries=self._entries, leaked=leaked
        )
        now, package_id, item_id = (
            self._clock.now(),
            str(self._ids.new_id()),
            str(self._ids.new_id()),
        )
        item = {
            "item_id": item_id,
            "item_type": "library_watchlist",
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
        return WatchlistDraftResult(package, saved)


@dataclass(frozen=True)
class ConfirmWatchlistDraftInput:
    session_id: str
    owner_id: str
    role: str
    package_id: str
    item_id: str


class ConfirmWatchlistDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        confirmations: AgentConfirmationRepository,
        entries: WatchlistRepository,
        create_entry: Any,
        update_entry: Any,
        audit: AuditPort,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions, self._packages, self._verifications = (
            sessions,
            packages,
            verifications,
        )
        self._confirmations, self._entries = confirmations, entries
        self._create, self._update, self._audit, self._clock, self._ids = (
            create_entry,
            update_entry,
            audit,
            clock,
            ids,
        )

    def execute(self, request: ConfirmWatchlistDraftInput) -> dict[str, str]:
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
            raise WatchlistDraftNotFoundError("draft not found")
        item = next(
            (
                r
                for r in package.content.get("items", [])
                if isinstance(r, dict) and r.get("item_id") == request.item_id
            ),
            None,
        )
        if item is None:
            raise WatchlistDraftNotFoundError("draft item not found")
        checks = self._verifications.list_for_subject(package.package_id)
        if (
            item.get("item_type") != "library_watchlist"
            or item.get("verification_status") != "PASS"
            or not checks
            or any(c.status != "PASS" for c in checks)
        ):
            raise WatchlistDraftPolicyError("draft has blocking verifications")
        draft, operation, target = (
            item.get("draft"),
            item.get("operation"),
            item.get("target_ref"),
        )
        if not isinstance(draft, dict) or operation not in {"create", "update"}:
            raise WatchlistDraftPolicyError("invalid draft")
        name, description = draft.get("name"), draft.get("description")
        raw_list_type = draft.get("list_type")
        if not isinstance(raw_list_type, str):
            raise WatchlistDraftPolicyError("invalid watchlist type")
        try:
            list_type = WatchlistType(raw_list_type)
        except (ValueError, TypeError) as error:
            raise WatchlistDraftPolicyError("invalid watchlist type") from error
        if not isinstance(name, str) or not isinstance(description, str):
            raise WatchlistDraftPolicyError("invalid watchlist metadata")
        current = self._entries.get(target) if isinstance(target, str) else None
        if operation == "update" and (
            current is None
            or current.updated_at.isoformat() != item.get("base_version")
        ):
            raise WatchlistDraftConflictError("base watchlist changed")
        if operation == "update":
            if current is None:
                raise WatchlistDraftConflictError("base watchlist changed")
            if current.list_type != list_type:
                raise WatchlistDraftConflictError("watchlist type is immutable")
        if any(
            entry.id != target
            and entry.list_type == list_type
            and _norm(entry.name) == _norm(name)
            for entry in self._entries.list()
        ):
            raise WatchlistDraftConflictError("watchlist already exists")
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
                action="agent.watchlist.confirmed",
                entity_type="watchlist",
                entity_id=target,
                correlation_id=package.package_id,
                parent_id=request.item_id,
                occurred_at=now,
                outcome="approved",
            )
        )
        if operation == "create":
            applied = self._create.execute(name, description, list_type)
        else:
            try:
                applied = self._update.execute(
                    target,
                    name=name,
                    description=description,
                    expected_updated_at=current.updated_at if current else None,
                )
            except WatchlistRevisionConflict as error:
                raise WatchlistDraftConflictError("base watchlist changed") from error
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=request.owner_id,
                worker_name=None,
                action="agent.watchlist.applied",
                entity_type="watchlist",
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
        "name": entry.name,
        "description": entry.description,
        "list_type": entry.list_type.value,
    }


def _normalize(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": value.get("name", "").strip()
        if isinstance(value.get("name"), str)
        else "",
        "description": value.get("description", "").strip()
        if isinstance(value.get("description"), str)
        else "",
        "list_type": value.get("list_type")
        if isinstance(value.get("list_type"), str)
        else None,
    }


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _diff(
    old: dict[str, Any] | None, draft: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    return {
        f: {"before": old.get(f) if old else None, "after": draft[f]}
        for f in FIELDS
        if old is None or old.get(f) != draft[f]
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
        result = masker.mask(value)
        return result.text, sum(result.counts.values())
    if isinstance(value, list):
        list_rows = [_mask_tree(v, masker) for v in value]
        return [r[0] for r in list_rows], sum(r[1] for r in list_rows)
    if isinstance(value, dict):
        map_rows = {k: _mask_tree(v, masker) for k, v in value.items()}
        return {k: v[0] for k, v in map_rows.items()}, sum(v[1] for v in map_rows.values())
    return value, 0


def _provenance(
    raw: Any, source: str, message_id: str
) -> dict[str, dict[str, str | None]]:
    out = {}
    for field in FIELDS:
        item = raw.get(field, {}) if isinstance(raw, dict) else {}
        quote = item.get("source_quote") if isinstance(item, dict) else None
        valid = isinstance(quote, str) and bool(quote) and quote in source
        out[field] = {
            "source": "user_input" if valid else "inferred",
            "source_message_id": message_id if valid else None,
            "source_quote": quote if valid else None,
        }
    return out


def _questions(raw: Any, masker: PersonalDataMasker) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        masker.mask(v.strip()).text for v in raw if isinstance(v, str) and v.strip()
    ][:10]


def _verify(
    draft: dict[str, Any],
    *,
    target_id: str | None,
    entries: WatchlistRepository,
    leaked: int,
) -> list[tuple[str, str, str | None]]:
    name, description = draft.get("name"), draft.get("description")
    raw_list_type = draft.get("list_type")
    try:
        list_type = WatchlistType(raw_list_type) if isinstance(raw_list_type, str) else None
    except (ValueError, TypeError):
        list_type = None
    schema = (
        isinstance(name, str)
        and 1 <= len(name.strip()) <= 200
        and isinstance(description, str)
        and 1 <= len(description.strip()) <= 1000
        and list_type is not None
    )
    duplicate = bool(
        schema
        and list_type is not None
        and isinstance(name, str)
        and any(
            e.id != target_id
            and e.list_type == list_type
            and _norm(e.name) == _norm(name)
            for e in entries.list()
        )
    )
    return [
        (
            "schema",
            "PASS" if schema else "FAIL",
            None if schema else "DRAFT_SCHEMA_INVALID",
        ),
        (
            "duplicates",
            "FAIL" if duplicate else "PASS",
            "DUPLICATE_WATCHLIST" if duplicate else None,
        ),
        (
            "leakage",
            "FAIL" if leaked else "PASS",
            "PERSONAL_DATA_REDACTED" if leaked else None,
        ),
    ]
