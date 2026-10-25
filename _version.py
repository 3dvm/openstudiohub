# =========================================================================================
# OPENSTUDIOHUB
# Module: _version.py
# Architectural role: Application version source of truth
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. All rights reserved.
# License: GNU General Public License v3.0 (GPLv3)
#
# Author: Ernesto Del Valle Macuare
# File version: 0.7.5
# =========================================================================================

# Tuple used by internal comparisons.
VERSION_INFO = (0, 7, 5)

# Semantic Versioning string (SemVer).
__version__ = ".".join(map(str, VERSION_INFO))
