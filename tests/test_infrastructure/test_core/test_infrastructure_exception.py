from src.infrastructure import InfrastructureException


class TestInfrastructureException:
    def test_init(self):
        """Ensure InfrastructureException
        initializes with the correct message."""

        message = "Error en el infraestructura"
        error = InfrastructureException(message)
        assert str(error) == message

    def test_srt(self):
        """Ensure string representation
        of InfrastructureException is correct."""

        message = "Error en el infraestructura"
        error = InfrastructureException(message)
        assert str(error) == message
