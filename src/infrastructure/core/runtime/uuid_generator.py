from functools import lru_cache
from uuid import UUID, uuid4

from src.application.ports.id_generator_port import IdGenerator


class Uuid4Generator(IdGenerator):
    def new_id(self) -> UUID:
        return uuid4()


@lru_cache(maxsize=1)
def get_id_generator() -> IdGenerator:
    return Uuid4Generator()
