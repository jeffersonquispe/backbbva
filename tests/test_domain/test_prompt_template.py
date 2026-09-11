from src.domain.models.prompt_template import substitute_variables


def test_known_tokens_are_replaced_with_their_values():
    assert substitute_variables(
        "Saldo: {saldo}, canal: {canal}", {"saldo": 1200.5, "canal": "App"}
    ) == "Saldo: 1200.5, canal: App"


def test_unknown_token_is_left_literal():
    assert substitute_variables("Hola {desconocido}", {"saldo": 1}) == "Hola {desconocido}"


def test_non_string_values_are_stringified():
    assert substitute_variables("{activo}", {"activo": True}) == "True"


def test_text_without_tokens_is_returned_unchanged():
    assert substitute_variables("texto plano", {}) == "texto plano"


def test_stray_braces_do_not_raise():
    assert substitute_variables("literal { sin cierre", {}) == "literal { sin cierre"
