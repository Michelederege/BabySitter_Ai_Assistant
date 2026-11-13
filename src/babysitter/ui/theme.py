"""Colors and type for the dark control-center look.

One accent color (teal). State colors match the orb: grey off, yellow
starting, green on, blue game mode, red when something needs you.
"""

from __future__ import annotations

STATE_COLORS = {
    "off": "#8b939e",
    "starting": "#e6b325",
    "on": "#3ddc86",
    "game": "#7aa2ff",
    "error": "#ff5d5d",
}

STATE_WORDS = {
    "off": "OFF",
    "starting": "WAIT",
    "on": "ON",
    "game": "GAME",
    "error": "ERROR",
}

CAPTIONS = {
    "off": "Off",
    "starting": "Working",
    "on": "On",
    "game": "Game mode",
    "error": "Needs attention",
}

MAIN_QSS = """
QToolTip {
    background: #1b212c;
    color: #e8eef7;
    border: 1px solid #2dd4bf;
    padding: 6px 8px;
    font-size: 13px;
}
/* Qt does not hand a parent's color down to child widgets, so this
   rule paints the whole window. More specific rules below override it. */
#appRoot, #appRoot QWidget {
    background-color: #0c0e12;
    color: #e8eef7;
}
#appRoot QLabel {
    background: transparent;
}
#appRoot #sidebar {
    background-color: #10141b;
    border-right: 1px solid #242b38;
}
#appRoot QPushButton {
    background-color: #1c2430;
    color: #e8eef7;
    border: 1px solid #314056;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 14px;
}
#appRoot QPushButton:hover { border-color: #2dd4bf; }
#appRoot QPushButton:disabled { color: #6c7686; border-color: #2a3140; background-color: #161b24; }
#appRoot QPushButton#nav {
    text-align: left;
    padding: 12px 14px;
    border: none;
    border-radius: 10px;
    background-color: transparent;
    color: #c5cedb;
    font-size: 15px;
}
#appRoot QPushButton#nav:hover { background-color: #1a2130; }
#appRoot QPushButton#nav:checked { background-color: #132924; color: #2dd4bf; }
#appRoot QPushButton#nav:disabled { color: #66707f; }
#appRoot QPushButton#primary {
    background-color: #145e52;
    border-color: #2dd4bf;
    color: #f3fffc;
    font-weight: 600;
}
#appRoot QPushButton#choice {
    background-color: #1c2430;
    padding: 10px 12px;
}
#appRoot QPushButton#choice:checked {
    background-color: #132924;
    border-color: #2dd4bf;
    color: #d9fff6;
}
#appRoot QFrame#card {
    background-color: #151a22;
    border: 1px solid #2a3344;
    border-radius: 16px;
}
#appRoot QLabel#title { font-size: 28px; font-weight: 700; color: #f4f7fb; }
#appRoot QLabel#section { font-size: 13px; color: #9aa6b8; }
#appRoot QLabel#hint { color: #9aa6b8; font-size: 14px; }
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
    background-color: #10151c;
    color: #e8eef7;
    border: 1px solid #2a3344;
    border-radius: 10px;
    padding: 6px;
    selection-background-color: #145e52;
}
#appRoot QComboBox QAbstractItemView {
    background-color: #10151c;
    color: #e8eef7;
    selection-background-color: #145e52;
}
#appRoot QScrollArea { border: none; background: transparent; }
#appRoot QCheckBox { font-size: 15px; spacing: 8px; background: transparent; }
#appRoot QProgressBar {
    background-color: #10151c;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: transparent;
}
#appRoot QProgressBar::chunk { background-color: #2dd4bf; border-radius: 6px; }
#appRoot QScrollBar:vertical { background: transparent; width: 10px; }
#appRoot QScrollBar::handle:vertical { background: #2a3344; border-radius: 5px; }
"""

DIALOG_QSS = """
QDialog { background: #12161d; color: #e8eef7; }
QLabel { color: #e8eef7; font-size: 15px; }
QPlainTextEdit {
    background: #0c0e12;
    color: #e8eef7;
    border: 1px solid #2a3344;
    border-radius: 8px;
}
QPushButton {
    background: #1c2430;
    color: #e8eef7;
    border: 1px solid #314056;
    border-radius: 10px;
    padding: 8px 14px;
}
QPushButton#primary { background: #145e52; border-color: #2dd4bf; }
QListWidget, QLineEdit {
    background: #0c0e12;
    color: #e8eef7;
    border: 1px solid #2a3344;
    border-radius: 8px;
    padding: 6px;
}
"""
