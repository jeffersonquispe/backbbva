from src.domain import DomainException


class TestDomainException:
    def test_init(self):
        """Ensure DomainException initializes with the correct message."""

        message = "Error en el dominio"
        error = DomainException(message)
        assert str(error) == message

    def test_srt(self):
        """Ensure DomainException initializes with the correct message."""

        message = "Error en el dominio"
        error = DomainException(message)
        assert str(error) == message
