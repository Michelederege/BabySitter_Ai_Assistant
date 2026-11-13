"""Tabs that are visible so you can see the map, but not built yet."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SoonPage(QWidget):
    def __init__(self, title: str, phase: str, body: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        heading = QLabel(title)
        heading.setObjectName("title")
        when = QLabel(phase)
        when.setObjectName("section")
        text = QLabel(body)
        text.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(when)
        layout.addWidget(text)
        layout.addStretch(1)
