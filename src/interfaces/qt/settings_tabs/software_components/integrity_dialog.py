# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/settings_tabs/software_components/integrity_dialog.py
# Architectural role: UI Dialog / Vault manifest integrity report
# =========================================================================================

"""Modal report for the vault manifest integrity audit.

Renders the findings produced by ``VaultIntegrityAuditor`` and exposes signals
for the manifest editor to apply the repairs it can (register downloaded
Blender versions, re-download missing assets, delete dead versions...).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class VaultIntegrityDialog(QDialog):
    apply_safe_fixes_requested = Signal()
    redownload_binary_requested = Signal(str)
    delete_version_requested = Signal(str)
    redownload_addons_requested = Signal()
    move_misplaced_requested = Signal()
    register_orphan_addons_requested = Signal(list)

    def __init__(self, parent, report, active_version: str = "") -> None:
        super().__init__(parent)
        self.report = report
        self.active_version = active_version
        self.setWindowTitle(self.tr("Vault Manifest Integrity"))
        self.resize(760, 660)
        self.setMinimumSize(560, 420)
        self.setModal(True)
        self.setObjectName("FloatingCard")
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 12)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(26, 22, 26, 10)
        self.content_layout.setSpacing(10)
        scroll.setWidget(content)

        root.addWidget(scroll, stretch=1)

        title = QLabel(self.tr("🩺 Vault Manifest Integrity"))
        title.setObjectName("H2Title")
        self.content_layout.addWidget(title)

        subtitle = QLabel(self.report.summary())
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.content_layout.addWidget(subtitle)

        self._render_report()

        buttons = QHBoxLayout()
        buttons.setContentsMargins(26, 4, 26, 0)

        self.btn_apply = QPushButton(self.tr("Apply Safe Fixes"))
        self.btn_apply.setObjectName("PrimaryButton")
        self.btn_apply.setFixedHeight(35)
        self.btn_apply.setEnabled(self._has_safe_fixes())
        self.btn_apply.clicked.connect(self._on_apply_safe_fixes)
        buttons.addWidget(self.btn_apply)

        self.btn_addons = QPushButton(self.tr("Re-download Missing Add-ons"))
        self.btn_addons.setObjectName("SecondaryButton")
        self.btn_addons.setFixedHeight(35)
        self.btn_addons.setEnabled(bool(self.report.missing_addon_files))
        self.btn_addons.clicked.connect(self.redownload_addons_requested.emit)
        buttons.addWidget(self.btn_addons)

        buttons.addStretch()

        self.btn_close = QPushButton(self.tr("Close"))
        self.btn_close.setObjectName("SecondaryButton")
        self.btn_close.setFixedHeight(35)
        self.btn_close.clicked.connect(self.accept)
        buttons.addWidget(self.btn_close)

        root.addLayout(buttons)

    def _has_safe_fixes(self) -> bool:
        return bool(self.report.unregistered_binaries or self.report.addon_version_mismatches)

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------
    def _add_section(self, title: str, color: str = "#F59E0B") -> None:
        label = QLabel(title)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 13px; margin-top: 12px;"
        )
        self.content_layout.addWidget(label)

    def _add_row(self, text: str, buttons=None, color: str = "#E2E8F0") -> None:
        frame = QFrame()
        frame.setStyleSheet("background-color: #1E293B; border-radius: 6px;")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {color}; font-size: 12px;")
        layout.addWidget(label, stretch=1)

        for text_btn, slot, object_name in buttons or []:
            btn = QPushButton(text_btn)
            btn.setObjectName(object_name)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        self.content_layout.addWidget(frame)

    def _render_report(self) -> None:
        report = self.report

        if not report.has_issues:
            ok = QLabel(self.tr("✓ The manifest matches the vault. Nothing to fix."))
            ok.setStyleSheet("color: #10B981; font-weight: bold; font-size: 13px;")
            self.content_layout.addWidget(ok)
            return

        if report.unregistered_binaries:
            self._add_section(
                self.tr("Downloaded Blender versions missing from the manifest "
                        "(fixable with Apply Safe Fixes):"),
                "#10B981",
            )
            for asset in report.unregistered_binaries:
                self._add_row(f"Blender {asset.version}  ·  {asset.filename}", color="#A7F3D0")

        if report.missing_binaries:
            self._add_section(
                self.tr("Manifest versions with no binary in the vault (re-download or delete):"),
                "#EF4444",
            )
            for version in report.missing_binaries:
                self._add_row(
                    f"Blender {version}  ·  no archive in blender_versions/",
                    buttons=[
                        (
                            self.tr("Re-download"),
                            lambda _, v=version: self.redownload_binary_requested.emit(v),
                            "SecondaryButton",
                        ),
                        (
                            self.tr("Delete version"),
                            lambda _, v=version: self._confirm_delete(v),
                            "SecondaryButton",
                        ),
                    ],
                    color="#FCA5A5",
                )

        if report.misplaced_binaries:
            self._add_section(
                self.tr("Archives stored at the vault root (should live in blender_versions/):"),
            )
            self._add_row(
                ", ".join(p.name for p in report.misplaced_binaries),
                buttons=[
                    (self.tr("Move to blender_versions/"), self.move_misplaced_requested.emit, "SecondaryButton"),
                ],
            )

        if report.missing_addon_files:
            self._add_section(
                self.tr("Manifest add-ons whose archive is missing from the vault:"),
                "#EF4444",
            )
            for version, name, path in report.missing_addon_files:
                detail = f"  ·  expected {path}" if path else ""
                self._add_row(f"[{version}] {name}{detail}", color="#FCA5A5")

        if report.addon_version_mismatches:
            self._add_section(
                self.tr("Add-on version mismatch (manifest vs archive) — fixed by Apply Safe Fixes:"),
                "#F59E0B",
            )
            for version, name, manifest_v, disk_v in report.addon_version_mismatches:
                self._add_row(
                    f"[{version}] {name}  ·  manifest {manifest_v} → archive {disk_v}"
                )

        if report.orphan_addons:
            self._add_section(
                self.tr("Archives not referenced by any manifest version:"),
                "#F59E0B",
            )
            register_buttons = []
            if self.active_version:
                register_buttons.append(
                    (
                        self.tr(f"Register to {self.active_version}"),
                        lambda: self.register_orphan_addons_requested.emit(
                            [asset.name for asset in report.orphan_addons]
                        ),
                        "SecondaryButton",
                    )
                )
            self._add_row(
                ", ".join(asset.filename for asset in report.orphan_addons),
                buttons=register_buttons,
            )

        if report.invalid_addon_files:
            self._add_section(
                self.tr("Archives that are not valid Blender add-ons:"),
                "#EF4444",
            )
            for asset in report.invalid_addon_files:
                self._add_row(asset.filename, color="#FCA5A5")

        if report.broken_requires:
            self._add_section(
                self.tr("Add-ons with unsatisfied 'requires' in the same version:"),
                "#F59E0B",
            )
            for version, name, target in report.broken_requires:
                self._add_row(f"[{version}] {name}  requires  {target}")

        if report.missing_templates:
            self._add_section(self.tr("Manifest templates not found on disk:"), "#EF4444")
            for version, name in report.missing_templates:
                self._add_row(f"[{version}] {name}", color="#FCA5A5")

        if report.orphan_templates:
            self._add_section(self.tr("Template folders not referenced by any manifest version:"))
            self._add_row(", ".join(report.orphan_templates))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _on_apply_safe_fixes(self) -> None:
        self.apply_safe_fixes_requested.emit()
        self.accept()

    def _confirm_delete(self, version: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            self.tr("Delete Blender version"),
            self.tr(
                f"Remove Blender {version} from the manifest? "
                "Projects pinned to this version will no longer be creatable."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.delete_version_requested.emit(version)
            self.accept()
