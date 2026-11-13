"""Slate panels, gold numbers, orange only for actions.

Green, blue, yellow, and red are reserved for state. The same words are
used on the window, the orb, and the tray.
"""

from __future__ import annotations

STATE_COLORS = {
    "off": "#8b939e",
    "starting": "#e6b325",
    "on": "#3ddc86",
    "listening": "#3ddc86",
    "thinking": "#3ddc86",
    "speaking": "#3ddc86",
    "game": "#6ea2ff",
    "error": "#ff5d5d",
}

STATE_WORDS = {
    "off": "Off",
    "starting": "Working",
    "on": "On",
    "listening": "Listening",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "game": "Game",
    "error": "Needs you",
}

CAPTIONS = {
    "off": "Off",
    "starting": "Working",
    "on": "Hold to talk",
    "listening": "Listening",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "game": "Game",
    "error": "Needs you",
}

MAIN_QSS = """
QToolTip {
    background: #1b2436;
    color: #e7edf7;
    border: 1px solid #e3902f;
    padding: 6px 8px;
    font-size: 13px;
}
#appRoot, #appRoot QWidget {
    background-color: #0f1524;
    color: #e7edf7;
    font-size: 14px;
}
#appRoot QLabel { background: transparent; }
#appRoot #topbar, #appRoot #pinbar {
    background-color: #121a2b;
    border-bottom: 1px solid #243049;
}
#appRoot QPushButton {
    background-color: #243049;
    color: #e7edf7;
    border: 1px solid #31425e;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 14px;
}
#appRoot QPushButton:hover { border-color: #e3902f; }
#appRoot QPushButton:disabled { color: #6c7686; border-color: #2a3140; background-color: #171e2e; }
#appRoot QPushButton#nav {
    text-align: center;
    padding: 8px 12px;
    border: none;
    border-radius: 10px;
    background-color: transparent;
    color: #c5cedb;
    font-size: 14px;
}
#appRoot QPushButton#nav:hover { background-color: #1c2740; }
#appRoot QPushButton#nav:checked { background-color: #e3902f; color: #1a1206; font-weight: 600; }
#appRoot QPushButton#primary {
    background-color: #e3902f;
    border: none;
    color: #1a1206;
    font-weight: 600;
}
#appRoot QPushButton#danger {
    background-color: transparent;
    color: #ffb4b4;
    border: 1px solid #ff5d5d;
}
#appRoot QPushButton#choice {
    background-color: #1c2740;
    padding: 8px 14px;
}
#appRoot QPushButton#choice:checked {
    background-color: #e3902f;
    border-color: #e3902f;
    color: #1a1206;
}
#appRoot QFrame#card {
    background-color: #171f33;
    border: 1px solid #2a3854;
    border-radius: 16px;
}
#appRoot QLabel#title { font-size: 28px; font-weight: 700; color: #f4f7fb; }
#appRoot QLabel#word { font-size: 22px; font-weight: 700; color: #f4f7fb; }
#appRoot QLabel#gold { font-size: 28px; font-weight: 700; color: #e7c27a; }
#appRoot QLabel#section { font-size: 12px; color: #93a0b8; letter-spacing: 0.08em; }
#appRoot QLabel#hint { color: #93a0b8; font-size: 13px; }
#appRoot QLabel#bannerText { color: #f4f7fb; font-size: 14px; }
#appRoot QFrame#banner {
    background-color: #2a2212;
    border: 1px solid #e6b325;
    border-radius: 12px;
}
#appRoot QFrame#dangerBanner {
    background-color: #2a1518;
    border: 1px solid #ff5d5d;
    border-radius: 12px;
}
#appRoot QPlainTextEdit, #appRoot QListWidget, #appRoot QLineEdit, #appRoot QComboBox {
    background-color: #101826;
    color: #e7edf7;
    border: 1px solid #2a3854;
    border-radius: 10px;
    padding: 6px;
    selection-background-color: #e3902f;
    selection-color: #1a1206;
}
#appRoot QComboBox QAbstractItemView {
    background-color: #101826;
    color: #e7edf7;
    selection-background-color: #e3902f;
    selection-color: #1a1206;
}
#appRoot QCheckBox { font-size: 14px; spacing: 8px; background: transparent; }
#appRoot QSlider::groove:horizontal {
    height: 6px;
    background: #2a3854;
    border-radius: 3px;
}
#appRoot QSlider::handle:horizontal {
    background: #e3902f;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
#appRoot QProgressBar {
    background-color: #101826;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}
#appRoot QProgressBar::chunk { background-color: #e3902f; border-radius: 6px; }
#appRoot QScrollArea { border: none; background: transparent; }
#appRoot QScrollBar:vertical { background: transparent; width: 10px; }
#appRoot QScrollBar::handle:vertical { background: #2a3854; border-radius: 5px; }
"""

DIALOG_QSS = """
QDialog { background: #121a2b; color: #e7edf7; }
QLabel { color: #e7edf7; font-size: 15px; }
QPlainTextEdit, QListWidget, QLineEdit {
    background: #0f1524;
    color: #e7edf7;
    border: 1px solid #2a3854;
    border-radius: 8px;
    padding: 6px;
}
QPushButton {
    background: #243049;
    color: #e7edf7;
    border: 1px solid #31425e;
    border-radius: 10px;
    padding: 8px 14px;
}
QPushButton#primary { background: #e3902f; color: #1a1206; border: none; }
"""
