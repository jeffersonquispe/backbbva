from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.application.ports.agent_confirmation_port import AgentConfirmation
from src.application.ports.agent_message_port import AgentMessage
from src.application.ports.agent_package_port import AgentPackage
from src.application.ports.agent_prompt_port import ActiveAgentPrompt, AgentPrompt
from src.application.ports.agent_session_port import AgentSession, AgentSessionStatus
from src.application.ports.agent_subagent_port import (
    AgentSubagentInput,
    AgentSubagentOutput,
)
from src.application.ports.agent_verification_port import AgentVerification
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)
from src.application.ports.audit_port import AuditEntry
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.use_cases.agent.draft_modus_operandi import (
    AgentDraftConflictError,
    AgentDraftPolicyError,
    ConfirmModusOperandiDraftInput,
    ConfirmModusOperandiDraftUseCase,
    GenerateModusOperandiDraftInput,
    GenerateModusOperandiDraftUseCase,
)
from src.domain.configurations.entities import ResolutionTag, ShortageBehavior
from src.domain.fraud_knowledge.library_entities import (
    ModusOperandiLibraryEntry,
    ModusOperandiPlaybook,
    TaxonomyLibraryEntry,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
VALID_DRAFT = {
    "title": "Suplantación en canal digital",
    "narrative": "El defraudador suplanta al titular durante la autenticación.",
    "taxonomy_library_id": "tax-1",
    "evolved_variables": ["canal", "dispositivo"],
    "playbook": {
        "strategy": "Solicitar validación reforzada.",
        "resolution": {
            "resolution_tag": "handle_by_aria",
            "resolution_method_id": "method-aria",
        },
        "if_no_voicebot": {
            "resolution_tag": "scale_to_analyst",
            "resolution_method_id": "method-analyst",
        },
        "if_no_analyst": {
            "resolution_tag": "block_soft",
            "resolution_method_id": "method-block",
        },
    },
}


class InMemorySessions:
    def __init__(self, session: AgentSession) -> None:
        self.session = session

    def get(self, session_id: str) -> AgentSession | None:
        return self.session if self.session.session_id == session_id else None


class InMemoryMessages:
    def __init__(self, message: AgentMessage) -> None:
        self.message = message

    def get_by_client_message_id(self, session_id: str, client_message_id: str):
        if (session_id, client_message_id) == (
            self.message.session_id,
            self.message.client_message_id,
        ):
            return self.message
        return None


class InMemoryPrompts:
    def __init__(self) -> None:
        self.prompt = AgentPrompt(
            name="agent.modus_operandi.generate",
            version=2,
            content="prompt immutable",
            content_hash="prompt-hash",
            status="ACTIVE",
            created_at=NOW,
        )

    def get_active(self, name: str):
        return ActiveAgentPrompt(name, 2, NOW, "test")

    def get_version(self, name: str, version: int):
        return self.prompt if version == self.prompt.version else None


class InMemoryPackages:
    def __init__(self) -> None:
        self.rows: dict[str, AgentPackage] = {}

    def create(self, package: AgentPackage) -> AgentPackage:
        self.rows[package.package_id] = package
        return package

    def get(self, package_id: str):
        return self.rows.get(package_id)


class InMemoryVerifications:
    def __init__(self) -> None:
        self.rows: list[AgentVerification] = []

    def create(self, verification: AgentVerification) -> AgentVerification:
        self.rows.append(verification)
        return verification

    def list_for_subject(self, subject_id: str) -> list[AgentVerification]:
        return [row for row in self.rows if row.subject_id == subject_id]


class InMemoryEntries:
    def __init__(self, rows: list[ModusOperandiLibraryEntry] | None = None) -> None:
        self.rows = {row.id: row for row in rows or []}

    def get(self, entry_id: str):
        return self.rows.get(entry_id)

    def list(self, *, active_only: bool = False):
        rows = list(self.rows.values())
        return [row for row in rows if row.active] if active_only else rows


class InMemoryTaxonomies:
    def get(self, entry_id: str):
        if entry_id != "tax-1":
            return None
        return TaxonomyLibraryEntry(
            id="tax-1",
            code="digital",
            name="Canal digital",
            description="",
            created_at=NOW,
            updated_at=NOW,
            active=True,
        )

    def list(self, *, active_only: bool = False):
        entry = self.get("tax-1")
        return [entry] if entry is not None and (entry.active or not active_only) else []


class InMemorySettings:
    def get(self) -> AssistantOptimizerSettings:
        return AssistantOptimizerSettings(assistant_enabled=True)


class RecordingSubagent:
    name = "modus_operandi_generator"

    def __init__(self, contribution: dict) -> None:
        self.contribution = contribution
        self.request: AgentSubagentInput | None = None

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        self.request = request
        return AgentSubagentOutput(self.name, self.contribution, "PENDING_VERIFICATION")


class InMemoryPersonalDataMasker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        masked, cc_count = re.subn(r"\b\d{8,10}\b", "[CC]", text)
        return MaskedPersonalData(masked, {"CC": cc_count} if cc_count else {})


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class UuidGenerator(IdGenerator):
    def new_id(self):
        return uuid4()


class InMemoryConfirmations:
    def __init__(self) -> None:
        self.rows: list[AgentConfirmation] = []

    def create(self, confirmation: AgentConfirmation) -> AgentConfirmation:
        self.rows.append(confirmation)
        return confirmation

    def list_for_session(self, session_id: str, limit: int = 100):
        return [row for row in self.rows if row.session_id == session_id][:limit]


class RecordingApplier:
    def __init__(self) -> None:
        self.created = []
        self.updated = []

    def create(self, fields):
        self.created.append(fields)
        return "created-entry"

    def update(self, entry_id, fields, expected_updated_at):
        self.updated.append((entry_id, fields, expected_updated_at))
        return entry_id


class RecordingAudit:
    def __init__(self) -> None:
        self.rows: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self.rows.append(entry)


def _contribution(draft: dict | None = None) -> dict:
    return {
        "draft": VALID_DRAFT if draft is None else draft,
        "field_provenance": {
            "title": {"source": "user_input", "source_quote": "Suplantación"},
            "narrative": {"source": "inferred"},
            "taxonomy_library_id": {"source": "agent_generated"},
            "evolved_variables": {"source": "agent_generated"},
            "playbook": {"source": "agent_generated"},
        },
        "questions": [],
    }


def _session() -> AgentSession:
    return AgentSession(
        session_id="session-1",
        mode="assistant",
        status=AgentSessionStatus.ACTIVE,
        owner_id="owner-1",
        created_at=NOW,
        updated_at=NOW,
        prompt_versions={},
        budget_limits={"tokens": 1_000},
    )


def _entry(entry_id: str, updated_at: datetime = NOW) -> ModusOperandiLibraryEntry:
    return ModusOperandiLibraryEntry(
        id=entry_id,
        title="Nombre anterior",
        narrative="Narrativa anterior",
        taxonomy_library_id="tax-1",
        created_at=NOW - timedelta(days=1),
        updated_at=updated_at,
        playbook=ModusOperandiPlaybook(
            strategy="Validar",
            resolution=ShortageBehavior(ResolutionTag.HANDLE_BY_ARIA),
            if_no_voicebot=ShortageBehavior(ResolutionTag.SCALE_TO_ANALYST),
            if_no_analyst=ShortageBehavior(ResolutionTag.BLOCK_SOFT),
        ),
    )


def _make_generate(draft: dict | None = None, entries=None):
    message = AgentMessage(
        session_id="session-1",
        client_message_id="client-1",
        message_id="message-1",
        seq=1,
        role="user",
        content="Crea un modus operandi de Suplantación en canal digital.",
        author_id="owner-1",
        created_at=NOW,
    )
    packages = InMemoryPackages()
    verifications = InMemoryVerifications()
    subagent = RecordingSubagent(_contribution(draft))
    use_case = GenerateModusOperandiDraftUseCase(
        sessions=InMemorySessions(_session()),
        messages=InMemoryMessages(message),
        prompts=InMemoryPrompts(),
        packages=packages,
        verifications=verifications,
        entries=entries or InMemoryEntries(),
        taxonomies=InMemoryTaxonomies(),
        settings=InMemorySettings(),
        subagent=subagent,
        masker=InMemoryPersonalDataMasker(),
        clock=FixedClock(),
        id_generator=UuidGenerator(),
    )
    request = GenerateModusOperandiDraftInput(
        session_id="session-1",
        owner_id="owner-1",
        client_message_id="client-1",
        operation="create",
    )
    return use_case, request, packages, verifications, subagent


def test_generate_draft_verifies_and_tracks_field_provenance_without_writing_live_entry():
    entries = InMemoryEntries()
    use_case, request, packages, verifications, subagent = _make_generate(entries=entries)

    result = use_case.execute(request)

    item = result.package.content["items"][0]
    assert result.package.status == "SEALED"
    assert item["verification_status"] == "PASS"
    assert item["field_provenance"]["title"]["source"] == "user_input"
    assert item["field_provenance"]["title"]["source_message_id"] == "message-1"
    assert {check.status for check in verifications.rows} == {"PASS"}
    assert not entries.rows
    assert subagent.request is not None
    assert subagent.request.scope["system_prompt"] == "prompt immutable"
    assert subagent.request.scope["available_taxonomies"] == [
        {"id": "tax-1", "code": "digital", "name": "Canal digital"}
    ]
    assert "handle_by_aria" in subagent.request.scope["resolution_tag_enum"]
    assert packages.get(result.package.package_id) == result.package


def test_missing_required_playbook_fields_block_confirmation_and_do_not_apply():
    incomplete = {**VALID_DRAFT, "playbook": None}
    generate, request, packages, verifications, _subagent = _make_generate(incomplete)
    result = generate.execute(request)
    confirmations = InMemoryConfirmations()
    applier = RecordingApplier()
    use_case = ConfirmModusOperandiDraftUseCase(
        sessions=InMemorySessions(_session()),
        packages=packages,
        verifications=verifications,
        confirmations=confirmations,
        entries=InMemoryEntries(),
        applier=applier,
        audit=RecordingAudit(),
        clock=FixedClock(),
        id_generator=UuidGenerator(),
    )

    with pytest.raises(AgentDraftPolicyError):
        use_case.execute(
            ConfirmModusOperandiDraftInput(
                "session-1", "owner-1", "manager", result.package.package_id,
                result.package.content["items"][0]["item_id"],
            )
        )

    assert not confirmations.rows
    assert not applier.created


def test_personal_data_is_masked_in_draft_and_blocks_approval():
    draft = {**VALID_DRAFT, "narrative": "Titular identificado con CC 123456789."}
    use_case, request, _packages, verifications, _subagent = _make_generate(draft)

    result = use_case.execute(request)

    item = result.package.content["items"][0]
    assert "123456789" not in str(item["draft"])
    assert item["verification_status"] == "FAIL"
    assert next(check for check in verifications.rows if check.verifier == "leakage").status == "FAIL"


def test_duplicate_title_and_incoherent_playbook_fallbacks_fail_verification():
    invalid_playbook = {
        **VALID_DRAFT,
        "playbook": {
            **VALID_DRAFT["playbook"],
            "if_no_analyst": {
                "resolution_tag": "scale_to_analyst",
                "resolution_method_id": None,
            },
        },
    }
    existing = _entry("existing-1")
    existing.title = VALID_DRAFT["title"]
    use_case, request, _packages, verifications, _subagent = _make_generate(
        invalid_playbook,
        entries=InMemoryEntries([existing]),
    )

    result = use_case.execute(request)

    item = result.package.content["items"][0]
    by_verifier = {check.verifier: check.status for check in verifications.rows}
    assert item["verification_status"] == "FAIL"
    assert by_verifier["duplicates"] == "FAIL"
    assert by_verifier["playbook_fallbacks"] == "FAIL"


def test_update_confirmation_rejects_stale_base_version():
    entry = _entry("entry-1")
    entries = InMemoryEntries([entry])
    generate, request, packages, verifications, _subagent = _make_generate(entries=entries)
    request = GenerateModusOperandiDraftInput(
        session_id="session-1",
        owner_id="owner-1",
        client_message_id="client-1",
        operation="update",
        target_id="entry-1",
    )
    result = generate.execute(request)
    entries.rows["entry-1"] = _entry("entry-1", NOW + timedelta(seconds=1))
    confirmations = InMemoryConfirmations()
    applier = RecordingApplier()
    use_case = ConfirmModusOperandiDraftUseCase(
        sessions=InMemorySessions(_session()),
        packages=packages,
        verifications=verifications,
        confirmations=confirmations,
        entries=entries,
        applier=applier,
        audit=RecordingAudit(),
        clock=FixedClock(),
        id_generator=UuidGenerator(),
    )

    with pytest.raises(AgentDraftConflictError):
        use_case.execute(
            ConfirmModusOperandiDraftInput(
                "session-1", "owner-1", "manager", result.package.package_id,
                result.package.content["items"][0]["item_id"],
            )
        )

    assert not confirmations.rows
    assert not applier.updated


def test_explicit_confirmation_is_audited_before_applying_candidate():
    generate, request, packages, verifications, _subagent = _make_generate()
    result = generate.execute(request)
    confirmations = InMemoryConfirmations()
    applier = RecordingApplier()
    audit = RecordingAudit()
    use_case = ConfirmModusOperandiDraftUseCase(
        sessions=InMemorySessions(_session()),
        packages=packages,
        verifications=verifications,
        confirmations=confirmations,
        entries=InMemoryEntries(),
        applier=applier,
        audit=audit,
        clock=FixedClock(),
        id_generator=UuidGenerator(),
    )

    response = use_case.execute(
        ConfirmModusOperandiDraftInput(
            "session-1", "owner-1", "channel_manager", result.package.package_id,
            result.package.content["items"][0]["item_id"],
        )
    )

    assert response["entity_id"] == "created-entry"
    assert confirmations.rows[0].role == "channel_manager"
    assert confirmations.rows[0].content_hash
    assert [row.action for row in audit.rows] == [
        "agent.modus_operandi.confirmed",
        "agent.modus_operandi.applied",
    ]
    assert len(applier.created) == 1
