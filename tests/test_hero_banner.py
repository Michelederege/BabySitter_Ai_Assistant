"""The home picture fills its panel and changes with the state."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from babysitter.paths import asset_path
from babysitter.ui.hero_banner import HeroBanner


def _banner() -> HeroBanner:
    QApplication.instance() or QApplication([])
    banner = HeroBanner(asset_path("hero.jpg"), asset_path("orb"))
    banner.set_reduced_motion(True)
    banner.resize(480, 150)
    return banner


def _light(banner: HeroBanner) -> int:
    image = banner._background().toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 3)
    return color.red() + color.green() + color.blue()


def test_off_is_darker_than_on():
    banner = _banner()
    banner.show_phase("off", "Off", "The AI is off. Nothing is listening.")
    off = _light(banner)
    banner.show_phase("on", "On", "Hold Mouse 4 or say the keyword.")
    assert _light(banner) > off
    assert banner.word.text() == "On"


def test_the_picture_is_cropped_to_the_banner():
    banner = _banner()
    image = banner._background().toImage()
    assert image.width() == banner.width()
    assert image.height() == banner.height()
    contained = banner._img.scaled(
        banner.width(), banner.height(), Qt.AspectRatioMode.KeepAspectRatio
    )
    assert contained.width() < banner.width() or contained.height() < banner.height()


def test_listening_keeps_the_on_picture_and_changes_the_frog():
    banner = _banner()
    banner.show_phase("listening", "Listening", "Say the question now.")
    assert banner._key == "on"
    assert banner.frog._state == "listening"
    assert banner.hint.text() == "Say the question now."


def test_half_screen_is_taller_than_full_screen():
    banner = _banner()
    banner.set_compact(False)
    assert banner.height() == 150
    banner.set_compact(True)
    assert banner.height() == 170


def test_a_missing_picture_leaves_the_current_one():
    banner = _banner()
    width = banner._img.width()
    assert banner.set_image("/no/such/picture.jpg") is False
    assert banner._img.width() == width
    assert banner.hint.text() == "The AI is off. Nothing is listening."
