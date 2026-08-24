# =========================================================================================
# OPENSTUDIOHUB
# Module: core/dev_defaults.py
# Architectural role: DEVELOPMENT-ONLY default credentials (single source of truth)
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
# =========================================================================================

"""
DEVELOPMENT-ONLY default credentials for local, self-hosted infrastructure.

These values bootstrap the local development loop only:
  * the local Docker Subversion server (`openstudio_local_svn`),
  * the local Docker Kitsu/Zou stack (`kitsu_local`) deployed by
    `ui/widget_infrastructure.py`,
  * the seed/dummy-account helpers used for local RBAC testing.

.. warning::
    DO NOT use these in production. They are committed only so the local
    development flow works out of the box. During the DDD refactor
    (Phases 1-4) they will be removed from the codebase entirely and read
    from the ConfigurationRepository / environment / a secret manager.
    Importing this module is a temporary, intentionally-flagged code smell.

    The *real* studio credentials must never live here; they are supplied at
    runtime (Kitsu login, SVN login dialogs) and held only in RAM.
"""

# --- Local Subversion (Docker `openstudio_local_svn`) bootstrap account. ---
DEV_SVN_USER = "admin"
DEV_SVN_PASSWORD = "admin123"

# --- Local Kitsu/Zou admin account used by seeders. ---
DEV_KITSU_ADMIN_EMAIL = "admin@example.com"
DEV_KITSU_ADMIN_PASSWORD = "entrando1"

# --- Default password for dummy/throwaway users in local RBAC seeding. ---
DEV_KITSU_DUMMY_PASSWORD = "entrar123"

# --- Local Kitsu Docker-Compose bootstrap secrets (written to .openstudio_infra/env). ---
DEV_KITSU_DB_PASSWORD = "Un53cur3Pa55w0rd"
DEV_KITSU_INDEXER_KEY = "Un53cur3Ma55t3rK3y"
DEV_KITSU_SECRET_KEY = "Op3nStud1oHubZ0uS3cr3tK3y2026V3ryS3cur3"
