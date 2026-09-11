# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/infrastructure_widget.py
# Architectural role: UI Widget / Infrastructure Controller
# =========================================================================================

"""Studio infrastructure panel.

Renders the service cards and forwards lifecycle commands to the
``InfrastructureViewModel``.
"""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.interfaces.qt.viewmodels.infrastructure_viewmodel import InfrastructureViewModel


class InfrastructureWidget(QFrame):
    def __init__(self, parent, viewmodel: InfrastructureViewModel, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.vm = viewmodel

        self.setObjectName("InfrastructureBase")
        self._build_ui()
        self.vm.operation_finished.connect(self._on_operation_finished)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        header = QLabel(self.tr("Studio Infrastructure (Zero-Config Environments)"))
        header.setStyleSheet("color: #F8FAFC; font-size: 20px; font-weight: bold;")
        layout.addWidget(header)

        desc = QLabel(self.tr("Deploy local instances of Subversion and Kitsu for testing and development. Requires Docker installed and running."))
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        grid = QGridLayout()
        grid.setSpacing(20)

        svn_card = self._build_service_card(
            title="Local VCS Server (SVN)",
            desc=self.tr("Centralized version control system for binary assets and scenes."),
            port="3690",
            start_callback=self.vm.deploy_svn,
            stop_callback=self.vm.stop_svn,
        )
        grid.addWidget(svn_card, 0, 0)

        kitsu_card = self._build_kitsu_service_card()
        grid.addWidget(kitsu_card, 0, 1)

        layout.addLayout(grid)
        layout.addStretch()

    def _build_service_card(self, title: str, desc: str, port: str, start_callback, stop_callback) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_title)

        lbl_desc = QLabel(desc)
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        lbl_desc.setWordWrap(True)
        c_layout.addWidget(lbl_desc)

        lbl_port = QLabel(f"Port: {port}")
        lbl_port.setStyleSheet("color: #3B82F6; font-size: 11px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_port)

        c_layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_start = QPushButton(self.tr("Deploy & Start"))
        btn_start.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_start.clicked.connect(start_callback)

        btn_stop = QPushButton(self.tr("Stop & Destroy"))
        btn_stop.setStyleSheet("""
            QPushButton { background-color: #EF4444; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #DC2626; }
        """)
        btn_stop.clicked.connect(stop_callback)

        btn_layout.addWidget(btn_start)
        btn_layout.addWidget(btn_stop)

        c_layout.addLayout(btn_layout)
        return card

    def _build_kitsu_service_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: #1E293B; border-radius: 12px; border: 1px solid #334155; }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)
        c_layout.setSpacing(10)

        lbl_title = QLabel("Production Tracker (Kitsu 1.0+)")
        lbl_title.setStyleSheet("color: #F8FAFC; font-size: 16px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_title)

        lbl_desc = QLabel(self.tr("Database, API, and Web Frontend for Shot and Asset management."))
        lbl_desc.setStyleSheet("color: #94A3B8; font-size: 12px; border: none;")
        lbl_desc.setWordWrap(True)
        c_layout.addWidget(lbl_desc)

        lbl_port = QLabel("Port: 8080")
        lbl_port.setStyleSheet("color: #3B82F6; font-size: 11px; font-weight: bold; border: none;")
        c_layout.addWidget(lbl_port)

        c_layout.addStretch()

        btn_layout1 = QHBoxLayout()
        btn_start = QPushButton(self.tr("Deploy & Start"))
        btn_start.setStyleSheet("""
            QPushButton { background-color: #10B981; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #059669; }
        """)
        btn_start.clicked.connect(self.vm.deploy_kitsu)

        btn_stop = QPushButton(self.tr("Stop & Destroy"))
        btn_stop.setStyleSheet("""
            QPushButton { background-color: #EF4444; color: white; border-radius: 6px; padding: 8px; font-weight: bold; }
            QPushButton:hover { background-color: #DC2626; }
        """)
        btn_stop.clicked.connect(self.vm.stop_kitsu)
        btn_layout1.addWidget(btn_start)
        btn_layout1.addWidget(btn_stop)

        btn_layout2 = QHBoxLayout()
        btn_seed_admin = QPushButton(self.tr("1. Create Admin Account"))
        btn_seed_admin.setToolTip("Runs 'zou create-admin' inside the container.")
        btn_seed_admin.setStyleSheet("""
            QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_seed_admin.clicked.connect(lambda: self.vm.run_seeder("admin"))

        btn_seed_dummy = QPushButton(self.tr("2. Seed Dummy Team"))
        btn_seed_dummy.setToolTip("Injects PM, TD and Artist via the Gazu API.")
        btn_seed_dummy.setStyleSheet("""
            QPushButton { background-color: #334155; color: white; border-radius: 6px; padding: 8px; font-weight: bold; font-size: 11px; }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_seed_dummy.clicked.connect(lambda: self.vm.run_seeder("dummy"))
        btn_layout2.addWidget(btn_seed_admin)
        btn_layout2.addWidget(btn_seed_dummy)

        c_layout.addLayout(btn_layout1)
        c_layout.addLayout(btn_layout2)

        return card

    def _on_operation_finished(self, success: bool, message: str) -> None:
        if not success:
            QMessageBox.critical(self, self.tr("Infrastructure Error"), message)
