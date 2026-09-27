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
"""

import sys


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


def main(argv=None) -> None:
    from watchtower_pipeline import kitsu

    patch_parser(kitsu)
    kitsu.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    main()
