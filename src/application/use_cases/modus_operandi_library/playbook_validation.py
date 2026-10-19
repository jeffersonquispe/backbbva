from src.application.errors import ValidationError
from src.domain.fraud_knowledge.library_entities import (
    FALLBACK_RESOLUTION_TAGS,
    PRIMARY_RESOLUTION_TAGS,
    ModusOperandiPlaybook,
)


class InvalidModusOperandiPlaybookError(ValidationError):
    pass


def validate_playbook(playbook: ModusOperandiPlaybook) -> None:
    if playbook.resolution.resolution_tag not in PRIMARY_RESOLUTION_TAGS:
        raise InvalidModusOperandiPlaybookError(
            "Playbook resolution must be scale_to_analyst, send_to_voicebot "
            "or handle_by_aria."
        )
    for name, fallback in (
        ("if_no_voicebot", playbook.if_no_voicebot),
        ("if_no_analyst", playbook.if_no_analyst),
    ):
        if fallback.resolution_tag not in FALLBACK_RESOLUTION_TAGS:
            raise InvalidModusOperandiPlaybookError(
                f"Playbook {name} must name a resource or a block, "
                "not handle_by_aria."
            )
    if playbook.if_no_voicebot.resolution_tag == "send_to_voicebot":
        raise InvalidModusOperandiPlaybookError(
            "if_no_voicebot cannot route back to the voicebot."
        )
    if playbook.if_no_analyst.resolution_tag == "scale_to_analyst":
        raise InvalidModusOperandiPlaybookError(
            "if_no_analyst cannot route back to an analyst."
        )
