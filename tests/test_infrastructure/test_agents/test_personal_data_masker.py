from src.application.use_cases.agent.draft_watchlist import (
    WatchlistDraftPolicyError,
    _restore_element_values,
)
from src.infrastructure.agents.rule_based_personal_data_masker import (
    RuleBasedPersonalDataMasker,
)


def test_masks_colombian_identifiers_and_preserves_operation_context_and_amounts() -> (
    None
):
    masker = RuleBasedPersonalDataMasker()
    text = (
        "Nombre: Juan Perez; CC 1.234.567.890; NIT 900.123.456-7; "
        "celular +57 310 555 1234; cuenta 123456789012; "
        "tarjeta 4111 1111 1111 1111; monto $250.000"
    )

    result = masker.mask(text)

    assert "Juan Perez" not in result.text
    assert "1.234.567.890" not in result.text
    assert "900.123.456-7" not in result.text
    assert "310 555 1234" not in result.text
    assert "123456789012" not in result.text
    assert "4111 1111 1111 1111" not in result.text
    assert "$250.000" in result.text
    assert "fraude" in result.text or "monto" in result.text
    assert result.counts == {
        "PERSONA": 1,
        "CC": 1,
        "NIT": 1,
        "TEL": 1,
        "CUENTA": 1,
        "TARJETA": 1,
    }


def test_masks_email_and_ip_and_uses_consistent_per_message_markers() -> None:
    result = RuleBasedPersonalDataMasker().mask(
        "correo ana@example.com, ip 10.20.30.40 y teléfono 3001234567 y 3001234567"
    )

    assert result.text.count("[TEL_1]") == 1
    assert "[TEL_2]" in result.text
    assert "[EMAIL_1]" in result.text
    assert "[IP_1]" in result.text
    assert result.counts["TEL"] == 2


def test_masks_card_number_even_when_checksum_is_invalid() -> None:
    text = "tarjeta 4111 1111 1111 1112"

    result = RuleBasedPersonalDataMasker().mask(text)

    assert "4111 1111 1111 1112" not in result.text
    assert result.counts["TARJETA"] == 1


def test_preserves_uuid_references_and_masks_personal_data_next_to_them() -> None:
    masker = RuleBasedPersonalDataMasker()
    reference = "5909a2d1-a66f-4c26-b123-456789012345"
    text = f"{reference} 4111 1111 1111 1111, teléfono 3001234567"

    result = masker.mask(text)

    assert reference in result.text
    assert "4111 1111 1111 1111" not in result.text
    assert "3001234567" not in result.text
    assert result.counts == {"TARJETA": 1, "TEL": 1}
    assert masker.unmask(result.text, result.replacements) == text


def test_masks_email_even_when_its_local_part_is_a_uuid() -> None:
    email = "5909a2d1-a66f-4c26-b123-456789012345@example.com"

    result = RuleBasedPersonalDataMasker().mask(f"Contactar {email}")

    assert email not in result.text
    assert result.counts == {"EMAIL": 1}


def test_restores_only_values_from_the_same_masking_request() -> None:
    masker = RuleBasedPersonalDataMasker()
    result = masker.mask("Añade CC 123456789 y correo ana@example.com")

    assert result.text == "Añade CC [CC_1] y correo [EMAIL_1]"
    assert masker.unmask("[CC_1] / [EMAIL_1]", result.replacements) == (
        "123456789 / ana@example.com"
    )
    assert masker.unmask("[CC_2]", result.replacements) == "[CC_2]"


def test_watchlist_element_values_restore_only_request_placeholders() -> None:
    masker = RuleBasedPersonalDataMasker()
    source = "Agrega la cédula 123456789 y ana@example.com"
    masked = masker.mask(source)

    assert _restore_element_values(
        ["[CC_1]", "[EMAIL_1]"], masked.replacements, masker, source
    ) == ["123456789", "ana@example.com"]
    try:
        _restore_element_values(["[CC_2]"], masked.replacements, masker, source)
    except WatchlistDraftPolicyError as error:
        assert "placeholder" in str(error)
    else:
        raise AssertionError("unknown placeholder must not be restored")
