# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/workspace/jailing.py
# Architectural role: Workspace domain service / JailingPolicy
# =========================================================================================

"""Sparse-checkout dependency ("jailing") policy.

Encodes the domain rule for resolving the ``//``-relative dependency syntax
(Blender's blend-file-relative convention) found in ``*-meta.json`` manifests,
plus the rule that a ``.blend`` dependency also pulls its companion
``-meta.json`` so the dependency chain can keep resolving.

Extracted from ``SparseManager`` (which keeps only the download orchestration).
"""

import os
from typing import List, Optional


class JailingPolicy:
    @staticmethod
    def resolve_dependency(meta_rel_dir: str, dependency: str) -> Optional[str]:
        """Resolve a ``//relative`` dependency into a repo-relative path.

        Returns ``None`` for dependencies that are not ``//``-relative (they are
        ignored, preserving the original behavior).
        """
        if not dependency.startswith("//"):
            return None
        rel_to_blend = dependency[2:]
        combined = os.path.normpath(os.path.join(meta_rel_dir, rel_to_blend))
        # SVN requires forward slashes.
        return combined.replace("\\", "/")

    @staticmethod
    def expand_with_meta(path: str) -> List[str]:
        """Return the path(s) to fetch for a resolved dependency.

        A ``.blend`` also requires its ``-meta.json`` so the chain can continue.
        """
        if path.endswith(".blend"):
            return [path, path.replace(".blend", "-meta.json")]
        return [path]
