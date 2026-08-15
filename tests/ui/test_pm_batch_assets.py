# =========================================================================================
# OPENSTUDIOHUB
# Módulo: tests/ui/test_pm_batch_assets.py
# E2E test for creating assets at the start of the project
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 0.1.0
# =========================================================================================

from PySide6.QtCore import Qt

from ui import view_pm

class DummyConfigFactory:
    def get_studio_name(self):
        return "Testing Studio"
    def get_workspace_root(self):
        return "/home/macuare/openstudio_projects/01_sample_project/"

def test_pm_asset_creation(qtbot):

    # PM logs in

    dummy_config = DummyConfigFactory()

    active_view = view_pm.ViewPM(None, None, dummy_config, None)

    qtbot.addWidget(active_view)
    # PM clicks on the wizard starter of the project that he/she needs to work on


    # PM clicks on asset generation tab

    # PM generates the pending asset tasks files.

    # PM sees the confirmation of the files generated for each task showing the new states of the tasks.

    pass
