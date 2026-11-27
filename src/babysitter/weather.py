"""Weather from Open-Meteo, after a yes every time (NEXT_ROUND phase 6).

Open-Meteo is free and needs no account or key. Only the town name (to find
it) and then its rounded position leave this PC, and only after you say yes.
Nothing about you is sent. The answer is spoken from the numbers here; the
chat model is not needed for it.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_HOSTS = {"geocoding-api.open-meteo.com", "api.open-meteo.com"}

# WMO weather codes, as Open-Meteo returns them, in plain words.
_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy",
    45: "foggy", 48: "foggy with frost",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


class WeatherError(Exception):
    """The weather could not be read. The message says what to do."""


def require_weather_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "") not in _HOSTS or parsed.username or parsed.password:
        raise WeatherError("The weather only talks to Open-Meteo.")


def clean_place(text: str) -> str:
    place = " ".join((text or "").replace("?", " ").split()).strip(" .,")
    if not place or len(place) > 60 or not any(character.isalpha() for character in place):
        raise WeatherError("Say a town or city, such as Leeds or Milan.")
    return place


def geocode_url(place: str) -> str:
    query = urllib.parse.urlencode({"name": clean_place(place), "count": "1", "language": "en", "format": "json"})
    return GEOCODE_URL + "?" + query


def forecast_url(latitude: float, longitude: float, fahrenheit: bool = False) -> str:
    # Two decimals is about a kilometre: enough for the weather, no closer.
    query = {
        "latitude": f"{float(latitude):.2f}",
        "longitude": f"{float(longitude):.2f}",
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "forecast_days": "2",
        "timezone": "auto",
    }
    if fahrenheit:
        query["temperature_unit"] = "fahrenheit"
        query["wind_speed_unit"] = "mph"
    return FORECAST_URL + "?" + urllib.parse.urlencode(query)


def _get(url: str, opener=None) -> dict:
    require_weather_url(url)
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json", "User-Agent": "BabySitter"})
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=8) as response:
            raw = response.read(200_000)
    except Exception as exc:
        raise WeatherError("Open-Meteo did not answer. Try again in a minute.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WeatherError("The weather answer could not be read.") from exc
    if not isinstance(payload, dict):
        raise WeatherError("The weather answer could not be read.")
    return payload


def find_place(place: str, opener=None) -> tuple[str, float, float]:
    payload = _get(geocode_url(place), opener)
    results = payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise WeatherError(f"I couldn't find a place called {clean_place(place)}.")
    first = results[0]
    try:
        latitude, longitude = float(first["latitude"]), float(first["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError(f"I couldn't find a place called {clean_place(place)}.") from exc
    return str(first.get("name") or clean_place(place)), latitude, longitude


def _words(code) -> str:
    try:
        return _CODES.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def weather_speech(name: str, payload: dict, fahrenheit: bool = False, tomorrow: bool = False) -> str:
    """Two short spoken sentences from the numbers."""
    unit = "°F" if fahrenheit else "°C"
    daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
    index = 1 if tomorrow else 0

    def pick(key):
        values = daily.get(key)
        return values[index] if isinstance(values, list) and len(values) > index else None

    high, low, rain, code = (pick(key) for key in ("temperature_2m_max", "temperature_2m_min", "precipitation_probability_max", "weather_code"))
    parts: list[str] = []
    if not tomorrow:
        current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
        now_temp = current.get("temperature_2m")
        now_words = _words(current.get("weather_code"))
        if isinstance(now_temp, (int, float)):
            parts.append(f"In {name} it's {round(now_temp)}{unit}" + (f" and {now_words}" if now_words else "") + " right now.")
    day = "Tomorrow" if tomorrow else "Today"
    if isinstance(high, (int, float)) and isinstance(low, (int, float)):
        sentence = f"{day}, {round(low)} to {round(high)}{unit}"
        if tomorrow and _words(code):
            sentence += f", {_words(code)}"
        if isinstance(rain, (int, float)):
            sentence += f", with a {round(rain)}% chance of rain" if rain >= 20 else ", and rain is unlikely"
        parts.append(sentence + ".")
    if not parts:
        raise WeatherError("The weather answer had no numbers in it.")
    if tomorrow:
        parts.insert(0, f"In {name}:")
        return " ".join(parts)
    return " ".join(parts)


def uses_fahrenheit() -> bool:
    """Windows' own region setting: the US measurement system means Fahrenheit."""
    import sys

    if sys.platform != "win32":
        return False
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(4)
        # LOCALE_IMEASURE (0x0D): "0" metric, "1" US.
        if ctypes.windll.kernel32.GetLocaleInfoEx(None, 0x0D, buffer, 4):
            return buffer.value.strip() == "1"
    except Exception:  # noqa: BLE001
        return False
    return False


def check(place: str, fahrenheit: bool | None = None, tomorrow: bool = False, opener=None) -> str:
    """Find the place, read its forecast, say it. Called only after a yes."""
    unit = uses_fahrenheit() if fahrenheit is None else fahrenheit
    name, latitude, longitude = find_place(place, opener)
    return weather_speech(name, _get(forecast_url(latitude, longitude, unit), opener), unit, tomorrow)
