"""Choosing the microphone. Nothing here opens a real one."""

from PySide6.QtWidgets import QApplication

from babysitter.microphones import device_for, list_microphones, shown_name
from babysitter.settings import Settings, load_settings, save_settings


class FakeSound:
    """What sounddevice reports on a PC with a dock, a headset, and a webcam."""

    def __init__(self, default_input: int = 1) -> None:
        self._default = default_input

    def query_hostapis(self):
        return [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]

    def query_devices(self, index=None, kind=None):
        rows = [
            {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2},
            {"name": "Microphone (2- GENERAL - AUDIO)", "hostapi": 0, "max_input_channels": 1},
            {"name": "Microphone (2- PRO X Wireless G", "hostapi": 0, "max_input_channels": 1},
            {"name": "Speakers (Realtek)", "hostapi": 0, "max_input_channels": 0},
            {"name": "Primary Sound Capture Driver", "hostapi": 1, "max_input_channels": 2},
            {"name": "Microphone (2- GENERAL - AUDIO)", "hostapi": 1, "max_input_channels": 1},
            {"name": "Microphone (2- PRO X Wireless Gaming Headset)", "hostapi": 1, "max_input_channels": 1},
            {"name": "Microphone (2- PRO X Wireless Gaming Headset)", "hostapi": 2, "max_input_channels": 2},
        ]
        if kind == "input":
            return rows[self._default]
        if index is not None:
            return rows[index]
        return rows


def test_microphones_are_listed_once_by_their_full_name():
    names = list_microphones(FakeSound())
    assert names == [
        "Microphone (2- GENERAL - AUDIO)",
        "Microphone (2- PRO X Wireless Gaming Headset)",
    ]


def test_a_saved_name_opens_through_directsound_not_wasapi():
    sound = FakeSound()
    assert device_for("Microphone (2- PRO X Wireless Gaming Headset)", sound) == 6
    assert device_for("", sound) is None
    assert device_for("A headset that is unplugged", sound) is None


def test_the_cut_mme_name_still_matches_when_directsound_is_missing():
    class MmeOnly(FakeSound):
        def query_hostapis(self):
            return [{"name": "MME"}, {"name": "Other"}, {"name": "Other"}]

    sound = MmeOnly()
    assert device_for("Microphone (2- PRO X Wireless Gaming Headset)", sound) == 2
    assert "Microphone (2- PRO X Wireless G" in list_microphones(sound)


def test_a_message_names_the_microphone_that_was_really_opened():
    assert shown_name("Microphone (Fifine)", FakeSound()) == "Microphone (Fifine)"
    assert shown_name("", FakeSound()) == "Windows' default microphone, Microphone (2- GENERAL - AUDIO)"


def test_the_choice_is_saved(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(microphone="Microphone (2- PRO X Wireless Gaming Headset)"), path)
    assert load_settings(path).microphone == "Microphone (2- PRO X Wireless Gaming Headset)"
    assert Settings().microphone == ""


def _shell(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    return app, controller, Shell(controller)


def test_settings_lists_microphones_and_the_listener_uses_the_choice(tmp_path, monkeypatch):
    import babysitter.microphones as microphones

    real_list, real_device, real_default = (
        microphones.list_microphones, microphones.device_for, microphones.default_name,
    )
    sound = FakeSound()
    monkeypatch.setattr(microphones, "list_microphones", lambda sd=None: real_list(sound))
    monkeypatch.setattr(microphones, "device_for", lambda name, sd=None: real_device(name, sound))
    monkeypatch.setattr(microphones, "default_name", lambda sd=None: real_default(sound))
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        shell._fill_microphones()
        box = shell.window.settings_page.microphone
        labels = [box.itemText(index) for index in range(box.count())]
        assert labels[0] == "Windows default (Microphone (2- GENERAL - AUDIO))"
        assert "Microphone (2- PRO X Wireless Gaming Headset)" in labels

        shell._set_microphone("Microphone (2- PRO X Wireless Gaming Headset)")
        assert controller.settings.microphone == "Microphone (2- PRO X Wireless Gaming Headset)"
        assert shell._listener.device == 6
        assert load_settings().microphone == "Microphone (2- PRO X Wireless Gaming Headset)"

        # An unplugged choice stays visible instead of silently switching back.
        controller.settings.microphone = "Microphone (Old USB)"
        shell._fill_microphones()
        labels = [box.itemText(index) for index in range(box.count())]
        assert "Microphone (Old USB) (not found right now)" in labels
        assert box.currentData() == "Microphone (Old USB)"
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()


def test_talk_with_a_silent_microphone_says_which_one(tmp_path, monkeypatch):
    app, controller, shell = _shell(tmp_path, monkeypatch)
    try:
        controller.settings.microphone = "Microphone (2- GENERAL - AUDIO)"
        heard: list = []
        monkeypatch.setattr(shell, "_start_hear", lambda wav, done: heard.append(wav))
        monkeypatch.setattr(shell._recorder, "stop", lambda: b"")
        shell._holding = True
        shell._recording = True
        shell._hold_up()
        assert heard == []
        from PySide6.QtWidgets import QLabel

        text = " ".join(label.text() for label in shell.window.findChildren(QLabel))
        assert "No sound came from Microphone (2- GENERAL - AUDIO)." in text
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
