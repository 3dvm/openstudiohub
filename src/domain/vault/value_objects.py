# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/vault/value_objects.py
# Architectural role: Vault value objects (SemVer)
# =========================================================================================

"""Vault value objects."""

import re
from dataclasses import dataclass
from typing import Tuple, Union


def _compare_padded(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    length = max(len(a), len(b))
    pa = a + (0,) * (length - len(a))
    pb = b + (0,) * (length - len(b))
    return (pa > pb) - (pa < pb)


@dataclass(frozen=True)
class SemVer:
    """A lenient semantic-version value object (numeric parts only)."""

    parts: Tuple[int, ...] = (0,)

    @classmethod
    def parse(cls, value: Union[str, Tuple[int, ...], "SemVer", None]) -> "SemVer":
        if isinstance(value, SemVer):
            return value
        if isinstance(value, (tuple, list)):
            parts = tuple(int(p) for p in value if str(p).isdigit())
        else:
            clean = re.sub(r"[^0-9.]", "", str(value or ""))
            parts = tuple(int(p) for p in clean.split(".") if p.isdigit())
        return cls(parts or (0,))

    def padded(self, length: int) -> Tuple[int, ...]:
        return self.parts + (0,) * (length - len(self.parts))

    def __str__(self) -> str:
        return ".".join(str(p) for p in self.parts)

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            other = SemVer.parse(other)  # type: ignore[arg-type]
        return _compare_padded(self.parts, other.parts) >= 0

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            other = SemVer.parse(other)  # type: ignore[arg-type]
        return _compare_padded(self.parts, other.parts) < 0
