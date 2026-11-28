"""How hard each program is working the graphics card, from Windows' own counters.

Windows keeps two per-program counters for the card (the same ones Task
Manager shows in its GPU column):

* "GPU Engine(pid_N_..._engtype_3D)\\Utilization Percentage": how busy
  the card's 3D engine is for that program;
* "GPU Process Memory(pid_N_...)\\Dedicated Usage": its video memory.

They're read with the Performance Data Helper (pdh.dll) through ctypes: no
extra program, no new library, a few milliseconds per reading. A busy
percentage needs two samples, so one query stays open and each reading
compares with the one before.
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass

_ENGINE = r"\GPU Engine(*)\Utilization Percentage"
_MEMORY = r"\GPU Process Memory(*)\Dedicated Usage"
_PID = re.compile(r"pid_(\d+)_")
_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2


@dataclass(frozen=True)
class Load:
    """One program's share of the card."""

    busy: float  # percent of the busiest engine type, 0 to 100
    memory_mib: int


class _Value(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _Item(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _Value)]


def per_engine_busy(rows: list[tuple[str, float]]) -> dict[int, float]:
    """Instance rows to each program's busiest engine type, in percent.

    One program has a row per engine (3D, Copy, Video Decode ...) and per
    adapter; rows of the same engine type add up, and the busiest type is
    the program's load, the way Task Manager shows it.
    """
    totals: dict[tuple[int, str], float] = {}
    for name, value in rows:
        found = _PID.search(name or "")
        if not found:
            continue
        kind = name.rsplit("engtype_", 1)[-1] if "engtype_" in name else "other"
        key = (int(found.group(1)), kind)
        totals[key] = totals.get(key, 0.0) + max(0.0, float(value))
    busy: dict[int, float] = {}
    for (pid, _kind), value in totals.items():
        busy[pid] = min(100.0, max(busy.get(pid, 0.0), value))
    return busy


def per_process_memory(rows: list[tuple[str, float]]) -> dict[int, int]:
    """Instance rows to each program's dedicated video memory, in MiB."""
    memory: dict[int, int] = {}
    for name, value in rows:
        found = _PID.search(name or "")
        if not found:
            continue
        pid = int(found.group(1))
        memory[pid] = memory.get(pid, 0) + int(max(0.0, float(value)) // (1024 * 1024))
    return memory


def load_of(pids, busy: dict[int, float], memory: dict[int, int]) -> Load:
    """All of one game's processes together."""
    pids = set(pids or ())
    return Load(
        busy=min(100.0, sum(busy.get(pid, 0.0) for pid in pids)),
        memory_mib=sum(memory.get(pid, 0) for pid in pids),
    )


class GpuLoadReader:
    """One open counter query. read() gives {pid: Load}; the first read only primes it."""

    def __init__(self) -> None:
        self._query = None
        self._engine = None
        self._memory = None
        self._primed = False
        self.available = sys.platform == "win32"

    def _open(self) -> bool:
        if self._query is not None:
            return True
        if not self.available:
            return False
        try:
            pdh = ctypes.WinDLL("pdh.dll")
            query = wintypes.HANDLE()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
                self.available = False
                return False
            engine, memory = wintypes.HANDLE(), wintypes.HANDLE()
            add = pdh.PdhAddEnglishCounterW
            if add(query, _ENGINE, None, ctypes.byref(engine)) != 0:
                pdh.PdhCloseQuery(query)
                self.available = False
                return False
            if add(query, _MEMORY, None, ctypes.byref(memory)) != 0:
                memory = None
        except (OSError, AttributeError):
            self.available = False
            return False
        self._pdh, self._query, self._engine, self._memory = pdh, query, engine, memory
        return True

    def _rows(self, counter) -> list[tuple[str, float]]:
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
        if (status & 0xFFFFFFFF) != _PDH_MORE_DATA or size.value == 0:
            return []
        buffer = (ctypes.c_byte * size.value)()
        status = self._pdh.PdhGetFormattedCounterArrayW(counter, _PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buffer)
        if status != 0:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(_Item))
        rows = []
        for index in range(count.value):
            item = items[index]
            if item.FmtValue.CStatus in (0, 1):  # valid, or valid with new data
                rows.append((item.szName or "", item.FmtValue.doubleValue))
        return rows

    def read(self) -> dict[int, Load] | None:
        """Each program's load since the last read. None when the counters can't be read."""
        if not self._open():
            return None
        try:
            if self._pdh.PdhCollectQueryData(self._query) != 0:
                return None
            if not self._primed:
                self._primed = True
                return {}
            busy = per_engine_busy(self._rows(self._engine))
            memory = per_process_memory(self._rows(self._memory)) if self._memory else {}
        except (OSError, ValueError):
            return None
        pids = set(busy) | set(memory)
        return {pid: Load(busy.get(pid, 0.0), memory.get(pid, 0)) for pid in pids}

    def close(self) -> None:
        if self._query is not None:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except OSError:
                pass
        self._query = None
