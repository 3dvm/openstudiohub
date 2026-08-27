# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/vault/compatibility.py
# Architectural role: Vault domain service / version compatibility
# =========================================================================================

"""Single version-compatibility rule.

Replaces the two divergent ``is_compatible`` implementations that previously
lived in ``AddonParser`` and ``AddonInspector``.
"""

from typing import Union

from .value_objects import SemVer


class CompatibilityPolicy:
    @staticmethod
    def is_compatible(min_version: Union[str, tuple], target_version: Union[str, tuple]) -> bool:
        """True if ``target_version`` satisfies ``min_version`` (target >= min).

        Falls back to True when either version cannot be parsed (leave the
        decision to TD judgment, preserving the legacy behavior).
        """
        try:
            return SemVer.parse(target_version) >= SemVer.parse(min_version)
        except Exception:  # noqa: BLE001
            return True
