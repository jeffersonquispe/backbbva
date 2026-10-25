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
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryRepository,
    SimilarCaseLibraryRevisionConflict,
)
from src.application.ports.taxonomy_library_port import TaxonomyLibraryRepository

PROMPT_NAME = "agent.similar_case.generate"
OPEN_STATUSES = {AgentSessionStatus.DRAFT, AgentSessionStatus.ACTIVE, AgentSessionStatus.PAUSED, AgentSessionStatus.WAITING_USER, AgentSessionStatus.WAITING_APPROVAL}
FIELDS = ("text", "modus_operandi_library_id", "taxonomy_library_id")


class SimilarCaseDraftNotFoundError(Exception):
    pass


class SimilarCaseDraftPolicyError(Exception):
    pass


class SimilarCaseDraftConflictError(Exception):
    pass


@dataclass(frozen=True)
class GenerateSimilarCaseDraftInput:
    session_id: str
    owner_id: str
    client_message_id: str
    operation: str
    target_id: str | None = None


@dataclass(frozen=True)
class SimilarCaseDraftResult:
    package: AgentPackage
    verifications: tuple[AgentVerification, ...]


class GenerateSimilarCaseDraftUseCase:
    def __init__(self, *, sessions: AgentSessionRepository, messages: AgentMessageRepository, prompts: AgentPromptRepository, packages: AgentPackageRepository, verifications: AgentVerificationRepository, entries: SimilarCaseLibraryRepository, modus_operandi: ModusOperandiLibraryRepository, taxonomies: TaxonomyLibraryRepository, settings: AssistantOptimizerSettingsPort, generator: AgentStructuredGenerator, masker: PersonalDataMasker, clock: Clock, ids: IdGenerator) -> None:
        self._sessions, self._messages, self._prompts = sessions, messages, prompts
        self._packages, self._verifications, self._entries = packages, verifications, entries
        self._modus, self._taxonomies, self._settings = modus_operandi, taxonomies, settings
        self._generator, self._masker, self._clock, self._ids = generator, masker, clock, ids

    def execute(self, request: GenerateSimilarCaseDraftInput) -> SimilarCaseDraftResult:
        session = self._sessions.get(request.session_id)
        if session is None or session.owner_id != request.owner_id or session.mode != "assistant":
            raise SimilarCaseDraftNotFoundError("assistant session not found")
        settings = self._settings.get()
        if session.status not in OPEN_STATUSES or not settings.assistant_enabled:
            raise SimilarCaseDraftPolicyError("assistant session is closed or disabled")
        if request.operation not in {"create", "update"} or ((request.operation == "update") != bool(request.target_id)):
            raise SimilarCaseDraftPolicyError("invalid operation or target")
        message = self._messages.get_by_client_message_id(request.session_id, request.client_message_id)
        if message is None or message.role != "user" or message.author_id != request.owner_id:
            raise SimilarCaseDraftNotFoundError("source message not found")
        source = self._masker.mask(message.content).text
        if len(source) > settings.assistant_max_message_chars:
            raise SimilarCaseDraftPolicyError("source message exceeds configured limit")
        current = self._entries.get(request.target_id) if request.target_id else None
        if request.target_id and current is None:
            raise SimilarCaseDraftNotFoundError("similar case not found")
        active = self._prompts.get_active(PROMPT_NAME)
        if active is None:
            raise SimilarCaseDraftPolicyError("similar case prompt unavailable")
        pinned = session.prompt_versions.get(PROMPT_NAME, {}).get("version")
        prompt = self._prompts.get_version(PROMPT_NAME, int(pinned) if pinned is not None else active.version)
        if prompt is None:
            raise SimilarCaseDraftPolicyError("similar case prompt version unavailable")
        old = _entity(current) if current else None
        context = {
            "operation": request.operation,
            "current_entry": old,
            "modus_operandi_entries": [
                {"id": entry.id, "title": entry.title, "taxonomy_library_id": entry.taxonomy_library_id}
                for entry in self._modus.list()[:50]
                if entry.active
            ],
            "taxonomies": [
                {"id": entry.id, "code": entry.code, "name": entry.name}
                for entry in self._taxonomies.list()[:50]
                if entry.active
            ],
        }
        raw = self._generator.generate(AgentStructuredGenerationInput(
            system_prompt=prompt.content,
            persisted_context=json.dumps(context, ensure_ascii=False),
            masked_user_message=source,
        ))
        try:
            payload = json.loads(_strip_fence(raw))
        except (ValueError, TypeError) as error:
            raise SimilarCaseDraftPolicyError("generator returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict):
            raise SimilarCaseDraftPolicyError("generator returned invalid draft")
        if old is not None:
            payload["draft"] = {**old, **{key: value for key, value in payload["draft"].items() if value is not None}}
        clean, leaked = _mask_tree(payload["draft"], self._masker)
        draft = _normalize(clean)
        provenance = _provenance(payload.get("field_provenance"), source, message.message_id)
        questions = _questions(payload.get("questions"), self._masker)
        checks = self._verify(draft, target_id=request.target_id, leaked=leaked)
        now = self._clock.now()
        package_id, item_id = str(self._ids.new_id()), str(self._ids.new_id())
        item = {"item_id": item_id, "item_type": "library_similar_case", "operation": request.operation,
                "target_ref": request.target_id, "base_version": current.updated_at.isoformat() if current else None,
                "draft": draft, "diff": _diff(old, draft), "field_provenance": provenance,
                "source_message_id": message.message_id,
                "verification_status": "PASS" if all(check[1] == "PASS" for check in checks) else "FAIL",
                "approval_status": "PENDING", "questions": questions}
        content = {"items": [item], "prompt_ref": {"name": prompt.name, "version": prompt.version, "hash": prompt.content_hash}}
        digest = _hash(content)
        package = self._packages.create(AgentPackage(package_id=package_id, session_id=request.session_id,
            iteration_number=1, status="SEALED", content=content, content_hash=digest, created_at=now, sealed_at=now))
        saved = tuple(self._verifications.create(AgentVerification(
            verification_id=str(self._ids.new_id()), subject_id=package_id, verifier=name, status=status,
            safe_metrics={"check": name}, error_code=error, created_at=now)) for name, status, error in checks)
        return SimilarCaseDraftResult(package, saved)

    def _verify(self, draft: dict[str, Any], *, target_id: str | None, leaked: int) -> list[tuple[str, str, str | None]]:
        text = draft.get("text")
        schema_ok = isinstance(text, str) and 1 <= len(text.strip()) <= 5_000
        taxonomy_id, modus_id = draft.get("taxonomy_library_id"), draft.get("modus_operandi_library_id")
        taxonomy = self._taxonomies.get(taxonomy_id) if isinstance(taxonomy_id, str) else None
        modus = self._modus.get(modus_id) if isinstance(modus_id, str) else None
        refs_ok = bool(taxonomy and taxonomy.active and modus and modus.active and modus.taxonomy_library_id == taxonomy_id)
        if target_id:
            current = self._entries.get(target_id)
            refs_ok = bool(refs_ok and current
                and current.modus_operandi_library_id == modus_id
                and current.taxonomy_library_id == taxonomy_id)
        duplicate = False
        if schema_ok and isinstance(modus_id, str) and isinstance(text, str):
            duplicate = any(entry.id != target_id and entry.modus_operandi_library_id == modus_id
                and _normalize_text(entry.text) == _normalize_text(text) for entry in self._entries.list())
        return [("schema", "PASS" if schema_ok else "FAIL", None if schema_ok else "DRAFT_SCHEMA_INVALID"),
                ("parent_references", "PASS" if refs_ok else "FAIL", None if refs_ok else "PARENT_REFERENCE_INVALID"),
                ("duplicates", "FAIL" if duplicate else "PASS", "DUPLICATE_SIMILAR_CASE" if duplicate else None),
                ("leakage", "FAIL" if leaked else "PASS", "PERSONAL_DATA_REDACTED" if leaked else None)]


@dataclass(frozen=True)
class ConfirmSimilarCaseDraftInput:
    session_id: str
    owner_id: str
    role: str
    package_id: str
    item_id: str


class ConfirmSimilarCaseDraftUseCase:
    def __init__(self, *, sessions: AgentSessionRepository, packages: AgentPackageRepository, verifications: AgentVerificationRepository, confirmations: AgentConfirmationRepository, entries: SimilarCaseLibraryRepository, modus_operandi: ModusOperandiLibraryRepository, taxonomies: TaxonomyLibraryRepository, create_entry: Any, update_entry: Any, audit: AuditPort, clock: Clock, ids: IdGenerator) -> None:
        self._sessions, self._packages, self._verifications = sessions, packages, verifications
        self._confirmations, self._entries = confirmations, entries
        self._modus, self._taxonomies = modus_operandi, taxonomies
        self._create, self._update, self._audit, self._clock, self._ids = create_entry, update_entry, audit, clock, ids

    def execute(self, request: ConfirmSimilarCaseDraftInput) -> dict[str, str]:
        session, package = self._sessions.get(request.session_id), self._packages.get(request.package_id)
        if session is None or session.owner_id != request.owner_id or package is None or package.session_id != request.session_id:
            raise SimilarCaseDraftNotFoundError("draft not found")
        item = next((row for row in package.content.get("items", []) if isinstance(row, dict) and row.get("item_id") == request.item_id), None)
        if item is None:
            raise SimilarCaseDraftNotFoundError("draft item not found")
        checks = self._verifications.list_for_subject(package.package_id)
        if item.get("item_type") != "library_similar_case" or item.get("verification_status") != "PASS" or not checks or any(check.status != "PASS" for check in checks):
            raise SimilarCaseDraftPolicyError("draft has blocking verifications")
        draft, operation, target = item.get("draft"), item.get("operation"), item.get("target_ref")
        if not isinstance(draft, dict) or operation not in {"create", "update"}:
            raise SimilarCaseDraftPolicyError("invalid draft")
        taxonomy_id, modus_id = draft.get("taxonomy_library_id"), draft.get("modus_operandi_library_id")
        taxonomy = self._taxonomies.get(taxonomy_id) if isinstance(taxonomy_id, str) else None
        modus = self._modus.get(modus_id) if isinstance(modus_id, str) else None
        if taxonomy is None or not taxonomy.active or modus is None or not modus.active or modus.taxonomy_library_id != taxonomy_id:
            raise SimilarCaseDraftConflictError("parent references changed")
        current = self._entries.get(target) if isinstance(target, str) else None
        if operation == "update" and current is not None and (
            current.modus_operandi_library_id != modus_id or current.taxonomy_library_id != taxonomy_id
        ):
            raise SimilarCaseDraftConflictError("similar case parent references are immutable")
        if operation == "update":
            if current is None or current.updated_at.isoformat() != item.get("base_version"):
                raise SimilarCaseDraftConflictError("base similar case changed")
        draft_text = draft.get("text")
        if not isinstance(draft_text, str) or not draft_text.strip():
            raise SimilarCaseDraftPolicyError("draft text is invalid")
        if any(entry.id != target and entry.modus_operandi_library_id == modus_id and _normalize_text(entry.text) == _normalize_text(draft_text) for entry in self._entries.list()):
            raise SimilarCaseDraftConflictError("similar case already exists")
        now, confirmation_id = self._clock.now(), str(self._ids.new_id())
        self._confirmations.create(AgentConfirmation(confirmation_id=confirmation_id, session_id=request.session_id,
            package_id=package.package_id, item_id=request.item_id, action=operation, content_hash=_hash(item),
            confirmed_by=request.owner_id, confirmed_at=now, role=request.role, base_version=item.get("base_version"),
            verification_states={check.verifier: check.status for check in checks}, source_message_id=item.get("source_message_id")))
        self._audit.write(AuditEntry(actor_type="user", actor_id=request.owner_id, worker_name=None,
            action="agent.similar_case.confirmed", entity_type="library_similar_case", entity_id=target,
            correlation_id=package.package_id, parent_id=request.item_id, occurred_at=now, outcome="approved"))
        if operation == "create":
            applied = self._create.execute(draft_text, modus_id, taxonomy_id)
        else:
            try:
                if current is None:
                    raise SimilarCaseDraftConflictError("base similar case changed")
                applied = self._update.execute(target, text=draft_text, expected_updated_at=current.updated_at)
            except SimilarCaseLibraryRevisionConflict as error:
                raise SimilarCaseDraftConflictError("base similar case changed") from error
        self._audit.write(AuditEntry(actor_type="user", actor_id=request.owner_id, worker_name=None,
            action="agent.similar_case.applied", entity_type="library_similar_case", entity_id=applied.id,
            correlation_id=package.package_id, parent_id=request.item_id, occurred_at=now, outcome="success"))
        return {"confirmation_id": confirmation_id, "package_id": package.package_id, "item_id": request.item_id, "entity_id": applied.id}


def _entity(entry: Any) -> dict[str, Any]:
    return {field: getattr(entry, field) for field in FIELDS}


def _normalize(value: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for field in FIELDS:
        item = value.get(field)
        result[field] = item.strip() if isinstance(item, str) else None
    return result


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _diff(old: dict[str, Any] | None, draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field: {"before": old.get(field) if old else None, "after": draft[field]} for field in FIELDS if old is None or old.get(field) != draft[field]}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _strip_fence(value: str) -> str:
    result = value.strip()
    if result.startswith("```") and result.endswith("```"):
        result = result[3:-3].strip()
        if result.startswith("json"):
            result = result[4:].strip()
    return result


def _provenance(raw: Any, source: str, message_id: str) -> dict[str, dict[str, str | None]]:
    out = {}
    for field in FIELDS:
        item = raw.get(field, {}) if isinstance(raw, dict) else {}
        quote = item.get("source_quote") if isinstance(item, dict) else None
        is_source = isinstance(quote, str) and bool(quote) and quote in source
        out[field] = {"source": "user_input" if is_source else "inferred",
            "source_message_id": message_id if is_source else None, "source_quote": quote if is_source else None}
    return out


def _mask_tree(value: Any, masker: PersonalDataMasker) -> tuple[Any, int]:
    if isinstance(value, str):
        result = masker.mask(value)
        return result.text, int(result.text != value)
    if isinstance(value, list):
        list_pairs = [_mask_tree(item, masker) for item in value]
        return [item for item, _ in list_pairs], sum(count for _, count in list_pairs)
    if isinstance(value, dict):
        dict_pairs = {key: _mask_tree(item, masker) for key, item in value.items()}
        return {key: item for key, (item, _) in dict_pairs.items()}, sum(count for _, count in dict_pairs.values())
    return value, 0


def _questions(value: Any, masker: PersonalDataMasker) -> list[str]:
    return [masker.mask(item).text for item in value[:10] if isinstance(item, str)] if isinstance(value, list) else []
