from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from src.application.ports.agent_confirmation_port import (
    AgentConfirmation,
    AgentConfirmationRepository,
)
from src.application.ports.agent_message_port import AgentMessageRepository
from src.application.ports.agent_modus_operandi_draft_applier_port import (
    ModusOperandiDraftApplier,
    ModusOperandiDraftFields,
)
from src.application.ports.agent_package_port import (
    AgentPackage,
    AgentPackageRepository,
)
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagent,
    AgentSubagentInput,
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
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
    ModusOperandiLibraryRevisionConflict,
)
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.application.ports.taxonomy_library_port import TaxonomyLibraryRepository
from src.application.use_cases.modus_operandi_library.playbook_validation import (
    InvalidModusOperandiPlaybookError,
    validate_playbook,
)
from src.domain.configurations.entities import ResolutionTag, ShortageBehavior
from src.domain.fraud_knowledge.library_entities import ModusOperandiPlaybook

DRAFT_PROMPT = "agent.modus_operandi.generate"
OPEN_SESSION_STATUSES = {
    AgentSessionStatus.DRAFT,
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.PAUSED,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.WAITING_APPROVAL,
}
REQUIRED_DRAFT_FIELDS = (
    "title",
    "narrative",
    "taxonomy_library_id",
    "evolved_variables",
    "playbook",
)


class AgentDraftNotFoundError(Exception):
    pass


class AgentDraftPolicyError(Exception):
    pass


class AgentDraftConflictError(Exception):
    pass


@dataclass(frozen=True)
class GenerateModusOperandiDraftInput:
    session_id: str
    owner_id: str
    client_message_id: str
    operation: str
    target_id: str | None = None


@dataclass(frozen=True)
class ModusOperandiDraftResult:
    package: AgentPackage
    verifications: tuple[AgentVerification, ...]


class GenerateModusOperandiDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        messages: AgentMessageRepository,
        prompts: AgentPromptRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        entries: ModusOperandiLibraryRepository,
        taxonomies: TaxonomyLibraryRepository,
        settings: AssistantOptimizerSettingsPort,
        subagent: AgentSubagent,
        masker: PersonalDataMasker,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._prompts = prompts
        self._packages = packages
        self._verifications = verifications
        self._entries = entries
        self._taxonomies = taxonomies
        self._settings = settings
        self._subagent = subagent
        self._masker = masker
        self._clock = clock
        self._ids = id_generator

    def execute(self, request: GenerateModusOperandiDraftInput) -> ModusOperandiDraftResult:
        session = self._sessions.get(request.session_id)
        if (
            session is None
            or session.owner_id != request.owner_id
            or session.mode != "assistant"
        ):
            raise AgentDraftNotFoundError("assistant session not found")
        if session.status not in OPEN_SESSION_STATUSES:
            raise AgentDraftPolicyError("assistant session is closed")
        settings = self._settings.get()
        if not settings.assistant_enabled:
            raise AgentDraftPolicyError("assistant is disabled")
        if request.operation not in {"create", "update"}:
            raise AgentDraftPolicyError("unsupported draft operation")
        if (request.operation == "update") != bool(request.target_id):
            raise AgentDraftPolicyError("update requires a target entry")

        message = self._messages.get_by_client_message_id(
            request.session_id, request.client_message_id
        )
        if message is None or message.role != "user" or message.author_id != request.owner_id:
            raise AgentDraftNotFoundError("source message not found")
        source = self._masker.mask(message.content)
        if len(source.text) > settings.assistant_max_message_chars:
            raise AgentDraftPolicyError("source message exceeds configured limit")

        current = self._entries.get(request.target_id) if request.target_id else None
        if request.target_id and current is None:
            raise AgentDraftNotFoundError("modus operandi not found")
        active = self._prompts.get_active(DRAFT_PROMPT)
        if active is None:
            raise AgentDraftPolicyError("generator prompt is unavailable")
        pinned = session.prompt_versions.get(DRAFT_PROMPT, {}).get("version")
        prompt_version = int(pinned) if pinned is not None else active.version
        prompt = self._prompts.get_version(DRAFT_PROMPT, prompt_version)
        if prompt is None:
            raise AgentDraftPolicyError("generator prompt version is unavailable")

        current_data = _entry_data(current) if current else None
        generated = self._subagent.execute(
            AgentSubagentInput(
                session_id=request.session_id,
                iteration_number=1,
                scope={
                    "operation": request.operation,
                    "target_id": request.target_id,
                    "current_entry": current_data,
                    "system_prompt": prompt.content,
                },
                hypothesis=source.text,
                budget=session.budget_limits,
            )
        )
        if generated.error_code is not None:
            raise AgentDraftPolicyError("entity generator is unavailable")
        draft_data = generated.contribution.get("draft")
        if not isinstance(draft_data, dict):
            draft_data = {}
        masked_draft, leakage_count = _mask_tree(draft_data, self._masker)
        draft = _normalize_draft(masked_draft)
        provenance = _normalize_provenance(
            generated.contribution.get("field_provenance"),
            source.text,
            message.message_id,
        )
        questions = generated.contribution.get("questions", [])
        if not isinstance(questions, list):
            questions = []
        questions = [
            masked.text
            for item in questions[:10]
            if isinstance(item, str)
            for masked in [self._masker.mask(item)]
        ]

        checks = self._verify(
            draft=draft,
            target_id=request.target_id,
            leakage_count=leakage_count,
        )
        now = self._clock.now()
        package_id = str(self._ids.new_id())
        item_id = str(self._ids.new_id())
        base_version = current.updated_at.isoformat() if current else None
        diff = _diff(current_data, draft)
        item = {
            "item_id": item_id,
            "item_type": "library_modus_operandi",
            "operation": request.operation,
            "target_ref": request.target_id,
            "base_version": base_version,
            "draft": draft,
            "diff": diff,
            "field_provenance": provenance,
            "source_message_id": message.message_id,
            "verification_status": "PASS"
            if all(check.status == "PASS" for check in checks)
            else "FAIL",
            "approval_status": "PENDING",
            "questions": questions,
        }
        content = {
            "items": [item],
            "prompt_ref": {
                "name": prompt.name,
                "version": prompt.version,
                "hash": prompt.content_hash,
            },
        }
        content_hash = _hash(content)
        package = self._packages.create(
            AgentPackage(
                package_id=package_id,
                session_id=request.session_id,
                iteration_number=1,
                status="SEALED",
                content=content,
                content_hash=content_hash,
                created_at=now,
                sealed_at=now,
            )
        )
        saved_checks = tuple(
            self._verifications.create(
                AgentVerification(
                    verification_id=str(self._ids.new_id()),
                    subject_id=package_id,
                    verifier=check.verifier,
                    status=check.status,
                    safe_metrics={"check": check.verifier},
                    error_code=check.error_code,
                    created_at=now,
                )
            )
            for check in checks
        )
        return ModusOperandiDraftResult(package, saved_checks)

    def _verify(
        self, *, draft: dict[str, Any], target_id: str | None, leakage_count: int
    ) -> list[_Check]:
        checks: list[_Check] = []
        schema_valid = (
            isinstance(draft.get("title"), str)
            and 1 <= len(draft["title"]) <= 200
            and isinstance(draft.get("narrative"), str)
            and 1 <= len(draft["narrative"]) <= 2_000
            and isinstance(draft.get("taxonomy_library_id"), str)
            and bool(draft["taxonomy_library_id"])
            and isinstance(draft.get("evolved_variables"), list)
            and all(isinstance(value, str) for value in draft["evolved_variables"])
            and _playbook(draft.get("playbook")) is not None
        )
        checks.append(
            _Check(
                "schema",
                "PASS" if schema_valid else "FAIL",
                None if schema_valid else "DRAFT_SCHEMA_INVALID",
            )
        )
        taxonomy_id = draft.get("taxonomy_library_id")
        taxonomy = (
            self._taxonomies.get(taxonomy_id)
            if isinstance(taxonomy_id, str) and taxonomy_id
            else None
        )
        checks.append(
            _Check(
                "taxonomy",
                "PASS" if taxonomy is not None and taxonomy.active else "FAIL",
                None if taxonomy is not None and taxonomy.active else "TAXONOMY_INVALID",
            )
        )
        title = draft.get("title")
        duplicate = False
        if isinstance(title, str) and title.strip():
            normalized = " ".join(title.split()).casefold()
            duplicate = any(
                entry.id != target_id
                and " ".join(entry.title.split()).casefold() == normalized
                for entry in self._entries.list()
            )
        checks.append(
            _Check("duplicates", "FAIL" if duplicate else "PASS", "DUPLICATE_TITLE" if duplicate else None)
        )
        playbook = _playbook(draft.get("playbook"))
        try:
            if playbook is None:
                raise ValueError("missing playbook")
            validate_playbook(playbook)
            playbook_status, playbook_error = "PASS", None
        except (ValueError, TypeError, InvalidModusOperandiPlaybookError):
            playbook_status, playbook_error = "FAIL", "PLAYBOOK_INVALID"
        checks.append(_Check("playbook_fallbacks", playbook_status, playbook_error))
        checks.append(
            _Check(
                "leakage",
                "FAIL" if leakage_count else "PASS",
                "PERSONAL_DATA_REDACTED" if leakage_count else None,
            )
        )
        return checks


