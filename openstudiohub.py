# =========================================================================================
# OPENSTUDIOHUB
# Module: openstudiohub.py
# Architectural role: Main App Root / Initial Orchestrator (PySide6)
# =========================================================================================

"""Main entry point of OpenStudio Hub.

Initializes the native Qt environment, builds the composition root, and routes
between the Login view and the role-based dashboards.
"""

from pathlib import Path
import os
import sys
import urllib.parse

from _version import __version__

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox, QStackedWidget

from src.domain.identity.value_objects import Role
from src.infrastructure.kitsu_manager import KitsuManager
from src.infrastructure.watchtower_launcher import WatchtowerLauncher
from src.interfaces.qt.components.vcs_credentials_dialog import VcsCredentialsDialog
from src.interfaces.qt.composition import AppContext
from src.interfaces.qt.shell.web_context_view import WebContextView
from src.interfaces.qt.viewmodels.artist_viewmodel import ArtistViewModel
from src.interfaces.qt.viewmodels.blend_builder_viewmodel import BlendBuilderViewModel
from src.interfaces.qt.viewmodels.infrastructure_viewmodel import InfrastructureViewModel
from src.interfaces.qt.viewmodels.login_viewmodel import LoginViewModel
from src.interfaces.qt.viewmodels.new_project_viewmodel import NewProjectViewModel
from src.interfaces.qt.viewmodels.project_list_viewmodel import ProjectListViewModel
from src.interfaces.qt.viewmodels.settings_viewmodel import SettingsViewModel
from src.interfaces.qt.views.artist_view import ViewArtist
from src.interfaces.qt.views.login_view import ViewLogin
from src.interfaces.qt.views.new_project_dialog import NewProjectDialog
from src.interfaces.qt.views.pm_view import ViewPM
from src.interfaces.qt.views.repair_project_dialog import RepairProjectDialog
from src.interfaces.qt.views.td_view import ViewTD


def _select_dashboard(role: Role, position: str) -> str:
    """Map an authenticated role/position to a dashboard ('td' | 'pm' | 'artist' | 'editor')."""
    if role is Role.TD:
        return "td"
    if role is Role.MANAGER:
        return "artist" if position == "lead" else "pm"
    return "artist"


if getattr(sys, "frozen", False):
    os.chdir(sys._MEIPASS if hasattr(sys, "_MEIPASS") else os.path.dirname(sys.executable))


