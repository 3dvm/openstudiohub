# =========================================================================================
# OPENSTUDIOHUB
# Módulo: src/infrastructure/watchtower_runner.py
# Rol Arquitectónico: Compatibility shim over watchtower_pipeline
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.1.0
# =========================================================================================

"""Compatibility shim for the ``watchtower_pipeline`` CLI.

Upstream ``Config.get_env_data_as_dict`` parses each dotenv line with a bare
``line.split('=')`` and feeds the result to ``dict()``. Any ``=`` inside a value
(common in generated Kitsu passwords) yields a 3-tuple and the pipeline aborts::

    ValueError: dictionary update sequence element #2 has length 3; 2 is required

This runner installs a corrected parser (``split('=', 1)``, ignoring blank and
comment lines) before delegating to the upstream ``main``. It lives in our repo
because patching ``site-packages`` is not durable across reinstalls.

It also guards ``KitsuProjectWriter.get_project_edit``. Upstream only handles a
project with *no* edit; a legacy project whose Edit entity was never rendered
(exists, but has no preview under the ``Edit`` task type) leaves
``latest_preview`` as ``None`` and aborts the whole bundle with::

    TypeError: 'NoneType' object is not subscriptable

Those projects are degraded to an empty edit (the same state upstream already
produces for projects with no edit) so the remaining projects still build.

It also guards ``KitsuProjectWriter.get_project_casting``. Upstream looks up
each casting reference in the already-filtered shots/assets lists, so a legacy
shot without ``frame_in`` (skipped) or a canceled asset leaves ``None`` in the
casting model. Serialization then aborts with::

    AttributeError: 'NoneType' object has no attribute 'id'

Orphaned references are dropped instead of aborting the bundle.
"""

import logging
import sys

logger = logging.getLogger("watchtower_runner")


def safe_get_env_data_as_dict(path):
    """Parse a dotenv file without choking on ``=`` inside values.

    Values are kept verbatim (no quote stripping) so credentials written by
    :class:`~src.infrastructure.watchtower_launcher.WatchtowerLauncher` survive
    round-trip unchanged.
    """
    result = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            if not stripped.strip() or stripped.lstrip().startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            result[key.strip()] = value
    return result


def patch_parser(kitsu_module) -> None:
    """Replace the upstream dotenv parser with the safe one."""
    kitsu_module.Config.get_env_data_as_dict = staticmethod(safe_get_env_data_as_dict)


def patch_edit_guard(kitsu_module, models_module) -> None:
    """Make edit extraction resilient to edits without a rendered preview.

    Wraps ``KitsuProjectWriter.get_project_edit`` so that a missing/empty/null
    preview degrades to an empty edit instead of crashing the whole pipeline.
    Idempotent: re-patching is a no-op.
    """
    writer_cls = kitsu_module.KitsuProjectWriter
    original = writer_cls.get_project_edit
    if getattr(original, "_watchtower_guarded", False):
        return

    def guarded_get_project_edit(self, project):
        try:
            return original(self, project)
        except (TypeError, IndexError) as error:
            logger.warning(
                "Watchtower: project %s (%s) has an edit but no usable 'Edit' "
                "preview; continuing without an edit (%s).",
                getattr(project, "name", "?"),
                getattr(project, "id", "?"),
                error,
            )
            return models_module.Edit(project=project, totalFrames=0, frameOffset=0)

    guarded_get_project_edit._watchtower_guarded = True
    writer_cls.get_project_edit = guarded_get_project_edit


def patch_casting_guard(kitsu_module) -> None:
    """Make casting extraction resilient to orphaned shot/asset references.

    Wraps ``KitsuProjectWriter.get_project_casting`` to drop ``ShotCasting``
    entries whose shot is missing and ``None`` entries from each casting's
    asset list, instead of letting them abort serialization. Idempotent.
    """
    writer_cls = kitsu_module.KitsuProjectWriter
    original = writer_cls.get_project_casting
    if getattr(original, "_watchtower_guarded", False):
        return

    def guarded_get_project_casting(self, project, sequences, shots, assets):
        castings = original(self, project, sequences, shots, assets)
        cleaned = []
        dropped = 0
        for casting in castings:
            if getattr(casting, "shot", None) is None:
                dropped += 1
                continue
            filtered = [asset for asset in casting.assets if asset is not None]
            dropped += len(casting.assets) - len(filtered)
            casting.assets = filtered
            cleaned.append(casting)
        if dropped:
            logger.warning(
                "Watchtower: project %s (%s): dropped %d orphaned casting "
                "reference(s) (shot/asset not in the fetched lists).",
                getattr(project, "name", "?"),
                getattr(project, "id", "?"),
                dropped,
            )
        return cleaned

    guarded_get_project_casting._watchtower_guarded = True
    writer_cls.get_project_casting = guarded_get_project_casting


def main(argv=None) -> None:
    from watchtower_pipeline import kitsu, models

    patch_parser(kitsu)
    patch_edit_guard(kitsu, models)
    patch_casting_guard(kitsu)
    kitsu.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    main()