@dataclass(frozen=True)
class _Check:
    verifier: str
    status: str
    error_code: str | None


@dataclass(frozen=True)
class ConfirmModusOperandiDraftInput:
    session_id: str
    owner_id: str
    role: str
    package_id: str
    item_id: str


class ConfirmModusOperandiDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        confirmations: AgentConfirmationRepository,
        entries: ModusOperandiLibraryRepository,
        applier: ModusOperandiDraftApplier,
        audit: AuditPort,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._packages = packages
        self._verifications = verifications
        self._confirmations = confirmations
        self._entries = entries
        self._applier = applier
        self._audit = audit
        self._clock = clock
        self._ids = id_generator

    def execute(self, request: ConfirmModusOperandiDraftInput) -> dict[str, Any]:
        session = self._sessions.get(request.session_id)
        if session is None or session.owner_id != request.owner_id:
            raise AgentDraftNotFoundError("assistant session not found")
        package = self._packages.get(request.package_id)
        if package is None or package.session_id != request.session_id:
            raise AgentDraftNotFoundError("draft package not found")
        items = package.content.get("items", [])
        item = next(
            (
                candidate
                for candidate in items
                if isinstance(candidate, dict)
                and candidate.get("item_id") == request.item_id
            ),
            None,
        )
        if item is None:
            raise AgentDraftNotFoundError("draft item not found")
        checks = self._verifications.list_for_subject(package.package_id)
        if item.get("verification_status") != "PASS" or not checks or any(
            check.status != "PASS" for check in checks
        ):
            raise AgentDraftPolicyError("draft has blocking verifications")
        draft = item.get("draft")
        operation = item.get("operation")
        target_id = item.get("target_ref")
        if not isinstance(draft, dict):
            raise AgentDraftPolicyError("draft content is invalid")
        current = self._entries.get(target_id) if isinstance(target_id, str) else None
        if operation == "update":
            if not isinstance(target_id, str) or current is None:
                raise AgentDraftConflictError("base entity no longer exists")
            if current.updated_at.isoformat() != item.get("base_version"):
                raise AgentDraftConflictError("base entity changed")
        elif operation == "create":
            normalized = " ".join(str(draft.get("title", "")).split()).casefold()
            if any(
                " ".join(entry.title.split()).casefold() == normalized
                for entry in self._entries.list()
            ):
                raise AgentDraftConflictError("entity title now exists")
        else:
            raise AgentDraftPolicyError("unsupported draft operation")

        fields = _draft_fields(draft)
        if operation == "update":
            if not isinstance(target_id, str) or current is None:
                raise AgentDraftConflictError("base entity no longer exists")
        now = self._clock.now()
        content_hash = _hash(item)
        confirmation_id = str(self._ids.new_id())
        self._confirmations.create(
            AgentConfirmation(
                confirmation_id=confirmation_id,
                session_id=request.session_id,
                package_id=package.package_id,
                item_id=request.item_id,
                action=operation,
                content_hash=content_hash,
                confirmed_by=request.owner_id,
                confirmed_at=now,
                role=request.role,
                base_version=item.get("base_version"),
                verification_states={
                    check.verifier: check.status for check in checks
                },
                source_message_id=item.get("source_message_id"),
            )
        )
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=request.owner_id,
                worker_name=None,
                action="agent.modus_operandi.confirmed",
                entity_type="library_modus_operandi",
                entity_id=target_id,
                correlation_id=package.package_id,
                parent_id=request.item_id,
                occurred_at=now,
                outcome="approved",
            )
        )
        try:
            if operation == "create":
                entity_id = self._applier.create(fields)
            elif operation == "update":
                if not isinstance(target_id, str) or current is None:
                    raise AgentDraftConflictError("base entity no longer exists")
                entity_id = self._applier.update(
                    target_id,
                    fields,
                    expected_updated_at=current.updated_at,
                )
            else:
                raise AgentDraftPolicyError("unsupported draft operation")
        except ModusOperandiLibraryRevisionConflict as error:
            raise AgentDraftConflictError("base entity changed") from error
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=request.owner_id,
                worker_name=None,
                action="agent.modus_operandi.applied",
                entity_type="library_modus_operandi",
                entity_id=entity_id,
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
            "entity_id": entity_id,
        }


