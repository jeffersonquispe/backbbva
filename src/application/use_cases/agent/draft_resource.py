from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.application.ports.agent_confirmation_port import (
    AgentConfirmation,
    AgentConfirmationRepository,
)
from src.application.ports.agent_draft_resource_port import AgentDraftResourcePort
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

OPEN_STATUSES = {
    AgentSessionStatus.DRAFT,
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.PAUSED,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.WAITING_APPROVAL,
}
RESOURCE_FIELDS = {
    "channel": ("code", "name", "description"),
    "catalog_entry": ("category", "value"),
    "dataset_empty": ("name", "fields"),
}


class ResourceDraftError(Exception):
    pass


@dataclass(frozen=True)
class GenerateResourceDraftInput:
    session_id: str
    owner_id: str
    client_message_id: str
    resource: str


class GenerateResourceDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        messages: AgentMessageRepository,
        prompts: AgentPromptRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        resources: AgentDraftResourcePort,
        settings: AssistantOptimizerSettingsPort,
        generator: AgentStructuredGenerator,
        masker: PersonalDataMasker,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions, self._messages, self._prompts = sessions, messages, prompts
        self._packages, self._verifications, self._resources = (
            packages,
            verifications,
            resources,
        )
        self._settings, self._generator, self._masker = settings, generator, masker
        self._clock, self._ids = clock, ids

    def execute(
        self, request: GenerateResourceDraftInput
    ) -> tuple[AgentPackage, tuple[AgentVerification, ...]]:
        if request.resource not in RESOURCE_FIELDS:
            raise ResourceDraftError("unsupported draft resource")
        session = self._sessions.get(request.session_id)
        if (
            session is None
            or session.owner_id != request.owner_id
            or session.mode != "assistant"
        ):
            raise ResourceDraftError("assistant session not found")
        if (
            session.status not in OPEN_STATUSES
            or not self._settings.get().assistant_enabled
        ):
            raise ResourceDraftError("assistant session is closed or disabled")
        message = self._messages.get_by_client_message_id(
            request.session_id, request.client_message_id
        )
        if (
            message is None
            or message.role != "user"
            or message.author_id != request.owner_id
        ):
            raise ResourceDraftError("source message not found")
        prompt_name = f"agent.{request.resource}.generate"
        active = self._prompts.get_active(prompt_name)
        if active is None:
            raise ResourceDraftError("resource prompt unavailable")
        pinned = session.prompt_versions.get(prompt_name, {}).get("version")
        prompt = self._prompts.get_version(
            prompt_name, int(pinned) if pinned is not None else active.version
        )
        if prompt is None:
            raise ResourceDraftError("resource prompt version unavailable")
        context = self._resources.context(request.resource)
        source = message.content
        raw = self._generator.generate(
            AgentStructuredGenerationInput(
                system_prompt=prompt.content,
                persisted_context=json.dumps(context, ensure_ascii=False),
                masked_user_message=source,
            )
        )
        try:
            payload = json.loads(_strip_fence(raw))
        except (ValueError, TypeError) as error:
            raise ResourceDraftError("generator returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict):
            raise ResourceDraftError("generator returned invalid draft")
        proposed = payload["draft"]
        clean, leaked = _mask_tree(proposed, self._masker)
        draft = {field: clean.get(field) for field in RESOURCE_FIELDS[request.resource]}
        checks = self._resources.verify(request.resource, draft)
        checks.append(
            (
                "personal_data",
                "FAIL" if leaked else "PASS",
                "PERSONAL_DATA_REDACTED" if leaked else None,
            )
        )
        fields = RESOURCE_FIELDS[request.resource]
        provenance = {}
        raw_provenance = payload.get("field_provenance", {})
        for field in fields:
            info = (
                raw_provenance.get(field, {})
                if isinstance(raw_provenance, dict)
                else {}
            )
            quote = info.get("source_quote") if isinstance(info, dict) else None
            valid = isinstance(quote, str) and bool(quote) and quote in source
            provenance[field] = {
                "source": "user_input" if valid else "inferred",
                "source_message_id": message.message_id if valid else None,
                "source_quote": quote if valid else None,
            }
        now = self._clock.now()
        package_id, item_id = str(self._ids.new_id()), str(self._ids.new_id())
        item = {
            "item_id": item_id,
            "item_type": f"agent_resource:{request.resource}",
            "operation": "create",
            "target_ref": None,
            "base_version": None,
            "draft": draft,
            "diff": {
                key: {"before": None, "after": value} for key, value in draft.items()
            },
            "field_provenance": provenance,
            "source_message_id": message.message_id,
            "verification_status": "PASS"
            if all(check[1] == "PASS" for check in checks)
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
        return package, saved


@dataclass(frozen=True)
class ConfirmResourceDraftInput:
    session_id: str
    owner_id: str
    role: str
    package_id: str
    item_id: str


class ConfirmResourceDraftUseCase:
    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        packages: AgentPackageRepository,
        verifications: AgentVerificationRepository,
        confirmations: AgentConfirmationRepository,
        resources: AgentDraftResourcePort,
        audit: AuditPort,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._sessions, self._packages, self._verifications = (
            sessions,
            packages,
            verifications,
        )
        self._confirmations, self._resources = confirmations, resources
        self._audit, self._clock, self._ids = audit, clock, ids

    def execute(self, request: ConfirmResourceDraftInput) -> dict[str, str]:
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
            raise ResourceDraftError("draft not found")
        item = next(
            (
                row
                for row in package.content.get("items", [])
                if isinstance(row, dict) and row.get("item_id") == request.item_id
            ),
            None,
        )
        checks = self._verifications.list_for_subject(package.package_id)
        if item is None or not isinstance(item.get("draft"), dict):
            raise ResourceDraftError("draft item not found")
        resource = item.get("item_type", "").removeprefix("agent_resource:")
        if (
            resource not in RESOURCE_FIELDS
            or item.get("verification_status") != "PASS"
            or not checks
            or any(check.status != "PASS" for check in checks)
        ):
            raise ResourceDraftError("draft has blocking verifications")
        now, confirmation_id = self._clock.now(), str(self._ids.new_id())
        self._confirmations.create(
            AgentConfirmation(
                confirmation_id=confirmation_id,
                session_id=request.session_id,
                package_id=package.package_id,
                item_id=request.item_id,
                action="create",
                content_hash=_hash(item),
                confirmed_by=request.owner_id,
                confirmed_at=now,
                role=request.role,
                base_version=None,
                verification_states={check.verifier: check.status for check in checks},
                source_message_id=item.get("source_message_id"),
            )
        )
        entity_id = self._resources.create(resource, item["draft"])
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=request.owner_id,
                worker_name=None,
                action=f"agent.{resource}.applied",
                entity_type=resource,
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


def _mask_tree(value: Any, masker: PersonalDataMasker) -> tuple[Any, int]:
    if isinstance(value, str):
        masked = masker.mask(value)
        return masked.text, sum(masked.counts.values())
    if isinstance(value, list):
        rows = [_mask_tree(item, masker) for item in value]
        return [item[0] for item in rows], sum(item[1] for item in rows)
    if isinstance(value, dict):
        mapped = {key: _mask_tree(item, masker) for key, item in value.items()}
        return {key: item[0] for key, item in mapped.items()}, sum(
            item[1] for item in mapped.values()
        )
    return value, 0


def _questions(value: Any, masker: PersonalDataMasker) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        masker.mask(item.strip()).text
        for item in value[:10]
        if isinstance(item, str) and item.strip()
    ]


def _strip_fence(value: str) -> str:
    result = value.strip()
    if result.startswith("```") and result.endswith("```"):
        result = result[3:-3].strip()
        if result.startswith("json"):
            result = result[4:].strip()
    return result


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
