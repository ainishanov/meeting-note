"""Give a source run of Meeting Note its own Windows taskbar button and icon.

A source run is pythonw.exe running run.py, so Windows groups its windows
under Python and shows the Python icon. The frozen exe embeds the app icon
and needs none of this; giving it a new ID would also split it from
shortcuts users have already pinned.

Two layers, both with the same ID:

- the process ID covers every window, but Windows ignores it when the
  interpreter is a packaged app (the Microsoft Store Python);
- the ID stored on a window works with any Python, so it is set on every
  top-level window that gets its own taskbar button.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from loguru import logger

APP_USER_MODEL_ID = "AinurNishanov.MeetingNote.Source"
APP_DISPLAY_NAME = "Meeting Note"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_IID_IPROPERTYSTORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_FMTID_APP_USER_MODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_PID_RELAUNCH_COMMAND = 2
_PID_RELAUNCH_ICON = 3
_PID_RELAUNCH_NAME = 4
_PID_ID = 5
_VT_LPWSTR = 31

# IPropertyStore vtable slots.
_RELEASE = 2
_SET_VALUE = 6
_COMMIT = 7


class _GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("value", ctypes.c_wchar_p),
        ("padding", ctypes.c_void_p),
    ]


def is_source_run_on_windows() -> bool:
    return sys.platform == "win32" and not getattr(sys, "frozen", False)


def relaunch_command() -> str:
    """Command Windows runs from a pinned taskbar button."""
    interpreter = Path(sys.executable)
    windowless = interpreter.with_name("pythonw.exe")
    if windowless.exists():
        interpreter = windowless
    return f'"{interpreter}" "{PROJECT_ROOT / "run.py"}"'


def window_properties() -> list[tuple[int, str]]:
    """Taskbar properties for a window; the ID goes last, after its relaunch data."""
    return [
        (_PID_RELAUNCH_COMMAND, relaunch_command()),
        (_PID_RELAUNCH_NAME, APP_DISPLAY_NAME),
        (_PID_RELAUNCH_ICON, f"{PROJECT_ROOT / 'assets' / 'app_icon.ico'},0"),
        (_PID_ID, APP_USER_MODEL_ID),
    ]


def apply_to_process() -> None:
    """Set the process ID; call before the first window is created."""
    if not is_source_run_on_windows():
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError) as exc:
        logger.debug(f"Could not set process taskbar identity: {exc}")


def apply_to_window(widget: object) -> None:
    """Set the ID on a top-level window; call before it is first shown."""
    if not is_source_run_on_windows():
        return
    try:
        _set_window_properties(int(widget.winId()), window_properties())
    except (AttributeError, OSError, ValueError) as exc:
        logger.debug(f"Could not set window taskbar identity: {exc}")


def _guid(text: str) -> _GUID:
    guid = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(guid))
    return guid


def _set_window_properties(hwnd: int, properties: list[tuple[int, str]]) -> None:
    store = ctypes.c_void_p()
    ctypes.oledll.shell32.SHGetPropertyStoreForWindow(
        ctypes.c_void_p(hwnd), ctypes.byref(_guid(_IID_IPROPERTYSTORE)), ctypes.byref(store)
    )
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,
        ctypes.c_void_p,
        ctypes.POINTER(_PROPERTYKEY),
        ctypes.POINTER(_PROPVARIANT),
    )(vtable[_SET_VALUE])
    commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[_COMMIT])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_RELEASE])

    fmtid = _guid(_FMTID_APP_USER_MODEL)
    try:
        for pid, value in properties:
            key = _PROPERTYKEY(fmtid, pid)
            variant = _PROPVARIANT(vt=_VT_LPWSTR, value=value)
            set_value(store, ctypes.byref(key), ctypes.byref(variant))
        commit(store)
    finally:
        release(store)