def _normalize_draft(value: dict[str, Any]) -> dict[str, Any]:
    draft: dict[str, Any] = {}
    for name in REQUIRED_DRAFT_FIELDS:
        item = value.get(name)
        if name == "evolved_variables":
            draft[name] = item if isinstance(item, list) else None
        elif name == "playbook":
            draft[name] = item if isinstance(item, dict) else None
        else:
            draft[name] = item.strip() if isinstance(item, str) else None
    return draft


def _normalize_provenance(value: Any, source: str, message_id: str) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for field_name in REQUIRED_DRAFT_FIELDS:
        raw = value.get(field_name, {}) if isinstance(value, dict) else {}
        kind = raw.get("source") if isinstance(raw, dict) else None
        quote = raw.get("source_quote") if isinstance(raw, dict) else None
        if kind == "user_input" and isinstance(quote, str) and quote and quote in source:
            origin = "user_input"
        elif kind == "inferred":
            origin = "inferred"
        else:
            origin = "agent_generated"
        result[field_name] = {
            "source": origin,
            "source_message_id": message_id if origin == "user_input" else None,
        }
    return result


def _mask_tree(value: Any, masker: PersonalDataMasker) -> tuple[Any, int]:
    if isinstance(value, str):
        masked = masker.mask(value)
        return masked.text, sum(masked.counts.values())
    if isinstance(value, list):
        list_results = [_mask_tree(item, masker) for item in value]
        return [item for item, _ in list_results], sum(
            count for _, count in list_results
        )
    if isinstance(value, dict):
        dict_results = {key: _mask_tree(item, masker) for key, item in value.items()}
        return {key: item for key, (item, _) in dict_results.items()}, sum(
            count for _, count in dict_results.values()
        )
    return value, 0


def _entry_data(entry) -> dict[str, Any]:
    data = asdict(entry)
    data.pop("embedding", None)
    data["created_at"] = entry.created_at.isoformat()
    data["updated_at"] = entry.updated_at.isoformat()
    return data


def _diff(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    if before is None:
        return {key: {"before": None, "after": value} for key, value in after.items()}
    return {
        key: {"before": before.get(key), "after": value}
        for key, value in after.items()
        if before.get(key) != value
    }


def _playbook(value: Any) -> ModusOperandiPlaybook | None:
    if not isinstance(value, dict):
        return None
    try:
        return ModusOperandiPlaybook(
            strategy=str(value["strategy"]),
            resolution=_shortage(value["resolution"]),
            if_no_voicebot=_shortage(value["if_no_voicebot"]),
            if_no_analyst=_shortage(value["if_no_analyst"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _shortage(value: Any) -> ShortageBehavior:
    if not isinstance(value, dict):
        raise ValueError("invalid fallback")
    raw_tag = value.get("resolution_tag")
    if raw_tag is None:
        raise ValueError("missing resolution tag")
    try:
        tag = ResolutionTag(str(raw_tag))
    except ValueError:
        tag = raw_tag
    method_id = value.get("resolution_method_id")
    if method_id is not None and not isinstance(method_id, str):
        raise ValueError("invalid resolution method id")
    return ShortageBehavior(resolution_tag=tag, resolution_method_id=method_id)


def _draft_fields(draft: dict[str, Any]) -> ModusOperandiDraftFields:
    playbook = _playbook(draft.get("playbook"))
    if playbook is None:
        raise AgentDraftPolicyError("playbook is invalid")
    title = draft.get("title")
    narrative = draft.get("narrative")
    taxonomy_id = draft.get("taxonomy_library_id")
    evolved_variables = draft.get("evolved_variables")
    if not isinstance(title, str) or not title:
        raise AgentDraftPolicyError("required draft fields are missing")
    if not isinstance(narrative, str) or not narrative:
        raise AgentDraftPolicyError("required draft fields are missing")
    if not isinstance(taxonomy_id, str) or not taxonomy_id:
        raise AgentDraftPolicyError("required draft fields are missing")
    if not isinstance(evolved_variables, list) or not all(
        isinstance(item, str) for item in evolved_variables
    ):
        raise AgentDraftPolicyError("draft variables are invalid")
    return ModusOperandiDraftFields(
        title=title,
        narrative=narrative,
        taxonomy_library_id=taxonomy_id,
        evolved_variables=evolved_variables,
        playbook=playbook,
    )


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
