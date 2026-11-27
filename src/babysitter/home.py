"""Home Assistant and music, on your own local network only (NEXT_ROUND phase 6).

BabySitter talks only to the one address you set, and only if that address
is on this home network (192.168.x.x, 10.x.x.x, 172.16-31.x.x, a .local
name, or a single-word name like homeassistant). A public address is refused.

You say the command; BabySitter says what it will do and waits for your yes,
the way a reminder is confirmed. The model's words never press play or flip
a switch: nothing the model writes reaches this file.

Music goes through Home Assistant's media players, so it obeys the same
address and the same yes. The access token is encrypted with DPAPI.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass

from babysitter.paths import secrets_dir

ACTIONS = {
    "turn_on": "turn on",
    "turn_off": "turn off",
    "toggle": "switch",
}
MUSIC_ACTIONS = {
    "media_play": "play",
    "media_pause": "pause",
    "media_next_track": "skip to the next song on",
    "media_previous_track": "go back a song on",
    "volume_up": "turn up",
    "volume_down": "turn down",
}
SWITCH_DOMAINS = ("light", "switch", "fan", "cover", "input_boolean", "media_player", "climate")


class HomeError(Exception):
    """The house could not be reached. The message says what to do."""


@dataclass(frozen=True)
class HomeCommand:
    domain: str
    service: str
    entity_id: str
    name: str

    @property
    def ask(self) -> str:
        verb = ACTIONS.get(self.service) or MUSIC_ACTIONS.get(self.service) or self.service.replace("_", " ")
        return f"{verb.capitalize()} {self.name}?"


def _host_is_local(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host.endswith(".local") or host.endswith(".lan") or host.endswith(".home.arpa") or "." not in host:
            return True
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        addresses = {info[4][0] for info in infos}
        return bool(addresses) and all(_host_is_local(item) for item in addresses if not item.startswith("fe80"))
    return address.is_private or address.is_loopback or address.is_link_local


def clean_base_url(raw: str) -> str:
    """The Home Assistant address, checked to be on this network. Raises HomeError otherwise."""
    text = (raw or "").strip().rstrip("/")
    if not text:
        raise HomeError("Type the Home Assistant address, such as homeassistant.local:8123.")
    if "://" not in text:
        # An address typed without a scheme. Whatever it is, the host is checked
        # to be on this network just below, before anything is sent.
        text = "http" + "://" + text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.query:
        raise HomeError("Use an address like homeassistant.local:8123, with no name or password in it.")
    if not _host_is_local(parsed.hostname or ""):
        raise HomeError("That address is not on your home network, so BabySitter will not talk to it.")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


class HomeTokenVault:
    """The long-lived access token, encrypted for this Windows user."""

    def __init__(self, path=None) -> None:
        self.path = path or (secrets_dir() / "home-assistant.dpapi")

    def has_token(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def save(self, token: str) -> None:
        cleaned = (token or "").strip()
        if len(cleaned) < 20 or len(cleaned) > 1000 or any(character.isspace() for character in cleaned):
            raise HomeError("Paste the long-lived access token from your Home Assistant profile, as one line.")
        if sys.platform != "win32":
            raise HomeError("Saving the token needs Windows, where it is encrypted for your user only.")
        from babysitter.secrets import protect_blob

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".dpapi.tmp")
        temporary.write_bytes(protect_blob(cleaned.encode("utf-8"), "BabySitter Home Assistant token"))
        temporary.replace(self.path)

    def load(self) -> str:
        if not self.has_token():
            return ""
        from babysitter.secrets import unprotect_blob

        try:
            return unprotect_blob(self.path.read_bytes()).decode("utf-8").strip()
        except Exception:  # noqa: BLE001
            return ""

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


def _request(base: str, token: str, path: str, body: dict | None = None, opener=None):
    url = clean_base_url(base) + path
    if not token:
        raise HomeError("Save the Home Assistant token first, under Settings, Accounts and home.")
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Content-Type", "application/json")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=6) as response:
            raw = response.read(2_000_000)
            status = getattr(response, "status", 200)
    except Exception as exc:
        raise HomeError("Home Assistant did not answer. Check that it is on and the address is right.") from exc
    if int(status) == 401:
        raise HomeError("Home Assistant refused the token. Make a new long-lived token and save it again.")
    if int(status) >= 400:
        raise HomeError("Home Assistant refused that.")
    try:
        return json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeError, json.JSONDecodeError):
        return None


def list_entities(base: str, token: str, opener=None) -> list[dict]:
    states = _request(base, token, "/api/states", opener=opener)
    found: list[dict] = []
    for item in states if isinstance(states, list) else []:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity_id") or "")
        domain = entity.split(".", 1)[0]
        if domain not in SWITCH_DOMAINS:
            continue
        attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        name = str(attributes.get("friendly_name") or entity.split(".", 1)[-1].replace("_", " "))
        found.append({"entity_id": entity, "domain": domain, "name": name, "state": str(item.get("state") or "")})
    return found


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def best_match(spoken: str, entities: list[dict], domains: tuple[str, ...] = SWITCH_DOMAINS) -> dict | None:
    """The entity whose name best matches the spoken words. None when no word matches."""
    wanted = [word for word in _words(spoken) if word not in {"the", "my", "a", "in", "on", "off", "lights", "light"}]
    if not wanted:
        wanted = _words(spoken)
    best, best_score = None, 0.0
    for entity in entities:
        if entity["domain"] not in domains:
            continue
        name_words = set(_words(entity["name"])) | set(_words(entity["entity_id"].split(".", 1)[-1]))
        hits = sum(1 for word in wanted if word in name_words or word.rstrip("s") in name_words)
        if not hits:
            continue
        score = hits / max(1, len(wanted)) + hits / max(1, len(name_words)) * 0.5
        if "light" in _words(spoken) and entity["domain"] == "light":
            score += 0.25
        if score > best_score:
            best, best_score = entity, score
    return best


_SWITCH = re.compile(r"(turn|switch) (on|off) (?:the |my )?(.+)|(turn|switch) (?:the |my )?(.+?) (on|off)")
_MUSIC = {
    "play music": "media_play", "play the music": "media_play", "resume the music": "media_play", "resume music": "media_play",
    "pause music": "media_pause", "pause the music": "media_pause", "stop the music": "media_pause", "stop music": "media_pause",
    "next song": "media_next_track", "skip this song": "media_next_track", "skip song": "media_next_track",
    "previous song": "media_previous_track", "last song": "media_previous_track",
    "turn the music up": "volume_up", "music louder": "volume_up", "turn up the music": "volume_up",
    "turn the music down": "volume_down", "music quieter": "volume_down", "turn down the music": "volume_down",
}


def parse_house(phrase: str) -> tuple[str, str] | None:
    """('turn_on' | 'turn_off', 'kitchen light') or ('media_*', '') from the words said. None otherwise."""
    text = " ".join(_words(phrase))
    if text in _MUSIC:
        return _MUSIC[text], ""
    match = _SWITCH.fullmatch(text)
    if not match:
        return None
    if match.group(3):
        state, target = match.group(2), match.group(3)
    else:
        target, state = match.group(5), match.group(6)
    if not target or target in {"it", "that", "this", "the ai", "ai", "you", "yourself", "game mode", "the microphone",
                                "listening", "the keyword", "keyword listening", "quiet hours", "the voice"}:
        return None
    return ("turn_on" if state == "on" else "turn_off"), target


def plan(phrase: str, entities: list[dict], music_entity: str = "") -> HomeCommand | None:
    parsed = parse_house(phrase)
    if parsed is None:
        return None
    service, target = parsed
    if service.startswith("media_") or service.startswith("volume_"):
        chosen = next((item for item in entities if item["entity_id"] == music_entity), None)
        if chosen is None:
            players = [item for item in entities if item["domain"] == "media_player"]
            chosen = next((item for item in players if item["state"] == "playing"), players[0] if players else None)
        if chosen is None:
            return None
        return HomeCommand("media_player", service, chosen["entity_id"], chosen["name"])
    entity = best_match(target, entities)
    if entity is None:
        return None
    domain = entity["domain"]
    if domain == "cover":
        service = "open_cover" if service == "turn_on" else "close_cover"
    return HomeCommand(domain, service, entity["entity_id"], entity["name"])


def run(command: HomeCommand, base: str, token: str, opener=None) -> str:
    """Do one confirmed command. Only ever called after your yes."""
    _request(base, token, f"/api/services/{command.domain}/{command.service}", {"entity_id": command.entity_id}, opener)
    verb = ACTIONS.get(command.service) or MUSIC_ACTIONS.get(command.service) or command.service.replace("_", " ")
    past = {"turn on": "Turned on", "turn off": "Turned off", "play": "Playing", "pause": "Paused"}.get(verb, "Done:")
    return f"{past} {command.name}." if past != "Done:" else f"Done. {verb.capitalize()} {command.name}."
