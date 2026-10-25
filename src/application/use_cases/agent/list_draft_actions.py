from dataclasses import dataclass

from src.application.ports.local_auth_port import ROLE_PERMISSIONS, LocalRole


@dataclass(frozen=True)
class AgentDraftAction:
    action_id: str
    label: str
    endpoint_kind: str
    operations: tuple[str, ...]
    required_permissions: tuple[str, ...]
    fields: tuple[str, ...]
    context: tuple[str, ...]


_LIBRARY_DRAFT_ACTIONS = (
    AgentDraftAction(
        action_id="taxonomy",
        label="Taxonomía",
        endpoint_kind="taxonomy",
        operations=("create", "update"),
        required_permissions=("configuration", "library"),
        fields=("code", "name", "description", "variables", "examples"),
        context=("taxonomy_schema", "existing_taxonomies"),
    ),
    AgentDraftAction(
        action_id="modus_operandi",
        label="Modus operandi / playbook",
        endpoint_kind="modus-operandi",
        operations=("create", "update"),
        required_permissions=("configuration", "library"),
        fields=(
            "title",
            "narrative",
            "taxonomy_library_id",
            "evolved_variables",
            "playbook",
        ),
        context=(
            "modus_operandi_schema",
            "available_taxonomies",
            "resolution_tag_enum",
        ),
    ),
    AgentDraftAction(
        action_id="flag",
        label="Flag",
        endpoint_kind="flag",
        operations=("create", "update"),
        required_permissions=("configuration", "library"),
        fields=(
            "flag_type",
            "name",
            "description",
            "evolved_variables",
            "modus_operandi_library_ids",
        ),
        context=("flag_schema", "flag_type_enum", "modus_operandi_entries"),
    ),
    AgentDraftAction(
        action_id="similar_case",
        label="Caso similar",
        endpoint_kind="similar-case",
        operations=("create", "update"),
        required_permissions=("configuration", "library"),
        fields=("text", "modus_operandi_library_id", "taxonomy_library_id"),
        context=("similar_case_schema", "modus_operandi_entries", "taxonomies"),
    ),
    AgentDraftAction(
        action_id="watchlist",
        label="Watchlist",
        endpoint_kind="watchlist",
        operations=("create", "update"),
        required_permissions=("configuration", "library"),
        fields=("name", "description", "list_type"),
        context=("watchlist_schema", "list_type_enum", "existing_watchlists"),
    ),
)


def list_agent_draft_actions(role: LocalRole) -> tuple[AgentDraftAction, ...]:
    """Return only draft actions allowed by the authenticated role's permissions."""
    permissions = ROLE_PERMISSIONS.get(role, frozenset())
    return tuple(
        action
        for action in _LIBRARY_DRAFT_ACTIONS
        if all(permission in permissions for permission in action.required_permissions)
    )
