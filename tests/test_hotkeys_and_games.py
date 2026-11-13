import pytest

from babysitter.games import GameWatch, clean_process_name, first_matching_game
from babysitter.hotkeys import HotkeyBook, HotkeyError, MemoryRegistrar, canonical_hotkey, parse_hotkey
from babysitter.platform import autostart_command


def test_default_emergency_key_parses():
    _mods, vk, label = parse_hotkey("Ctrl+Alt+F12")
    assert label == "Ctrl+Alt+F12"
    assert vk == 0x7B


def test_typing_keys_are_rejected():
    with pytest.raises(HotkeyError):
        canonical_hotkey("Ctrl+C")
    with pytest.raises(HotkeyError):
        canonical_hotkey("F12")
    with pytest.raises(HotkeyError):
        canonical_hotkey("Alt+F4")


def test_same_key_cannot_be_both():
    book = HotkeyBook()
    with pytest.raises(HotkeyError):
        book.apply("Ctrl+Alt+F12", "ctrl+alt+f12", MemoryRegistrar())


def test_assistant_flag_does_not_drop_emergency_key():
    book = HotkeyBook()
    registrar = MemoryRegistrar()
    notes = book.apply("Ctrl+Alt+F12", "Ctrl+Alt+F11", registrar)
    assert notes == []
    book.set_assistant_enabled(False)
    assert 1 in book.registered
    assert 2 in book.registered
    assert book.assistant_enabled is False


def test_failed_registration_is_reported():
    book = HotkeyBook()
    notes = book.apply("Ctrl+Alt+F12", "Ctrl+Alt+F11", MemoryRegistrar(failures={1}))
    assert notes and "Ctrl+Alt+F12" in notes[0]
    assert 2 in book.registered


def test_process_name_drops_a_path():
    assert clean_process_name(r"C:\Games\bg3.exe") == "bg3.exe"
    assert clean_process_name("  game.exe  ") == "game.exe"
    with pytest.raises(ValueError):
        clean_process_name("..")


def test_game_match_ignores_case():
    assert first_matching_game(["BG3.exe"], {"bg3.exe", "explorer.exe"}) == "BG3.exe"
    assert first_matching_game(["bg3.exe"], {"explorer.exe"}) is None


def test_wake_suppresses_auto_switch_until_the_game_closes():
    watch = GameWatch()
    assert watch.auto_switch_target("bg3.exe") == "bg3.exe"
    watch.suppress("bg3.exe")
    assert watch.auto_switch_target("bg3.exe") is None
    assert watch.auto_switch_target(None) is None
    assert watch.auto_switch_target("bg3.exe") == "bg3.exe"


def test_autostart_command_is_fixed_text():
    frozen = autostart_command(frozen=True, executable=r"C:\Apps\BabySitter.exe", source_launcher=None)
    assert frozen == r'"C:\Apps\BabySitter.exe"'
    source = autostart_command(
        frozen=False,
        executable="python",
        source_launcher=r"C:\src\Run BabySitter.vbs",
    )
    assert "wscript.exe" in source
    assert "Run BabySitter.vbs" in source
