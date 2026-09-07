"""View package for the Qt interface (thin Views bound to ViewModels)."""

from src.interfaces.qt.views.login_view import ViewLogin
from src.interfaces.qt.views.artist_view import ViewArtist
from src.interfaces.qt.views.pm_view import ViewPM
from src.interfaces.qt.views.td_view import ViewTD
from src.interfaces.qt.views.new_project_dialog import NewProjectDialog

__all__ = ["ViewLogin", "ViewArtist", "ViewPM", "ViewTD", "NewProjectDialog"]
