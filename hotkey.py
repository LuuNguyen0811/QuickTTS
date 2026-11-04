#!/usr/bin/env python3
"""Global Option+` / Control+Option+` listener. Speaks the selection."""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import ApplicationServices
import Quartz
from AppKit import NSBundle, NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from CoreFoundation import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRunInMode,
    kCFRunLoopCommonModes,
    kCFRunLoopDefaultMode,
)

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
TTS_URL = "http://127.0.0.1:8765/tts"
AFPLAY = "/usr/bin/afplay"
GRAVE_KEY = 50
C_KEY = 8
COMMAND_KEY = 55
COPY_TIMEOUT = 0.6
PYTHON_APP = "/opt/homebrew/Cellar/python@3.12/3.12.11/Frameworks/Python.framework/Versions/3.12/Resources/Python.app"

_events = queue.Queue()
_main_queue = queue.Queue()
_tap = None
_tap_source = None
_player = None
_selection_lock = threading.Lock()


def permission_text() -> str:
    return (
        "macOS is blocking the hotkey listener.\n"
        "Turn these on, then run:\n"
        "  /Users/luunguyen/kokoro-tts/stop.sh && /Users/luunguyen/kokoro-tts/start.sh\n"
        "\n"
        "1. System Settings → Privacy & Security → Accessibility\n"
        "   Enable Python. If it is not listed, click +, press Command-Shift-G, and open:\n"
        f"   {PYTHON_APP}\n"
        "\n"
        "2. System Settings → Privacy & Security → Input Monitoring\n"
        "   Enable the same Python.\n"
    )


def ax_trusted() -> bool:
    return bool(ApplicationServices.AXIsProcessTrusted())


def _ax_value(element, attribute):
    try:
        result = ApplicationServices.AXUIElementCopyAttributeValue(
            element, attribute, None
        )
    except Exception:
        return None
    if isinstance(result, tuple):
        if len(result) >= 2 and isinstance(result[0], int) and result[0] != 0:
            return None
        if len(result) >= 2:
            return result[1]
        return result[0] if result else None
    return result


def ax_selected_text() -> str:
    if not ax_trusted():
        return ""
    system = ApplicationServices.AXUIElementCreateSystemWide()
    ApplicationServices.AXUIElementSetMessagingTimeout(system, 0.4)
    focused = _ax_value(system, ApplicationServices.kAXFocusedUIElementAttribute)
    if focused is None:
        return ""
    ApplicationServices.AXUIElementSetMessagingTimeout(focused, 0.4)
    value = _ax_value(focused, ApplicationServices.kAXSelectedTextAttribute)
    if value is None:
        return ""
    return str(value)


def _snapshot(pasteboard):
    saved = []
    items = pasteboard.pasteboardItems() or []
    for item in items:
        chunks = []
        for kind in item.types():
            chunks.append((kind, item.dataForType_(kind)))
        saved.append(chunks)
    return saved


def _restore(pasteboard, saved) -> None:
    pasteboard.clearContents()
    if not saved:
        return
    objects = []
    for chunks in saved:
        item = NSPasteboardItem.alloc().init()
        for kind, data in chunks:
            if data is not None:
                item.setData_forType_(data, kind)
        objects.append(item)
    if not pasteboard.writeObjects_(objects):
        print("pasteboard restore failed", flush=True)


