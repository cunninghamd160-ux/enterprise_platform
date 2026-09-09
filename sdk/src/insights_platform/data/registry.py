from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

type Kind = Literal["sql", "http"]


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    name: str
    kind: Kind
    keys: tuple[str, ...]

    def env_var(self, key: str) -> str:
        return f"INSIGHTS_CONN_{self.name.upper().replace('-', '_')}_{key.upper()}"


KNOWN_CONNECTIONS: Mapping[str, ConnectionSpec] = {
    "warehouse": ConnectionSpec("warehouse", "sql", ("url",)),
    "hr-api": ConnectionSpec("hr-api", "http", ("url", "token")),
}
