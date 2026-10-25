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
from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryRepository,
    TaxonomyLibraryRevisionConflict,
)

PROMPT_NAME = "agent.taxonomy.generate"
OPEN_STATUSES = {AgentSessionStatus.DRAFT, AgentSessionStatus.ACTIVE, AgentSessionStatus.PAUSED, AgentSessionStatus.WAITING_USER, AgentSessionStatus.WAITING_APPROVAL}
FIELDS = ("code", "name", "description", "variables", "examples")


class TaxonomyDraftNotFoundError(Exception):
    pass


class TaxonomyDraftPolicyError(Exception):
    pass


class TaxonomyDraftConflictError(Exception):
    pass


@dataclass(frozen=True)
class GenerateTaxonomyDraftInput:
    session_id: str
    owner_id: str
    client_message_id: str
    operation: str
    target_id: str | None = None


class GenerateTaxonomyDraftUseCase:
    def __init__(self, *, sessions: AgentSessionRepository, messages: AgentMessageRepository, prompts: AgentPromptRepository, packages: AgentPackageRepository, verifications: AgentVerificationRepository, entries: TaxonomyLibraryRepository, settings: AssistantOptimizerSettingsPort, generator: AgentStructuredGenerator, masker: PersonalDataMasker, clock: Clock, ids: IdGenerator) -> None:
        self._sessions, self._messages, self._prompts = sessions, messages, prompts
        self._packages, self._verifications, self._entries = packages, verifications, entries
        self._settings, self._generator, self._masker = settings, generator, masker
        self._clock, self._ids = clock, ids

    def execute(self, request: GenerateTaxonomyDraftInput) -> tuple[AgentPackage, tuple[AgentVerification, ...]]:
        session = self._sessions.get(request.session_id)
        if session is None or session.owner_id != request.owner_id or session.mode != "assistant":
            raise TaxonomyDraftNotFoundError("assistant session not found")
        if session.status not in OPEN_STATUSES or not self._settings.get().assistant_enabled:
            raise TaxonomyDraftPolicyError("assistant session is closed or disabled")
        if request.operation not in {"create", "update"} or ((request.operation == "update") != bool(request.target_id)):
            raise TaxonomyDraftPolicyError("invalid operation or target")
        message = self._messages.get_by_client_message_id(request.session_id, request.client_message_id)
        if message is None or message.role != "user" or message.author_id != request.owner_id:
            raise TaxonomyDraftNotFoundError("source message not found")
        masked_source = self._masker.mask(message.content).text
        if len(masked_source) > self._settings.get().assistant_max_message_chars:
            raise TaxonomyDraftPolicyError("source message exceeds configured limit")
        current = self._entries.get(request.target_id) if request.target_id else None
        if request.target_id and current is None:
            raise TaxonomyDraftNotFoundError("taxonomy not found")
        active = self._prompts.get_active(PROMPT_NAME)
        if active is None:
            raise TaxonomyDraftPolicyError("taxonomy prompt unavailable")
        version = int(session.prompt_versions.get(PROMPT_NAME, {}).get("version", active.version))
        prompt = self._prompts.get_version(PROMPT_NAME, version)
        if prompt is None:
            raise TaxonomyDraftPolicyError("taxonomy prompt version unavailable")
        old = _entity(current) if current else None
        catalog = [
            {"code": entry.code, "name": entry.name}
            for entry in self._entries.list()[:50]
            if entry.id != request.target_id
        ]
        raw = self._generator.generate(AgentStructuredGenerationInput(
            system_prompt=prompt.content,
            persisted_context=json.dumps({
                "operation": request.operation,
                "current_entry": old,
                "existing_taxonomies": catalog,
            }, ensure_ascii=False),
            masked_user_message=masked_source,
        ))
        try:
            payload = json.loads(_strip_fence(raw))
        except (ValueError, TypeError) as error:
            raise TaxonomyDraftPolicyError("generator returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict):
            raise TaxonomyDraftPolicyError("generator returned invalid draft")
        if old is not None:
            payload["draft"] = {**old, **{key: value for key, value in payload["draft"].items() if value is not None}}
        clean, leaked = _mask_tree(payload["draft"], self._masker)
        draft = _normalize(clean)
        provenance = _provenance(payload.get("field_provenance"), masked_source, message.message_id)
        checks = _verify(draft, target_id=request.target_id, entries=self._entries, leaked=leaked)
        now = self._clock.now()
        item_id, package_id = str(self._ids.new_id()), str(self._ids.new_id())
        item = {"item_id": item_id, "item_type": "library_taxonomy", "operation": request.operation,
                "target_ref": request.target_id, "base_version": current.updated_at.isoformat() if current else None,
                "draft": draft, "diff": _diff(old, draft), "field_provenance": provenance,
                "source_message_id": message.message_id,
                "verification_status": "PASS" if all(c[1] == "PASS" for c in checks) else "FAIL",
                "approval_status": "PENDING", "questions": _questions(payload.get("questions"), self._masker)}
        content = {"items": [item], "prompt_ref": {"name": prompt.name, "version": prompt.version, "hash": prompt.content_hash}}
        package = self._packages.create(AgentPackage(package_id=package_id, session_id=request.session_id,
            iteration_number=1, status="SEALED", content=content,
            content_hash=hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
            created_at=now, sealed_at=now))
        saved = tuple(self._verifications.create(AgentVerification(verification_id=str(self._ids.new_id()),
            subject_id=package_id, verifier=name, status=status, safe_metrics={"check": name}, error_code=error, created_at=now))
            for name, status, error in checks)
        return package, saved


@dataclass(frozen=True)
class ConfirmTaxonomyDraftInput:
    session_id: str
    owner_id: str
    role: str
    package_id: str
    item_id: str


class ConfirmTaxonomyDraftUseCase:
    def __init__(self, *, sessions: AgentSessionRepository, packages: AgentPackageRepository, verifications: AgentVerificationRepository, confirmations: AgentConfirmationRepository, entries: TaxonomyLibraryRepository, create_entry: Any, update_entry: Any, audit: AuditPort, clock: Clock, ids: IdGenerator) -> None:
        self._sessions, self._packages, self._verifications = sessions, packages, verifications
        self._confirmations, self._entries = confirmations, entries
        self._create, self._update, self._audit, self._clock, self._ids = create_entry, update_entry, audit, clock, ids

    def execute(self, request: ConfirmTaxonomyDraftInput) -> dict[str, str]:
        session = self._sessions.get(request.session_id)
        package = self._packages.get(request.package_id)
        if session is None or session.owner_id != request.owner_id or package is None or package.session_id != request.session_id:
            raise TaxonomyDraftNotFoundError("draft not found")
        item = next((it for it in package.content.get("items", []) if isinstance(it, dict) and it.get("item_id") == request.item_id), None)
        checks = self._verifications.list_for_subject(request.package_id)
        if item is None:
            raise TaxonomyDraftNotFoundError("draft item not found")
        if item.get("item_type") != "library_taxonomy" or item.get("verification_status") != "PASS" or not checks or any(c.status != "PASS" for c in checks):
            raise TaxonomyDraftPolicyError("draft has blocking verifications")
        draft, operation, target = item.get("draft"), item.get("operation"), item.get("target_ref")
        if not isinstance(draft, dict) or operation not in {"create", "update"}:
            raise TaxonomyDraftPolicyError("invalid draft")
        current = self._entries.get(target) if isinstance(target, str) else None
        if operation == "update":
            if current is None or current.updated_at.isoformat() != item.get("base_version"):
                raise TaxonomyDraftConflictError("base taxonomy changed")
        elif _duplicate(draft, self._entries.list()):
            raise TaxonomyDraftConflictError("taxonomy already exists")
        now = self._clock.now()
        confirmation_id = str(self._ids.new_id())
        content_hash = hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self._confirmations.create(AgentConfirmation(confirmation_id=confirmation_id, session_id=request.session_id,
            package_id=request.package_id, item_id=request.item_id, action=operation, content_hash=content_hash,
            confirmed_by=request.owner_id, confirmed_at=now, role=request.role,
            base_version=item.get("base_version"), verification_states={c.verifier: c.status for c in checks},
            source_message_id=item.get("source_message_id")))
        self._audit.write(AuditEntry(actor_type="user", actor_id=request.owner_id, worker_name=None,
            action="agent.taxonomy.confirmed", entity_type="library_taxonomy", entity_id=target,
            correlation_id=request.package_id, parent_id=request.item_id, occurred_at=now, outcome="approved"))
        if operation == "create":
            result = self._create.execute(draft["code"], draft["name"], draft["description"], draft["variables"], draft["examples"])
        else:
            assert current is not None
            try:
                result = self._update.execute(target, code=draft["code"], name=draft["name"], description=draft["description"], variables=draft["variables"], examples=draft["examples"], expected_updated_at=current.updated_at)
            except TaxonomyLibraryRevisionConflict as error:
                raise TaxonomyDraftConflictError("base taxonomy changed") from error
        self._audit.write(AuditEntry(actor_type="user", actor_id=request.owner_id, worker_name=None,
            action="agent.taxonomy.applied", entity_type="library_taxonomy", entity_id=result.id,
            correlation_id=request.package_id, parent_id=request.item_id, occurred_at=now, outcome="success"))
        return {"confirmation_id": confirmation_id, "package_id": request.package_id, "item_id": request.item_id, "entity_id": result.id}


def _entity(entry: Any) -> dict[str, Any]:
    return {field: getattr(entry, field) for field in FIELDS}


def _normalize(value: dict[str, Any]) -> dict[str, Any]:
    return {field: ([str(v).strip() for v in value[field] if isinstance(v, str) and v.strip()] if field in {"variables", "examples"} and isinstance(value.get(field), list) else (str(value[field]).strip() if isinstance(value.get(field), str) else None)) for field in FIELDS}


def _verify(draft: dict[str, Any], *, target_id: str | None, entries: TaxonomyLibraryRepository, leaked: int) -> list[tuple[str, str, str | None]]:
    valid = all(isinstance(draft.get(k), str) and bool(draft[k]) for k in ("code", "name", "description")) and all(isinstance(draft.get(k), list) for k in ("variables", "examples"))
    duplicate = _duplicate(draft, [e for e in entries.list() if e.id != target_id])
    return [("schema", "PASS" if valid else "FAIL", None if valid else "DRAFT_SCHEMA_INVALID"),
            ("duplicates", "FAIL" if duplicate else "PASS", "DUPLICATE_TAXONOMY" if duplicate else None),
            ("leakage", "FAIL" if leaked else "PASS", "PERSONAL_DATA_REDACTED" if leaked else None)]


def _duplicate(draft: dict[str, Any], entries: list[Any]) -> bool:
    code = str(draft.get("code", "")).strip().casefold()
    name = " ".join(str(draft.get("name", "")).split()).casefold()
    return bool(code and any(e.code.casefold() == code or " ".join(e.name.split()).casefold() == name for e in entries))


def _diff(old: dict[str, Any] | None, draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field: {"before": old.get(field) if old else None, "after": draft[field]} for field in FIELDS if old is None or old.get(field) != draft[field]}


def _provenance(raw: Any, source: str, message_id: str) -> dict[str, dict[str, str | None]]:
    out = {}
    for field in FIELDS:
        value = raw.get(field, {}) if isinstance(raw, dict) else {}
        quote = value.get("source_quote") if isinstance(value, dict) else None
        kind = "user_input" if isinstance(quote, str) and quote and quote in source else "inferred"
        out[field] = {"source": kind, "source_message_id": message_id if kind == "user_input" else None, "source_quote": quote if kind == "user_input" else None}
    return out


def _mask_tree(value: Any, masker: PersonalDataMasker) -> tuple[Any, int]:
    if isinstance(value, str):
        result = masker.mask(value)
        return result.text, 1 if result.text != value else 0
    if isinstance(value, list):
        list_pairs = [_mask_tree(v, masker) for v in value]
        return [v for v, _ in list_pairs], sum(n for _, n in list_pairs)
    if isinstance(value, dict):
        dict_pairs = {k: _mask_tree(v, masker) for k, v in value.items()}
        return (
            {k: masked for k, (masked, _) in dict_pairs.items()},
            sum(count for _, count in dict_pairs.values()),
        )
    return value, 0


def _questions(value: Any, masker: PersonalDataMasker) -> list[str]:
    if not isinstance(value, list):
        return []
    return [masker.mask(q).text for q in value[:10] if isinstance(q, str)]


def _strip_fence(value: str) -> str:
    value = value.strip()
    if value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
        if value.startswith("json"):
            value = value[4:].strip()
    return value
