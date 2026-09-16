# =========================================================================================
# OPENSTUDIOHUB
# Module: src/interfaces/qt/widgets/addon_config_panel.py
# Architectural role: UI Widget / declarative per-add-on configuration form
# =========================================================================================

"""A small schema-driven form used to edit an add-on's static settings.

The vault manifest declares a ``config_schema`` per add-on; this widget renders
the matching inputs and returns a plain ``settings`` dict. It stays completely
add-on agnostic: new fields only require manifest changes.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)


class AddonConfigPanel(QWidget):
    def __init__(self, schema: dict | None, defaults: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.schema = schema or {}
        self._defaults = defaults or {}
        self._widgets: dict[str, tuple[QWidget, str]] = {}

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 2, 10, 8)
        layout.setSpacing(4)

        for field_name, raw_spec in self.schema.items():
            spec = raw_spec or {}
            field_type = spec.get("type", "str")
            default = self._defaults.get(field_name, spec.get("default"))

            widget = self._build_widget(field_type, default)
            widget.setEnabled(False)

            label = QLabel(spec.get("label", field_name))
            label.setStyleSheet("color: #94A3B8; font-size: 11px;")
            layout.addRow(label, widget)
            self._widgets[field_name] = (widget, field_type)

        self.setVisible(bool(self.schema))

    @staticmethod
    def _build_widget(field_type: str, default) -> QWidget:
        if field_type == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(default))
            return widget
        if field_type == "int":
            widget = QSpinBox()
            widget.setRange(-1000000, 1000000)
            widget.setValue(int(default) if default is not None else 0)
            return widget
        widget = QLineEdit()
        widget.setText("" if default is None else str(default))
        return widget

    def set_editable(self, editable: bool) -> None:
        for widget, _ in self._widgets.values():
            widget.setEnabled(editable)

    def values(self) -> dict:
        result: dict = {}
        for field_name, (widget, field_type) in self._widgets.items():
            if field_type == "bool":
                result[field_name] = bool(widget.isChecked())
            elif field_type == "int":
                result[field_name] = int(widget.value())
            else:
                result[field_name] = widget.text().strip()
        return result
