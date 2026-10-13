from __future__ import annotations


class ConfigurationNotFoundError(Exception):
    """Raised when a test run explicitly pins a ConfigurationRef
    (configuration_id [+ version]) that doesn't resolve to a stored
    ConfigurationRecord. Deliberately fails loud here, unlike the
    no-ref production path (_resolve_segment in alert_review_workflow.py),
    which fails safe to "no active config" - an explicit test override
    silently falling back to the active configuration would corrupt the
    meaning of the test.
    """

    def __init__(self, configuration_id: str, version: int | None) -> None:
        self.configuration_id = configuration_id
        self.version = version
        where = f"version {version}" if version is not None else "any version"
        super().__init__(f"Configuration '{configuration_id}' ({where}) not found.")
