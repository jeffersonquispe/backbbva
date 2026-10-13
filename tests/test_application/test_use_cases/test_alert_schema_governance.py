
import pytest

from src.application.dtos.alert_schema_dtos import (
    ApproveAlertSchemaInput,
    CreateAlertSchemaSuggestionInput,
)
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.use_cases.alert_schema.approve_schema import (
    ApproveAlertSchemaUseCase,
    ImpactAcknowledgementRequired,
    SelfApprovalError,
)
from src.application.use_cases.alert_schema.create_suggestion import (
    CreateAlertSchemaSuggestionUseCase,
    ListAlertSchemaSuggestionsUseCase,
)
from src.application.use_cases.alert_schema.propose_schema import (
    ProposeAlertSchemaUseCase,
)
from src.application.use_cases.alert_schema.reject_schema import (
    RejectAlertSchemaUseCase,
)


class InMemorySchemaRepository:
    def __init__(self, versions=()):
        self.items = {item.version: item for item in versions}

    def get_active(self):
        return next((item for item in self.items.values() if item.status == AlertSchemaStatus.ACTIVE), None)

    def list_versions(self):
        return list(self.items.values())

    def get(self, version):
        return self.items.get(version)

    def save_draft(self, schema):
        self.items[schema.version] = schema
        return schema

    def update(self, schema):
        self.items[schema.version] = schema
        return schema


class InMemorySuggestionRepository:
    def __init__(self):
        self.items = []

    def create(self, suggestion):
        self.items.append(suggestion)
        return suggestion

    def list(self):
        return list(self.items)



def field(field_id="amount", name="amount", description=""):
    return AlertSchemaField(field_id, AlertSchemaDataSource.ARIC, name, field_ds_loc=name, description=description)


def test_proposal_stores_field_diff_and_role_reassignment():
    active = AlertSchemaVersion(1, AlertSchemaStatus.ACTIVE, [field()], {"amount": "amount"})
    draft = AlertSchemaVersion(2, fields=[field(description="updated"), field("new", "merchant")], field_roles={"amount": "new"}, based_on_version=1)
    repository = InMemorySchemaRepository([active, draft])
    proposed = ProposeAlertSchemaUseCase(repository, lambda comparison: []).execute(2, "proposer")

    assert proposed.comparison["added"][0]["id"] == "new"
    assert proposed.comparison["changed"][0]["field"] == "amount"
    assert proposed.comparison["changed"][0]["attributes"]["description"]["after"] == "updated"
    assert proposed.comparison["role_reassignments"] == [{"role": "amount", "before": "amount", "after": "new"}]


def test_approval_rejects_self_approval_by_user_id():
    proposed = AlertSchemaVersion(2, AlertSchemaStatus.PROPOSED, proposed_by="same-id", based_on_version=1)
    repository = InMemorySchemaRepository([proposed])
    with pytest.raises(SelfApprovalError):
        ApproveAlertSchemaUseCase(repository).execute(ApproveAlertSchemaInput(2, "same-id"))


def test_approval_rejects_stale_proposal():
    active = AlertSchemaVersion(3, AlertSchemaStatus.ACTIVE)
    proposed = AlertSchemaVersion(2, AlertSchemaStatus.PROPOSED, proposed_by="other", based_on_version=1)
    repository = InMemorySchemaRepository([active, proposed])
    with pytest.raises(ValueError, match="stale"):
        ApproveAlertSchemaUseCase(repository).execute(ApproveAlertSchemaInput(2, "approver"))


def test_approval_requires_and_persists_impact_acknowledgement():
    proposed = AlertSchemaVersion(2, AlertSchemaStatus.PROPOSED, proposed_by="proposer", based_on_version=1, impact=[{"kind": "configuration", "id": "config"}])
    active = AlertSchemaVersion(1, AlertSchemaStatus.ACTIVE)
    repository = InMemorySchemaRepository([active, proposed])
    use_case = ApproveAlertSchemaUseCase(repository)
    with pytest.raises(ImpactAcknowledgementRequired):
        use_case.execute(ApproveAlertSchemaInput(2, "approver"))
    approved = use_case.execute(ApproveAlertSchemaInput(2, "approver", True))
    assert approved.status == AlertSchemaStatus.ACTIVE
    assert approved.impact_acknowledged is True


def test_suggestions_can_be_created_and_listed_without_a_mock():
    repository = InMemorySuggestionRepository()
    created = CreateAlertSchemaSuggestionUseCase(repository).execute(
        CreateAlertSchemaSuggestionInput("alert-1", "merchant", "merchant.name", "New field", "fraud-user")
    )

    assert ListAlertSchemaSuggestionsUseCase(repository).execute() == [created]
    assert created.created_by == "fraud-user"


def test_reject_only_applies_to_proposed_versions():
    repository = InMemorySchemaRepository(
        [AlertSchemaVersion(2, AlertSchemaStatus.PROPOSED, proposed_by="user-1")]
    )

    rejected = RejectAlertSchemaUseCase(repository).execute(2)

    assert rejected.status == AlertSchemaStatus.REJECTED
    with pytest.raises(ValueError, match="proposed"):
        RejectAlertSchemaUseCase(repository).execute(2)
