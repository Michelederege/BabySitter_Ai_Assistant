"""Which microphone BabySitter opens.

Windows' default microphone is not always the one you talk into. A
webcam or a dock can hold the default and send no sound at all. Settings
can name one microphone, and both keyword listening and Talk open that one.

A microphone shows up once per Windows sound system. MME cuts the name at
31 characters, DirectSound keeps the whole name, and WASAPI often refuses
16,000 samples a second. So the name is kept in full, and it is opened
through DirectSound first, then MME. Nothing here records anything.
"""

from __future__ import annotations

# Not a microphone, only Windows pointing at its own default.
_STAND_INS = {"microsoft sound mapper - input", "primary sound capture driver"}
_PREFERRED_APIS = ("Windows DirectSound", "MME")


def _rows(sd) -> list[tuple[int, str, str]]:
    """(device index, sound system name, device name) for every input."""
    apis = sd.query_hostapis()
    rows: list[tuple[int, str, str]] = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels") or 0) <= 0:
            continue
        api = str(apis[int(device["hostapi"])]["name"])
        rows.append((index, api, str(device["name"]).strip()))
    return rows


def _real(name: str) -> bool:
    return bool(name) and name.lower() not in _STAND_INS


def list_microphones(sd=None) -> list[str]:
    """Full names, once each, in the order Windows lists them."""
    if sd is None:
        import sounddevice as sd
    names: list[str] = []
    rows = _rows(sd)
    # DirectSound has the full names. MME is only used when it is missing.
    for wanted in _PREFERRED_APIS:
        for _index, api, name in rows:
            if api == wanted and _real(name) and name not in names:
                names.append(name)
        if names:
            break
    return names


def device_for(name: str, sd=None) -> int | None:
    """The device index for this saved name. None means Windows' default."""
    wanted = " ".join((name or "").split())
    if not wanted:
        return None
    if sd is None:
        import sounddevice as sd
    rows = _rows(sd)
    for api in _PREFERRED_APIS:
        for index, row_api, row_name in rows:
            if row_api != api:
                continue
            # MME's copy of a name stops at 31 characters.
            if row_name == wanted or (len(row_name) >= 31 and wanted.startswith(row_name)):
                return index
    return None


def default_name(sd=None) -> str:
    """The name of Windows' default microphone, or an empty string."""
    if sd is None:
        import sounddevice as sd
    try:
        return str(sd.query_devices(kind="input")["name"]).strip()
    except Exception:
        return ""


def shown_name(saved: str, sd=None) -> str:
    """The microphone that will really be opened, for a spoken message."""
    if (saved or "").strip():
        return saved.strip()
    found = default_name(sd)
    return f"Windows' default microphone, {found}" if found else "Windows' default microphone"
