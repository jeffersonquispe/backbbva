from __future__ import annotations

from src.application.use_cases.agent.retrieve_project_context import (
    RetrieveProjectContextInput,
    RetrieveProjectContextUseCase,
)

MAX_QUERY_CHARS = 200
TOOL_RESULT_CHARS = 2_000
NO_RESULT = "Sin resultados en el mapa de ARIA para esa consulta."


class ProjectToolbox:
    """The two read-only tools the chat model may call, scoped to one turn.

    Scope (role, current page, earlier messages) comes from the server, never
    from the model, so a tool call cannot widen what the user is allowed to see.
    ``surfaced`` collects every node id shown to the model so its citations can
    be validated against what it was actually given.
    """

    def __init__(
        self,
        *,
        retriever: RetrieveProjectContextUseCase,
        role: str,
        page_path: str,
        history: tuple[str, ...],
    ) -> None:
        self._retriever = retriever
        self._role = role
        self._page_path = page_path
        self._history = history
        self.surfaced: set[str] = set()

    def search_project(self, query: str) -> str:
        context = self._retriever.execute(
            RetrieveProjectContextInput(
                query=str(query)[:MAX_QUERY_CHARS],
                page_path=self._page_path,
                role=self._role,
                history=self._history,
                max_nodes=10,
                max_chars=TOOL_RESULT_CHARS,
            )
        )
        self.surfaced.update(context.node_ids)
        return context.text or NO_RESULT

    def describe_node(self, node_id: str) -> str:
        text = self._retriever.describe(str(node_id)[:MAX_QUERY_CHARS], self._role)
        if text:
            self.surfaced.add(str(node_id))
        return text or NO_RESULT
