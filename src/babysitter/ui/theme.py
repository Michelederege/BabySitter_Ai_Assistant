"""The BabySitter v2 look: slate panels, gold numbers, orange only for actions.

Green, blue, yellow, and red are reserved for state. The same words are
used on the window, the frog orb, and the tray. Colors and sizes follow
the design package (babysitter-ui-v2/theme/tokens.json).
"""

from __future__ import annotations

from babysitter.paths import asset_path

STATE_COLORS = {
    "off": "#b9c1d3",
    "starting": "#f2c14e",
    "on": "#62d68e",
    "listening": "#62d68e",
    "thinking": "#62d68e",
    "speaking": "#62d68e",
    "game": "#86b6ff",
    "error": "#ff8a8a",
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
    "on": "On",
    "listening": "Listening",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "game": "Game",
    "error": "Needs you",
}

# The frog sprite strip that plays for each internal state.
ORB_SPRITES = {
    "off": "off",
    "starting": "working",
    "on": "on",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
    "game": "game",
    "error": "needs",
}

# States whose pill text is dark ink on the bright state color.
DARK_INK_STATES = {"starting", "on", "listening", "thinking", "speaking"}


def apply_fonts(app) -> None:
    """Load Inter, Space Grotesk, and JetBrains Mono from the assets folder.

    Missing font files are skipped quietly; Qt then falls back to the
    system font named in the stylesheet's font-family lists.
    """
    from PySide6.QtGui import QFontDatabase

    for name in ("Inter.ttf", "SpaceGrotesk.ttf", "JetBrainsMono.ttf"):
        path = asset_path("fonts") / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))