def _post_key(source, keycode: int, key_down: bool, flags: int) -> None:
    event = Quartz.CGEventCreateKeyboardEvent(source, keycode, key_down)
    Quartz.CGEventSetFlags(event, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def send_copy() -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    command = Quartz.kCGEventFlagMaskCommand
    _post_key(source, COMMAND_KEY, True, command)
    time.sleep(0.01)
    _post_key(source, C_KEY, True, command)
    time.sleep(0.01)
    _post_key(source, C_KEY, False, command)
    time.sleep(0.01)
    _post_key(source, COMMAND_KEY, False, 0)


def call_on_main(fn):
    done = threading.Event()
    box = {}

    def wrapper():
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        done.set()

    _main_queue.put(wrapper)
    if not done.wait(timeout=2):
        raise TimeoutError("pasteboard work was not run")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def copied_text() -> str:
    def begin():
        pasteboard = NSPasteboard.generalPasteboard()
        return pasteboard.changeCount(), _snapshot(pasteboard)

    before, saved = call_on_main(begin)
    send_copy()
    deadline = time.monotonic() + COPY_TIMEOUT
    text = ""
    changed = False
    while time.monotonic() < deadline:
        def poll():
            pasteboard = NSPasteboard.generalPasteboard()
            if pasteboard.changeCount() == before:
                return None
            value = pasteboard.stringForType_(NSPasteboardTypeString)
            return str(value) if value else ""

        got = call_on_main(poll)
        if got is not None:
            changed = True
            text = got
            break
        time.sleep(0.02)
    if changed:
        def restore():
            _restore(NSPasteboard.generalPasteboard(), saved)

        call_on_main(restore)
    return text


def read_selection() -> str:
    text = ax_selected_text()
    if text.strip():
        return text
    if not ax_trusted():
        print(permission_text(), flush=True)
        return ""
    print("no accessibility selection, trying copy", flush=True)
    return copied_text()


class Player:
    def __init__(self):
        self._lock = threading.Lock()
        self._gen = 0
        self._proc = None

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            proc.kill()

    def request(self, text: str) -> None:
        with self._lock:
            self._gen += 1
            generation = self._gen
            self._stop_locked()
        threading.Thread(
            target=self._run, args=(generation, text), daemon=True
        ).start()

    def _run(self, generation: int, text: str) -> None:
        print(f"speaking {len(text)} characters", flush=True)
        try:
            wav = fetch_wav(text)
        except Exception as exc:
            print(f"tts failed: {exc}", flush=True)
            return
        if len(wav) < 44 or not wav.startswith(b"RIFF"):
            print("tts returned no wav", flush=True)
            return
        with self._lock:
            if generation != self._gen:
                return
            path = LOG_DIR / f"speech-{generation}.wav"
            path.write_bytes(wav)
            for old in LOG_DIR.glob("speech-*.wav"):
                if old != path:
                    try:
                        old.unlink()
                    except OSError:
                        pass
            self._proc = subprocess.Popen(
                [AFPLAY, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )


def fetch_wav(text: str) -> bytes:
    request = urllib.request.Request(
        TTS_URL,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _modifier_mask(flags: int) -> int:
    mask = (
        Quartz.kCGEventFlagMaskShift
        | Quartz.kCGEventFlagMaskControl
        | Quartz.kCGEventFlagMaskAlternate
        | Quartz.kCGEventFlagMaskCommand
    )
    return int(flags) & mask


def _is_speak_shortcut(event) -> str:
    keycode = Quartz.CGEventGetIntegerValueField(
        event, Quartz.kCGKeyboardEventKeycode
    )
    if int(keycode) != GRAVE_KEY:
        return ""
    flags = _modifier_mask(Quartz.CGEventGetFlags(event))
    option = Quartz.kCGEventFlagMaskAlternate
    control_option = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
    if flags == option:
        return "Option+`"
    if flags == control_option:
        return "Control+Option+`"
    return ""


def _event_type(value) -> int:
    return int(value) & 0xFFFFFFFF


def event_callback(proxy, event_type, event, refcon):
    del proxy, refcon
    try:
        kind = _event_type(event_type)
        if kind in (0xFFFFFFFE, 0xFFFFFFFF):
            if _tap is not None:
                Quartz.CGEventTapEnable(_tap, True)
            return event
        if event is None:
            return event
        name = _is_speak_shortcut(event)
        if not name:
            return event
        repeat = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventAutorepeat
        )
        if int(repeat):
            return None
        _events.put(name)
        return None
    except Exception:
        traceback.print_exc()
        return event


def install_tap() -> bool:
    global _tap, _tap_source
    if _tap is not None:
        return True
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        event_callback,
        None,
    )
    if tap is None:
        return False
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    _tap = tap
    _tap_source = source
    print("event tap installed", flush=True)
    return True


def speak_hotkey(name: str) -> None:
    with _selection_lock:
        print(f"hotkey {name}", flush=True)
        text = read_selection().strip()
        if not text:
            print("empty selection, ignored", flush=True)
            return
        _player.request(text)


def drain_hotkeys() -> None:
    names = []
    while True:
        try:
            names.append(_events.get_nowait())
        except queue.Empty:
            break
    if names:
        threading.Thread(target=speak_hotkey, args=(names[-1],), daemon=True).start()


def drain_main() -> None:
    while True:
        try:
            fn = _main_queue.get_nowait()
        except queue.Empty:
            return
        fn()


def _shutdown(signum, frame):
    del signum, frame
    if _player is not None:
        _player.stop()
    raise SystemExit(0)


def main():
    global _player
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    LOG_DIR.mkdir(exist_ok=True)
    (LOG_DIR / "hotkey.pid").write_text(str(os.getpid()))
    _player = Player()
    print(f"python {os.path.realpath(sys.executable)}", flush=True)
    print(f"bundle {NSBundle.mainBundle().bundlePath()}", flush=True)
    print(f"accessibility trusted: {ax_trusted()}", flush=True)
    print(
        "shortcuts: Option+` (keycode 50) and Control+Option+`. "
        "Option+` is a dead key on the ABC keyboard layout, so "
        "Control+Option+` is the reliable shortcut.",
        flush=True,
    )
    try:
        ax_selected_text()
        print("accessibility query ok", flush=True)
    except Exception as exc:
        print(f"accessibility query failed: {exc}", flush=True)
    warned = False
    while True:
        if _tap is None and not install_tap():
            if not warned:
                print(permission_text(), flush=True)
                warned = True
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.05, False)
        try:
            drain_main()
            drain_hotkeys()
        except Exception as exc:
            print(f"hotkey failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
