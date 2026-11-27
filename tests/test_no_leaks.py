"""Long run, scan F (0.29.0): long use must not grow memory.

Each DPAPI call built a new ctypes structure type, and ctypes keeps every
type (and its pointer type) for good. The History page decrypts every saved
conversation on each refresh, so 600 local commands grew BabySitter from
116 MB to 784 MB. The types are now made once.
"""

from __future__ import annotations

import gc
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_decrypting_many_times_keeps_no_new_objects():
    from babysitter.secrets import protect_blob, unprotect_blob

    sealed = protect_blob(b"a saved conversation", "BabySitter test")
    for _ in range(5):
        unprotect_blob(sealed)
    gc.collect()
    before = len(gc.get_objects())
    for _ in range(300):
        assert unprotect_blob(sealed) == b"a saved conversation"
    gc.collect()
    assert len(gc.get_objects()) - before < 50


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_the_windows_calls_are_made_once():
    from babysitter import secrets

    first = secrets._dpapi()
    assert secrets._dpapi() is first