MAIN_QSS = """
QToolTip {
    background: #12172a;
    color: #ffffff;
    border: 1px solid #3b4566;
    padding: 6px 9px;
    border-radius: 6px;
    font-size: 13px;
}
#appRoot, #appRoot QWidget {
    background-color: #202840;
    color: #e8ecf4;
    font-size: 14px;
}
#appRoot QLabel { background: transparent; }

/* ---------- custom title bar ---------- */
#appRoot #titlebar {
    background-color: #1a2136;
    border-bottom: 1px solid #38436a;
}
#appRoot #titlebar QLabel { background: transparent; }
#appRoot QLabel#appName {
    font-family: "Space Grotesk";
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
}
#appRoot QPushButton#windowButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    color: #c6cddc;
    padding: 4px 12px;
    font-weight: 600;
    font-size: 13px;
}
#appRoot QPushButton#windowButton:hover { background: #38436a; color: #ffffff; }
#appRoot QPushButton#windowButton:checked { background: #f5a54a; color: #2a1606; }
#appRoot QPushButton#closeButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    color: #c6cddc;
    padding: 4px 14px;
    font-weight: 600;
    font-size: 15px;
}
#appRoot QPushButton#closeButton:hover { background: #8a3e48; color: #ffffff; }

/* ---------- top bar and rail ---------- */
#appRoot #topbar {
    background-color: #1a2136;
    border-bottom: 1px solid #38436a;
}
#appRoot #rail {
    background-color: #252d47;
    border-right: 1px solid #38436a;
}
#appRoot QLabel#railGroup {
    color: #a3aec5;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 10px 10px 2px 10px;
}
#appRoot QPushButton#nav {
    text-align: left;
    padding: 8px 12px;
    border: none;
    border-radius: 6px;
    background-color: transparent;
    color: #c6cddc;
    font-size: 14px;
}
#appRoot QPushButton#nav:hover { background-color: #38436a; color: #ffffff; }
#appRoot QPushButton#nav:checked {
    background-color: #f5a54a;
    color: #2a1606;
    font-weight: 700;
}

/* ---------- buttons ---------- */
#appRoot QPushButton {
    background-color: #38436a;
    color: #e8ecf4;
    border: none;
    border-radius: 6px;
    padding: 8px 13px;
    font-weight: 600;
    font-size: 13px;
}
#appRoot QPushButton:hover { background-color: #4a5680; color: #ffffff; }
#appRoot QPushButton:pressed { background-color: #56638a; }
#appRoot QPushButton:disabled {
    color: rgba(232, 236, 244, 0.4);
    background-color: rgba(56, 67, 106, 0.4);
}
#appRoot QPushButton:focus { border: 2px solid #f6b977; }
#appRoot QPushButton#primary {
    background-color: #f5a54a;
    color: #2a1606;
}
#appRoot QPushButton#primary:hover { background-color: #f8b866; }
#appRoot QPushButton#primary:disabled {
    background-color: rgba(245, 165, 74, 0.35);
    color: rgba(42, 22, 6, 0.6);
}
#appRoot QWidget#heroBanner,
#appRoot QWidget#heroOverlay,
#appRoot QWidget#heroFrog,
#appRoot QWidget#heroBody {
    background: transparent;
}
#appRoot QPushButton#heroCorner {
    background-color: rgba(20, 26, 44, 0.62);
    color: #e8ecf4;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 6px 11px;
    font-size: 12px;
    font-weight: 600;
}
#appRoot QPushButton#heroCorner:hover {
    background-color: rgba(56, 67, 106, 0.85);
    color: #ffffff;
}
#appRoot QPushButton#heroCorner:focus { border: 2px solid #f6b977; }
#appRoot QPushButton#danger {
    background-color: transparent;
    color: #ffd0d0;
    border: 1px solid #ff8a8a;
}
#appRoot QPushButton#danger:hover { background-color: #3d2730; }
#appRoot QPushButton#choice {
    background-color: #38436a;
    color: #dfe4ee;
    border-radius: 5px;
    font-weight: 700;
}
#appRoot QPushButton#choice:checked { background-color: #f5a54a; color: #2a1606; }

/* ---------- panels, cards, and words ---------- */
#appRoot QFrame#card {
    background-color: #2a3350;
    border: 1px solid #38436a;
    border-radius: 8px;
}
#appRoot QFrame#innerCard {
    background-color: #323c5e;
    border: 1px solid #3e4a72;
    border-radius: 7px;
}
#appRoot QLabel#title { font-size: 24px; font-weight: 700; color: #ffffff; }
#appRoot QLabel#word { font-size: 20px; font-weight: 700; color: #ffffff; }
#appRoot QLabel#gold { font-size: 22px; font-weight: 700; color: #ffe2bd; }
#appRoot QLabel#section {
    font-size: 11px;
    color: #a3aec5;
    font-weight: 700;
    letter-spacing: 1px;
}
#appRoot QLabel#hint { color: #a3aec5; font-size: 13px; }
#appRoot QLabel#mono { font-family: "JetBrains Mono"; font-size: 12px; }
#appRoot QLabel#spoken { font-size: 17px; font-weight: 600; color: #ffffff; }
#appRoot QLabel#bannerText { color: #e8ecf4; font-size: 14px; }
#appRoot QFrame#banner {
    background-color: #3b3426;
    border: 1px solid #6b5426;
    border-radius: 8px;
}
#appRoot QFrame#dangerBanner {
    background-color: #3d2730;
    border: 1px solid #8a3e48;
    border-radius: 8px;
}
#appRoot QFrame#offerBanner {
    background-color: #323c5e;
    border: 1px solid #f5a54a;
    border-radius: 8px;
}
#appRoot QFrame#followupBar {
    background-color: #2c3a36;
    border: 1px solid #3f6b55;
    border-radius: 8px;
}

/* ---------- inputs ---------- */
#appRoot QPlainTextEdit, #appRoot QListWidget, #appRoot QLineEdit, #appRoot QComboBox {
    background-color: #1f2740;
    color: #e8ecf4;
    border: 1px solid #4a5680;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #f5a54a;
    selection-color: #2a1606;
}
#appRoot QLineEdit:focus, #appRoot QComboBox:focus, #appRoot QPlainTextEdit:focus {
    border-color: #f5a54a;
}
#appRoot QPushButton#pinIcon {
    background: transparent;
    border: 1px solid #3b4566;
    border-radius: 6px;
    padding: 2px;
}
#appRoot QPushButton#pinIcon:hover {
    border-color: #e7b008;
}
#appRoot QComboBox QAbstractItemView {
    background-color: #2a3350;
    color: #e8ecf4;
    border: 1px solid #56638a;
    selection-background-color: #38436a;
    selection-color: #ffffff;
}
#appRoot QCheckBox { font-size: 14px; spacing: 8px; background: transparent; }
#appRoot QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 4px;
    border: 1px solid #4a5680;
    background: #1f2740;
}
#appRoot QCheckBox::indicator:checked { background: #f5a54a; border-color: #f5a54a; }
#appRoot QSlider::groove:horizontal {
    height: 6px;
    background: #38436a;
    border-radius: 3px;
}
#appRoot QSlider::sub-page:horizontal { background: #f5a54a; border-radius: 3px; }
#appRoot QSlider::handle:horizontal {
    background: #ffffff;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
#appRoot QProgressBar {
    background-color: #38436a;
    border: none;
    border-radius: 3px;
    height: 8px;
    text-align: center;
    color: transparent;
}
#appRoot QProgressBar::chunk { background-color: #f5a54a; border-radius: 3px; }
#appRoot QScrollArea { border: none; background: transparent; }
#appRoot QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
#appRoot QScrollBar::handle:vertical { background: #38436a; border-radius: 4px; min-height: 30px; }
#appRoot QScrollBar::handle:vertical:hover { background: #4a5680; }
#appRoot QScrollBar::add-line:vertical, #appRoot QScrollBar::sub-line:vertical { height: 0; }
#appRoot QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
#appRoot QScrollBar::handle:horizontal { background: #38436a; border-radius: 4px; min-width: 30px; }
#appRoot QScrollBar::add-line:horizontal, #appRoot QScrollBar::sub-line:horizontal { width: 0; }
#appRoot QMenu {
    background-color: #2a3350;
    border: 1px solid #56638a;
    border-radius: 10px;
    padding: 6px;
}
#appRoot QMenu::item { padding: 8px 14px; border-radius: 6px; }
#appRoot QMenu::item:selected { background: #38436a; }
#appRoot QMenu::separator { height: 1px; background: #38436a; margin: 4px 6px; }
"""

MENU_QSS = """
QMenu {
    background-color: #2a3350;
    color: #e8ecf4;
    border: 1px solid #56638a;
    border-radius: 10px;
    padding: 6px;
    font-size: 14px;
}
QMenu::item { padding: 8px 14px; border-radius: 6px; }
QMenu::item:selected { background: #38436a; }
QMenu::separator { height: 1px; background: #38436a; margin: 4px 6px; }
"""

DIALOG_QSS = """
QDialog { background: #2a3350; color: #e8ecf4; }
QLabel { color: #e8ecf4; font-size: 15px; background: transparent; }
QPlainTextEdit, QListWidget, QLineEdit {
    background: #1f2740;
    color: #e8ecf4;
    border: 1px solid #4a5680;
    border-radius: 6px;
    padding: 6px;
    selection-background-color: #f5a54a;
    selection-color: #2a1606;
}
QPushButton {
    background: #38436a;
    color: #e8ecf4;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover { background: #4a5680; }
QPushButton#primary { background: #f5a54a; color: #2a1606; }
QPushButton#primary:hover { background: #f8b866; }
"""