class OpenStudioHub(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(f"OpenStudioHub - v{__version__}")
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)
        self.setWindowIcon(QIcon("assets/openstudiohub.ico"))

        self.blender_instances = 0
        self._repair_dialogs: list = []
        self._new_project_dialogs: list = []

        self.ctx = AppContext(Path("settings.json"), credential_prompt=self._prompt_vcs_credentials)

        self.show_login()

    # ------------------------------------------------------------------
    # VCS credential gate
    # ------------------------------------------------------------------
    def _prompt_vcs_credentials(self) -> tuple[str, str] | None:
        """Show the modal VCS credentials prompt; return the pair or None on cancel."""
        default_user, _ = self.ctx.credential_vault.get_svn_credentials()
        if not default_user and self.ctx.auth_service.current_user is not None:
            default_user = self.ctx.auth_service.current_user.email

        dialog = VcsCredentialsDialog(self, default_user or "")
        if dialog.exec() == QDialog.Accepted:
            return dialog.credentials()
        return None

    # ------------------------------------------------------------------
    # Process guardian
    # ------------------------------------------------------------------
    def register_instance(self, active: bool) -> None:
        if active:
            self.blender_instances += 1
        else:
            self.blender_instances = max(0, self.blender_instances - 1)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.blender_instances > 0:
            message = self.tr(
                "You have {0} 3D environment session(s) open.\n\n"
                "Please close the program first to release the master files on the server (SVN Unlock) "
                "and avoid production corruption."
            ).format(self.blender_instances)

            QMessageBox.warning(self, self.tr("Blocked Operation"), message)
            event.ignore()
        else:
            if self.ctx.auth_service.access_token():
                self.ctx.auth_service.logout()
            self.ctx.credential_vault.clear()
            event.accept()

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    def show_login(self) -> None:
        self.setWindowTitle(f"OpenStudio Hub - v{__version__}")

        login_vm = LoginViewModel(
            self.ctx.auth_service,
            self.ctx.credential_vault,
            self.ctx.config_factory,
        )
        login_vm.login_succeeded.connect(self.show_dashboard)

        view_login = ViewLogin(parent=self, viewmodel=login_vm)
        self.setCentralWidget(view_login)

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------
    def show_dashboard(self) -> None:
        studio_name = self.ctx.config_factory.get_studio_name() or "OpenStudio"
        self.setWindowTitle(f"{studio_name} Hub - v{__version__}")

        self._retire_previous_dashboard()

        role = self.ctx.auth_service.current_role()
        user = self.ctx.auth_service.current_user
        position = user.position if user else ""
        nas_dir = self.ctx.config_factory.get_workspace_root()

        dashboard = _select_dashboard(role, position)
        if dashboard == "td":
            self.current_view = self._build_td_view(nas_dir)
        elif dashboard == "pm":
            self.current_view = self._build_pm_view(nas_dir)
        else:
            self.current_view = self._build_artist_view(nas_dir)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.current_view)

        self.web_context = WebContextView(self)
        self.web_context.back_requested.connect(self.close_kitsu)
        self.view_stack.addWidget(self.web_context)

        self.setCentralWidget(self.view_stack)

    def _retire_previous_dashboard(self) -> None:
        """Keep the outgoing dashboard referenced so its QThreads finish gracefully.

        Replacing the central widget would otherwise drop the last Python
        reference to the previous dashboard (and its ViewModels/workers), letting
        the garbage collector destroy a running QThread and abort the process.
        """
        view = getattr(self, "current_view", None)
        if view is None:
            return

        if not hasattr(self, "_retired_views"):
            self._retired_views = []
        self._retired_views.append(view)

        try:
            view.deleteLater()
        except RuntimeError:
            pass

    def _build_project_list_vm(self, nas_dir, read_vcs_credentials: bool) -> ProjectListViewModel:
        return ProjectListViewModel(
            production_service=self.ctx.production_service,
            auth_service=self.ctx.auth_service,
            audit_service=self.ctx.audit_service,
            config_factory=self.ctx.config_factory,
            installation_service=self.ctx.installation_service,
            read_vcs_credentials=read_vcs_credentials,
            nas_dir=nas_dir,
            open_kitsu_callback=self.open_kitsu,
            open_watchtower_callback=lambda project_dir: self.open_watchtower(project_dir),
            instance_lock_callback=self.register_instance,
            status_sink=self.ctx.status_sink,
            credential_vault=self.ctx.credential_vault,
            vcs_prompt=self._prompt_vcs_credentials,
        )

    def _build_td_view(self, nas_dir):
        project_list_vm = self._build_project_list_vm(nas_dir, True)
        infrastructure_vm = InfrastructureViewModel(
            self.ctx.config_factory,
            self.ctx.production_service,
            self.ctx.status_sink,
            credential_vault=self.ctx.credential_vault,
        )
        settings_vm = SettingsViewModel(
            self.ctx.config_factory,
            self.ctx.vault_service,
            self.ctx.status_sink,
            credential_vault=self.ctx.credential_vault,
        )

        return ViewTD(
            parent=self,
            project_list_vm=project_list_vm,
            infrastructure_vm=infrastructure_vm,
            settings_vm=settings_vm,
            audit_vm=self.ctx.audit_viewmodel,
            repair_vm=self.ctx.repair_viewmodel,
            auth_service=self.ctx.auth_service,
            config_factory=self.ctx.config_factory,
            production_service=self.ctx.production_service,
            vault_service=self.ctx.vault_service,
            on_logout=self.ejecutar_logout,
            on_new_project_callback=self._open_new_project_dialog,
            on_repair_callback=self._open_repair_dialog,
            status_sink=self.ctx.status_sink,
        )

    def _build_pm_view(self, nas_dir):
        project_list_vm = self._build_project_list_vm(nas_dir, False)
        blend_builder_vm = BlendBuilderViewModel(
            self.ctx.production_service,
            self.ctx.config_factory,
            self.ctx.credential_vault,
            self.ctx.status_sink,
            vcs_prompt=self._prompt_vcs_credentials,
            installation_service=self.ctx.installation_service,
            user_role=self.ctx.auth_service.current_role().value,
        )

        return ViewPM(
            parent=self,
            project_list_vm=project_list_vm,
            blend_builder_vm=blend_builder_vm,
            audit_vm=self.ctx.audit_viewmodel,
            repair_vm=self.ctx.repair_viewmodel,
            auth_service=self.ctx.auth_service,
            config_factory=self.ctx.config_factory,
            on_logout=self.ejecutar_logout,
            status_sink=self.ctx.status_sink,
            credential_vault=self.ctx.credential_vault,
        )

    def _build_artist_view(self, nas_dir):
        artist_vm = ArtistViewModel(
            production_service=self.ctx.production_service,
            auth_service=self.ctx.auth_service,
            credential_vault=self.ctx.credential_vault,
            config_factory=self.ctx.config_factory,
            installation_service=self.ctx.installation_service,
            register_instance=self.register_instance,
            status_sink=self.ctx.status_sink,
            vcs_prompt=self._prompt_vcs_credentials,
        )

        return ViewArtist(
            parent=self,
            viewmodel=artist_vm,
            auth_service=self.ctx.auth_service,
            config_factory=self.ctx.config_factory,
            on_logout=self.ejecutar_logout,
            status_sink=self.ctx.status_sink,
        )

    def _open_new_project_dialog(self) -> None:
        vm = NewProjectViewModel(
            self.ctx.config_factory,
            self.ctx.production_service,
            self.ctx.vault_service,
            credential_vault=self.ctx.credential_vault,
            vcs_prompt=self._prompt_vcs_credentials,
        )
        dialog = NewProjectDialog(self, vm, on_success_callback=self._on_project_created)
        # Keep a strong Python reference so the dialog (and its ViewModel's
        # workers) cannot be garbage-collected while the thread is running.
        self._new_project_dialogs.append(dialog)
        dialog.finished.connect(lambda _result, d=dialog: self._release_new_project_dialog(d))
        dialog.show()

    def _release_new_project_dialog(self, dialog) -> None:
        if dialog in self._new_project_dialogs:
            self._new_project_dialogs.remove(dialog)
        dialog.try_safe_delete()

    def _open_repair_dialog(self, project_name: str, project_id: str, error_code: str) -> None:
        dialog = RepairProjectDialog(
            parent=self,
            repair_vm=self.ctx.repair_viewmodel,
            production_service=self.ctx.production_service,
            vault_service=self.ctx.vault_service,
            config_factory=self.ctx.config_factory,
            project_name=project_name,
            project_id=project_id,
            error_code=error_code,
            on_success_callback=self._on_project_created,
        )
        # Keep a strong Python reference: a parented dialog whose wrapper is
        # garbage-collected releases its workers, which then get destroyed while
        # running ("QThread: Destroyed while thread is still running").
        self._repair_dialogs.append(dialog)
        dialog.finished.connect(lambda _result, d=dialog: self._release_repair_dialog(d))
        dialog.show()

    def _release_repair_dialog(self, dialog) -> None:
        if dialog in self._repair_dialogs:
            self._repair_dialogs.remove(dialog)
        dialog.try_safe_delete()

    def _on_project_created(self) -> None:
        view = getattr(self, "current_view", None)
        project_list = getattr(view, "projects_view", None)
        if project_list is not None:
            project_list.refresh()

    # ------------------------------------------------------------------
    # Web context layer (Kitsu / Watchtower)
    # ------------------------------------------------------------------
    def open_kitsu(self, target_url: str | None = None) -> None:
        kitsu_url = self.ctx.config_factory.get_kitsu_api_url()
        if kitsu_url.endswith("/api"):
            kitsu_url = kitsu_url[:-4]

        if not target_url:
            target_url = f"{kitsu_url}/news-feed"

        if False:  # SSO still needs a fix first for embeded opening
            parsed_url = urllib.parse.urlparse(kitsu_url)
            allowed_hosts = [parsed_url.hostname, "localhost", "127.0.0.1"]

            token = self.ctx.auth_service.access_token()
            self.web_context.load_context(target_url, "Kitsu", allowed_hosts, sso_token=token)
            self.view_stack.setCurrentWidget(self.web_context)
        else:
            QDesktopServices.openUrl(QUrl(target_url))

    def close_kitsu(self) -> None:
        self.view_stack.setCurrentWidget(self.current_view)
        print("[OpenStudioHub] Returned from Kitsu.")

    def open_watchtower(self, project_root_path: Path, project_id: str = "") -> None:
        if project_id:
            kitsu_mgr = KitsuManager()
            if not kitsu_mgr.check_edit_preview_exists(project_id):
                QMessageBox.warning(
                    self,
                    "Edit Not Rendered",
                    "There is no rendered video for the Edit in Kitsu.\n\n"
                    "Watchtower requires the main edit file to work.\n\n"
                    "Please render and push the Master Edit from Blender before opening Watchtower.",
                )
                return

        kitsu_url = self.ctx.config_factory.get_kitsu_api_url()
        kitsu_user, kitsu_pwd = self.ctx.credential_vault.get_kitsu_credentials()

        self.wt_launcher = WatchtowerLauncher(
            project_root_path,
            kitsu_url,
            kitsu_user,
            kitsu_pwd,
            lambda msg, color: print(f"[Watchtower] {msg}"),
            self.ctx.config_factory,
        )
        self.wt_launcher.server_ready.connect(self._on_watchtower_ready)
        self.wt_launcher.launch()

    def _on_watchtower_ready(self, url: str) -> None:
        self.web_context.load_context(url, "Watchtower", ["localhost", "127.0.0.1"])
        self.view_stack.setCurrentWidget(self.web_context)

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------
    def ejecutar_logout(self) -> None:
        if self.blender_instances > 0:
            self.close()
            return

        self.ctx.auth_service.logout()
        self.ctx.credential_vault.clear()
        self.show_login()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    theme_path = Path("macuare_theme.qss")
    if theme_path.exists():
        try:
            with open(theme_path, "r", encoding="utf-8") as handle:
                app.setStyleSheet(handle.read())
            print("[OPENSTUDIO HUB] ✓ Corporate QSS theme loaded successfully.")
        except Exception as error:  # noqa: BLE001
            print(f"[OPENSTUDIO HUB] ❌ Error reading QSS file: {error}")
    else:
        print("[OPENSTUDIO HUB] ⚠️ WARNING: 'macuare_theme.qss' not found. Starting with OS native theme.")

    window = OpenStudioHub()
    window.show()
    sys.exit(app.exec())
