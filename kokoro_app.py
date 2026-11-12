#!/usr/bin/env python3
"""Menu bar QuickTTS app. Change model, voice, and shortcut from Settings."""

import ctypes
import ctypes.util
import gc
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import objc

import ApplicationServices
import Quartz
import numpy as np
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBeep,
    NSBezierPath,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSImage,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPopUpButton,
    NSStatusBar,
    NSTabView,
    NSTabViewItem,
    NSTextField,
    NSView,
    NSVariableStatusItemLength,
    NSWorkspace,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeSize, NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer
from PyObjCTools import AppHelper

import hotkey

APP_NAME = "QuickTTS"
MAX_CHARS = 4000
TEXT_INPUT_ROLES = frozenset(
    {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}
)
GRAVE_KEY = 50
CONTROL = Quartz.kCGEventFlagMaskControl
OPTION = Quartz.kCGEventFlagMaskAlternate
SHIFT = Quartz.kCGEventFlagMaskShift
COMMAND = Quartz.kCGEventFlagMaskCommand
MODIFIER_BITS = (
    ("control", CONTROL, "⌃"),
    ("option", OPTION, "⌥"),
    ("shift", SHIFT, "⇧"),
    ("command", COMMAND, "⌘"),
)
MENU_KEYS = {
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    23: "5",
    22: "6",
    26: "7",
    28: "8",
    83: "1",
    84: "2",
    85: "3",
    86: "4",
    87: "5",
    88: "6",
    89: "7",
    91: "8",
}
MODEL_CHOICES = (
    ("int8", "Fast (int8)"),
    ("fp32", "Best quality (full)"),
)
MODEL_FILES = {
    "int8": "kokoro-v1.0.int8.onnx",
    "fp32": "kokoro-v1.0.onnx",
}
DEFAULT_CONFIG = {
    "model": "fp32",
    "voice": "af_heart",
    "keyCode": GRAVE_KEY,
    "modifiers": ["option"],
}
TRANSLATE_LANGUAGES = (
    ("en", "English"),
    ("vi", "Vietnamese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh-Hans", "Chinese"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
)
TRANSLATE_LANGUAGE_CODES = {code for code, _title in TRANSLATE_LANGUAGES}

_app = None


def menu_bar_image():
    path = app_root() / "assets" / "menubarTemplate.png"
    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        return None
    image.setTemplate_(True)
    image.setSize_((18, 18))
    return image


def speaking_frames(count: int = 8):
    """Equalizer frames of the menu-bar waveform, same layout as the idle icon."""
    bars = (
        (62, 95, 173, 270),
        (120, 154, 103, 340),
        (178, 213, 39, 403),
        (236, 271, 125, 318),
        (295, 329, 77, 366),
        (353, 387, 157, 286),
    )
    x0, y0, x1, y1 = 62, 39, 387, 403
    size = 18.0
    art_w = x1 - x0 + 1
    art_h = y1 - y0 + 1
    pad = size * 0.06
    scale = min((size - pad * 2) / art_w, (size - pad * 2) / art_h)
    origin_x = (size - art_w * scale) / 2
    origin_y = (size - art_h * scale) / 2
    layout = []
    for left, right, top, bottom in bars:
        width = (right - left + 1) * scale
        cocoa_top = origin_y + (y1 - top) * scale
        cocoa_bottom = origin_y + (y1 - bottom) * scale
        layout.append(
            (
                origin_x + (left - x0) * scale,
                width,
                (cocoa_top + cocoa_bottom) / 2,
                cocoa_top - cocoa_bottom,
            )
        )

    frames = []
    for frame in range(count):
        image = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
        image.lockFocus()
        NSColor.blackColor().set()
        for index, (x, width, center, height) in enumerate(layout):
            phase = 2 * math.pi * frame / count - index * (math.pi / 3)
            factor = 0.22 + 0.78 * (0.5 + 0.5 * math.sin(phase))
            bar_h = max(width, height * factor)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, center - bar_h / 2, width, bar_h),
                width / 2,
                width / 2,
            ).fill()
        image.unlockFocus()
        image.setTemplate_(True)
        frames.append(image)
    return frames


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def support_dir() -> Path:
    path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    legacy = Path.home() / "Library" / "Application Support" / "Kokoro" / "config.json"
    config = path / "config.json"
    if not config.exists() and legacy.is_file():
        config.write_bytes(legacy.read_bytes())
    return path


def config_file() -> Path:
    return support_dir() / "config.json"


def log_file() -> Path:
    path = Path.home() / "Library" / "Logs" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path / "quicktts.log"


def log(message: str) -> None:
    line = message.rstrip()
    try:
        with log_file().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


_VOICE_LANG = {
    "a": "American",
    "b": "British",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Portuguese",
    "z": "Chinese",
}


def ensure_source_models(names: list[str]) -> None:
    if getattr(sys, "frozen", False):
        return
    from ensure_models import ensure_models

    ensure_models(names, report=log)


def voice_names() -> list[str]:
    ensure_source_models(["voices-v1.0.bin"])
    voices = np.load(app_root() / "models" / "voices-v1.0.bin")

    def sort_key(name: str):
        english = name.startswith(("af_", "am_", "bf_", "bm_"))
        return (0 if english else 1, name)

    return sorted(voices.files, key=sort_key)


def spoken_name(voice_id: str) -> str:
    name = voice_id.split("_", 1)[-1]
    if not name:
        return voice_id
    return name[:1].upper() + name[1:]


def voice_label(voice_id: str) -> str:
    prefix = voice_id.split("_", 1)[0]
    gender = "Female" if len(prefix) > 1 and prefix[1] == "f" else "Male"
    return f"{gender}-{spoken_name(voice_id)}"


def voice_menu_entries() -> list[tuple[str, str]]:
    ids = voice_names()
    labels = [voice_label(voice_id) for voice_id in ids]
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    entries = []
    for voice_id, label in zip(ids, labels):
        if counts[label] > 1:
            lang = _VOICE_LANG.get(voice_id[:1], voice_id[:1].upper())
            label = f"{label} ({lang})"
        entries.append((voice_id, label))
    return entries


def test_sentence(voice_id: str) -> str:
    return (
        f"This is {spoken_name(voice_id)} speaking a longer test sentence, "
        "so you can hear the pace, the tone, and how loud the voice sounds "
        "from the first word through to the end."
    )


def modifier_mask(names) -> int:
    bits = {name: bit for name, bit, _symbol in MODIFIER_BITS}
    mask = 0
    for name in names:
        mask |= bits.get(name, 0)
    return mask


def flags_to_names(flags: int) -> list[str]:
    return [name for name, bit, _symbol in MODIFIER_BITS if flags & bit]


def shortcut_label(key_code: int, names) -> str:
    symbols = [symbol for name, _bit, symbol in MODIFIER_BITS if name in names]
    return "".join(symbols) + key_glyph(key_code)


def key_glyph(key_code: int) -> str:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    event = Quartz.CGEventCreateKeyboardEvent(source, key_code, True)
    try:
        _count, text = Quartz.CGEventKeyboardGetUnicodeString(event, 4, None, None)
    except Exception:
        text = ""
    if text:
        return str(text).upper() if len(str(text)) == 1 else str(text)
    if key_code == GRAVE_KEY:
        return "`"
    return f"key {key_code}"


def load_config() -> tuple[dict, bool]:
    first_launch = not config_file().exists()
    config = dict(DEFAULT_CONFIG)
    if not first_launch:
        try:
            stored = json.loads(config_file().read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update(stored)
        except (OSError, json.JSONDecodeError):
            first_launch = True
    if config.get("model") not in MODEL_FILES:
        config["model"] = "fp32"
    if not isinstance(config.get("keyCode"), int):
        config["keyCode"] = GRAVE_KEY
    if not isinstance(config.get("modifiers"), list) or not config["modifiers"]:
        config["modifiers"] = ["option"]
    if not isinstance(config.get("voice"), str):
        config["voice"] = "af_heart"
    for key in ("translateEditable", "translateReadOnly"):
        value = config.get(key)
        if not isinstance(value, str) or value not in TRANSLATE_LANGUAGE_CODES:
            config.pop(key, None)
    save_config(config)
    return config, first_launch


def save_config(config: dict) -> None:
    config_file().write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def release_memory() -> None:
    gc.collect()
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        libc.malloc_zone_pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.malloc_zone_pressure_relief.restype = ctypes.c_size_t
        libc.malloc_zone_pressure_relief(None, 0)
    except Exception:
        pass


def wav_bytes(samples, sample_rate: int) -> bytes:
    import io
    import wave

    pcm = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
    if peak > 1e-4:
        pcm = pcm * min(0.9 / peak, 4.0)
    pcm = np.clip(pcm, -1.0, 1.0)
    frames = (pcm * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames.tobytes())
    return buf.getvalue()


class Engine:
    def __init__(self):
        self._lock = threading.Lock()
        self._model_id = None
        self.ready = False
        self.failed = False

    def _open(self, model_id: str):
        from kokoro_onnx import Kokoro

        filename = MODEL_FILES[model_id]
        ensure_source_models([filename, "voices-v1.0.bin"])
        path = app_root() / "models" / filename
        voices = app_root() / "models" / "voices-v1.0.bin"
        return Kokoro(str(path), str(voices))

    def load(self, model_id: str) -> None:
        self.failed = False
        with self._lock:
            kokoro = self._open(model_id)
            try:
                kokoro.create("Hello.", voice="af_heart", speed=1.0, lang="en-us")
                self._model_id = model_id
                self.ready = True
            finally:
                del kokoro
                release_memory()

    def synthesize(self, text: str, voice: str) -> bytes:
        with self._lock:
            if self._model_id is None:
                raise RuntimeError("model is not loaded")
            kokoro = self._open(self._model_id)
            try:
                if voice not in kokoro.voices:
                    voice = "af_heart"
                samples, sample_rate = kokoro.create(
                    text, voice=voice, speed=1.0, lang="en-us"
                )
                wav = wav_bytes(samples, sample_rate)
                del samples
                return wav
            finally:
                del kokoro
                release_memory()


class Player:
    def __init__(self):
        self._lock = threading.Lock()
        self._gen = 0
        self._proc = None
        self._pending: set[int] = set()

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self._pending.clear()
            self._stop_locked()
            self._clear_files()

    def busy(self) -> bool:
        with self._lock:
            playing = self._proc is not None and self._proc.poll() is None
            return playing or bool(self._pending)

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _clear_files(self) -> None:
        for path in support_dir().glob("speech-*.wav"):
            try:
                path.unlink()
            except OSError:
                pass

    def begin(self) -> int:
        with self._lock:
            self._gen += 1
            generation = self._gen
            self._pending.add(generation)
            self._stop_locked()
            return generation

    def finish(self, generation: int) -> None:
        with self._lock:
            self._pending.discard(generation)

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._gen

    def wait(self, generation: int) -> None:
        with self._lock:
            if generation != self._gen:
                return
            proc = self._proc
        if proc is not None:
            proc.wait()

    def play(self, generation: int, wav: bytes) -> bool:
        if len(wav) < 44 or not wav.startswith(b"RIFF"):
            return False
        with self._lock:
            if generation != self._gen:
                return False
            path = support_dir() / f"speech-{generation}.wav"
            path.write_bytes(wav)
            for old in support_dir().glob("speech-*.wav"):
                if old != path:
                    try:
                        old.unlink()
                    except OSError:
                        pass
            self._proc = subprocess.Popen(
                ["/usr/bin/afplay", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
            return True


class KokoroApp(NSObject):
    def init(self):
        self = objc.super(KokoroApp, self).init()
        if self is None:
            return None
        self.config, self.first_launch = load_config()
        self.engine = Engine()
        self.player = Player()
        self._load_gen = 0
        self._tap = None
        self._tap_source = None
        self._window = None
        self._recording = False
        self._monitor = None
        self._copy = None
        self._menu_proc = None
        self._menu_open = False
        self._menu_speaking = False
        self._menu_text = ""
        self._source_app = None
        self._replace_target = None
        self._replace_range = None
        self.status = None
        self._idle_image = None
        self._speak_frames = None
        self._speak_frame = 0
        self._speak_timer = None
        self.model_popup = None
        self.voice_popup = None
        self.shortcut_field = None
        self.record_button = None
        self.status_field = None
        self.editable_language_popup = None
        self.read_only_language_popup = None
        return self

    @objc.python_method
    def start(self):
        self._build_status_item()
        self._install_tap()
        self.start_load()
        if os.environ.get("QUICKTTS_SKIP_PERMISSION_PROMPT") != "1":
            AppHelper.callLater(0.4, self._prompt_accessibility)
            AppHelper.callLater(0.8, self._prompt_input_monitoring)
        if self.first_launch:
            self.show_settings()

    @objc.python_method
    def _prompt_accessibility(self):
        try:
            ApplicationServices.AXIsProcessTrustedWithOptions(
                {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
            )
        except Exception:
            log(traceback.format_exc())

    @objc.python_method
    def _prompt_input_monitoring(self):
        try:
            granted = bool(Quartz.CGPreflightListenEventAccess())
        except Exception:
            log(traceback.format_exc())
            return
        log(f"input monitoring={granted}")
        if granted:
            return
        try:
            allowed = bool(Quartz.CGRequestListenEventAccess())
            log(f"input monitoring request={allowed}")
        except Exception:
            log(traceback.format_exc())
            allowed = False
        if not allowed:
            subprocess.Popen(
                [
                    "/usr/bin/open",
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
                ]
            )

    @objc.python_method
    def _build_status_item(self):
        self.status = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        image = menu_bar_image()
        self._idle_image = image
        button = self.status.button()
        if image is not None:
            button.setImage_(image)
        else:
            button.setTitle_(APP_NAME)
        self.rebuild_menu()

    @objc.python_method
    def _begin_speaking_animation(self):
        if self._speak_timer is not None or self.status is None:
            return
        if not self.player.busy():
            return
        if not self._speak_frames:
            self._speak_frames = speaking_frames()
        self._speak_frame = 0
        button = self.status.button()
        if button is not None:
            button.setImage_(self._speak_frames[0])
        timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            0.1, self, "tickSpeaking:", None, True
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
        self._speak_timer = timer

    def tickSpeaking_(self, timer):
        del timer
        if self.status is None or not self.player.busy():
            self._end_speaking_animation()
            return
        frames = self._speak_frames
        if not frames:
            return
        self._speak_frame = (self._speak_frame + 1) % len(frames)
        button = self.status.button()
        if button is not None:
            button.setImage_(frames[self._speak_frame])

    @objc.python_method
    def _end_speaking_animation(self):
        timer = self._speak_timer
        self._speak_timer = None
        if timer is not None:
            timer.invalidate()
        if self.status is None or self._idle_image is None:
            return
        button = self.status.button()
        if button is not None:
            button.setImage_(self._idle_image)

    @objc.python_method
    def rebuild_menu(self):
        menu = NSMenu.alloc().init()
        if self.engine.ready:
            header_title = APP_NAME
        else:
            header_title = "Loading model…"
        header = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            header_title, None, ""
        )
        header.setEnabled_(False)
        menu.addItem_(header)
        speak = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Selection actions", "speakSelection:", ""
        )
        speak.setTarget_(self)
        speak.setEnabled_(self.engine.ready)
        menu.addItem_(speak)
        preview = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show actions", "showActions:", ""
        )
        preview.setTarget_(self)
        menu.addItem_(preview)
        settings = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings…", "showSettings:", ""
        )
        settings.setTarget_(self)
        menu.addItem_(settings)
        if not hotkey.ax_trusted() or self._tap is None:
            permissions = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Open Permission Settings", "openPermissions:", ""
            )
            permissions.setTarget_(self)
            menu.addItem_(permissions)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit QuickTTS", "quitApp:", ""
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.status.setMenu_(menu)

    @objc.python_method
    def set_status(self, text: str):
        if self.status_field is not None:
            self.status_field.setStringValue_(text)

    @objc.python_method
    def start_load(self):
        self._load_gen += 1
        generation = self._load_gen
        model_id = self.config["model"]
        self.engine.ready = False
        if self.status is not None:
            self.rebuild_menu()
        self.set_status("Loading model…")
        threading.Thread(
            target=self._load, args=(generation, model_id), daemon=True
        ).start()

    @objc.python_method
    def _load(self, generation: int, model_id: str):
        error = None
        try:
            self.engine.load(model_id)
            log(f"loaded {model_id}")
        except Exception:
            error = traceback.format_exc()
            self.engine.failed = True
            log(error)

        def finish():
            if generation != self._load_gen:
                return
            if error:
                self.engine.ready = False
                self.set_status("Could not load the model. See the log.")
            else:
                self.set_status("Ready")
            if self.status is not None:
                self.rebuild_menu()

        AppHelper.callAfter(finish)

    @objc.python_method
    def speak(self, text: str, *, from_menu: bool = False):
        text = " ".join(text.split())
        if not text:
            if not from_menu:
                AppHelper.callAfter(NSBeep)
            return
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
        if not from_menu and not self.engine.ready:
            AppHelper.callAfter(NSBeep)
            self.set_status("Model is still loading")
            return
        generation = self.player.begin()
        if from_menu:
            self._menu_speaking = True
        log(f"speaking {len(text)} characters")
        failed = False
        try:
            if not self._wait_ready(generation):
                if self.player.is_current(generation):
                    raise RuntimeError("The speech model is not ready.")
                return
            wav = self.engine.synthesize(text, self.config["voice"])
            if not self.player.play(generation, wav):
                if self.player.is_current(generation):
                    raise RuntimeError("Could not speak.")
                return
            del wav
            release_memory()
            AppHelper.callAfter(self._begin_speaking_animation)
            if from_menu:
                AppHelper.callAfter(
                    lambda: self._menu_send({"cmd": "speak", "phase": "playing"})
                )
            self.player.wait(generation)
        except Exception as exc:
            failed = True
            log(traceback.format_exc())
            if from_menu and self.player.is_current(generation):
                self._menu_speaking = False
                message = (
                    str(exc) if isinstance(exc, RuntimeError) else "Could not speak."
                )
                AppHelper.callAfter(
                    lambda message=message: self._menu_send(
                        {"cmd": "speak", "phase": "error", "message": message}
                    )
                )
            elif not from_menu:
                AppHelper.callAfter(NSBeep)
        finally:
            self.player.finish(generation)
        if from_menu and not failed:
            AppHelper.callAfter(
                lambda generation=generation: self._finish_menu_speak(generation)
            )

    @objc.python_method
    def _wait_ready(self, generation: int) -> bool:
        deadline = time.monotonic() + 90
        while not self.engine.ready:
            if self.engine.failed or not self.player.is_current(generation):
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return self.player.is_current(generation)

    @objc.python_method
    def _cancel_menu_speech(self) -> None:
        self.player.stop()
        release_memory()
        self._end_speaking_animation()
        self.set_status("Stopped")

    @objc.python_method
    def _finish_menu_speak(self, generation: int) -> None:
        if not self._menu_speaking or not self.player.is_current(generation):
            return
        self._menu_speaking = False
        self._close_menu()

    @objc.python_method
    def stop_speech(self):
        self._copy = None
        self._menu_speaking = False
        self._close_menu()
        self.player.stop()
        release_memory()
        self._end_speaking_animation()
        self.set_status("Stopped")
        log("stopped")

    @objc.python_method
    def handle_hotkey(self):
        if self._recording:
            return
        if self._menu_open:
            self._close_menu()
            return
        hotkey.enable_front_app_accessibility()
        text = hotkey.ax_selected_text().strip()
        if text:
            self._open_menu(text)
            return
        if self.player.busy():
            self.stop_speech()
            return
        self._begin_copy()

    @objc.python_method
    def _menu_binary(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "QuickTTSMenu"
        return Path(__file__).resolve().parent / "helper" / "QuickTTSMenu"

    @objc.python_method
    def _ensure_menu(self) -> None:
        proc = self._menu_proc
        if proc is not None and proc.poll() is None:
            return
        path = self._menu_binary()
        if not path.is_file():
            log(f"menu helper missing: {path}")
            self._menu_proc = None
            return
        proc = subprocess.Popen(
            [str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._menu_proc = proc
        threading.Thread(target=self._read_menu, args=(proc,), daemon=True).start()
        threading.Thread(target=self._drain_menu_error, args=(proc,), daemon=True).start()

    @objc.python_method
    def _menu_send(self, payload: dict) -> None:
        proc = self._menu_proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return
        try:
            proc.stdin.write((json.dumps(payload) + "\n").encode())
            proc.stdin.flush()
        except Exception:
            log(traceback.format_exc())

    @objc.python_method
    def _read_menu(self, proc: subprocess.Popen) -> None:
        stream = proc.stdout
        if stream is None:
            return
        for raw in stream:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log(f"menu: {line}")
                continue
            AppHelper.callAfter(lambda event=event: self._on_menu_event(event))
        AppHelper.callAfter(lambda: self._menu_exited(proc))

    @objc.python_method
    def _drain_menu_error(self, proc: subprocess.Popen) -> None:
        stream = proc.stderr
        if stream is None:
            return
        for raw in stream:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                log(f"menu: {line}")

    @objc.python_method
    def _menu_exited(self, proc: subprocess.Popen) -> None:
        if self._menu_proc is proc:
            self._menu_proc = None
            self._menu_open = False

    @objc.python_method
    def _open_menu(self, text: str) -> None:
        text = text.strip()
        if not text:
            NSBeep()
            return
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
        self._ensure_menu()
        if self._menu_proc is None or self._menu_proc.poll() is not None:
            NSBeep()
            self.set_status("The action menu could not open.")
            return
        self._menu_text = text
        editable = self._selection_is_editable()
        payload = {"cmd": "show", "text": text, "editable": editable}
        language = self._default_translate_language(editable)
        if language:
            payload["translateLanguage"] = language
        self._menu_open = True
        self._menu_send(payload)

    @objc.python_method
    def _close_menu(self) -> None:
        if self._menu_speaking:
            self._menu_speaking = False
            self._cancel_menu_speech()
        if not self._menu_open and (
            self._menu_proc is None or self._menu_proc.poll() is not None
        ):
            self._menu_open = False
            return
        self._menu_open = False
        self._menu_send({"cmd": "dismiss"})

    @objc.python_method
    def _copy_text(self, text: str) -> None:
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)

    @objc.python_method
    def _focused_element(self):
        if not hotkey.ax_trusted():
            return None
        system = ApplicationServices.AXUIElementCreateSystemWide()
        ApplicationServices.AXUIElementSetMessagingTimeout(system, 0.4)
        focused = hotkey._ax_value(system, ApplicationServices.kAXFocusedUIElementAttribute)
        if focused is None:
            return None
        ApplicationServices.AXUIElementSetMessagingTimeout(focused, 0.4)
        return focused

    @objc.python_method
    def _selection_is_editable(self) -> bool:
        self._source_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        hotkey.enable_front_app_accessibility()
        focused = self._focused_element()
        target = self._editable_target() if focused is not None else None
        self._replace_target = target
        self._replace_range = None
        if target is not None:
            self._replace_range = hotkey._ax_value(
                target, ApplicationServices.kAXSelectedTextRangeAttribute
            )
            return True
        # ChatGPT and Teams draw the composer inside a web view that never
        # publishes a focused text element. The selection is still live, and
        # Replace pastes over it. A focused element that is not editable, such
        # as a normal read-only page, still hides Replace.
        return focused is None and self._source_app is not None

    @objc.python_method
    def _attribute_is_settable(self, element, attribute) -> bool:
        try:
            result = ApplicationServices.AXUIElementIsAttributeSettable(
                element, attribute, None
            )
        except Exception:
            log(traceback.format_exc())
            return False
        if isinstance(result, tuple):
            return (
                bool(result)
                and int(result[0] or 0) == 0
                and len(result) > 1
                and bool(result[1])
            )
        return bool(result)

    @objc.python_method
    def _has_text_caret(self, element) -> bool:
        value = hotkey._ax_value(
            element, ApplicationServices.kAXInsertionPointLineNumberAttribute
        )
        try:
            line = int(value)
        except (TypeError, ValueError):
            return False
        return 0 <= line < 1_000_000

    @objc.python_method
    def _editable_in_chain(self, element):
        current = element
        for _ in range(10):
            if current is None:
                return None
            role = hotkey._ax_value(current, ApplicationServices.kAXRoleAttribute)
            role = str(role) if role else ""
            writable = (
                self._attribute_is_settable(
                    current, ApplicationServices.kAXSelectedTextAttribute
                )
                or self._attribute_is_settable(
                    current, ApplicationServices.kAXValueAttribute
                )
                or self._attribute_is_settable(
                    current, ApplicationServices.kAXSelectedTextRangeAttribute
                )
            )
            if role in TEXT_INPUT_ROLES and writable:
                return current
            if self._attribute_is_settable(
                current, ApplicationServices.kAXSelectedTextAttribute
            ):
                return current
            if role == "AXWebArea" and self._has_text_caret(current):
                return current
            if role in ("AXWindow", "AXApplication"):
                return None
            parent = hotkey._ax_value(current, ApplicationServices.kAXParentAttribute)
            if parent is not None:
                ApplicationServices.AXUIElementSetMessagingTimeout(parent, 0.25)
            current = parent
        return None

    @objc.python_method
    def _editable_target(self):
        hotkey.enable_front_app_accessibility()
        focused = self._focused_element()
        if focused is None:
            return None
        target = self._editable_in_chain(focused)
        if target is not None:
            return target
        current = focused
        web = None
        for _ in range(10):
            if current is None:
                break
            role = hotkey._ax_value(current, ApplicationServices.kAXRoleAttribute)
            if str(role or "") == "AXWebArea":
                web = current
                break
            if str(role or "") in ("AXWindow", "AXApplication"):
                break
            current = hotkey._ax_value(current, ApplicationServices.kAXParentAttribute)
        if web is None:
            return None
        try:
            ApplicationServices.AXUIElementSetAttributeValue(
                web, "AXEnhancedUserInterface", True
            )
        except Exception:
            log(traceback.format_exc())
            return None
        return self._editable_in_chain(self._focused_element())

    @objc.python_method
    def _ax_error(self, error) -> int:
        if isinstance(error, tuple):
            error = error[0] if error else 0
        try:
            return int(error or 0)
        except (TypeError, ValueError):
            return -1

    @objc.python_method
    def _selected_write_applied(
        self, target, text, error, before_selected, before_value, current
    ) -> bool:
        if current is not None and str(current) == text:
            return True
        if error != 0 or current is None:
            return error == 0 and current is None
        if str(current) != "":
            return False
        # Notes clears the selection after a replace, so an empty selection
        # with a changed field means the write already landed. Pasting again
        # would insert a second copy.
        after_value = hotkey._ax_value(target, ApplicationServices.kAXValueAttribute)
        if before_value is None or after_value is None:
            return True
        if str(after_value) != str(before_value):
            return True
        return str(before_selected or "") == text

    @objc.python_method
    def _write_selected_text(self, target, text: str) -> bool:
        try:
            ApplicationServices.AXUIElementSetAttributeValue(
                target, ApplicationServices.kAXFocusedAttribute, True
            )
        except Exception:
            log(traceback.format_exc())
        if self._replace_range is not None and self._attribute_is_settable(
            target, ApplicationServices.kAXSelectedTextRangeAttribute
        ):
            ApplicationServices.AXUIElementSetAttributeValue(
                target,
                ApplicationServices.kAXSelectedTextRangeAttribute,
                self._replace_range,
            )
        attribute = ApplicationServices.kAXSelectedTextAttribute
        if self._attribute_is_settable(target, attribute):
            before_selected = hotkey._ax_value(target, attribute)
            before_value = hotkey._ax_value(
                target, ApplicationServices.kAXValueAttribute
            )
            error = self._ax_error(
                ApplicationServices.AXUIElementSetAttributeValue(target, attribute, text)
            )
            current = hotkey._ax_value(target, attribute)
            if self._selected_write_applied(
                target, text, error, before_selected, before_value, current
            ):
                return True
        value = hotkey._ax_value(target, ApplicationServices.kAXValueAttribute)
        if (
            value is not None
            and str(value) == self._menu_text
            and self._attribute_is_settable(target, ApplicationServices.kAXValueAttribute)
        ):
            error = self._ax_error(
                ApplicationServices.AXUIElementSetAttributeValue(
                    target, ApplicationServices.kAXValueAttribute, text
                )
            )
            if error == 0:
                return True
        return False

    @objc.python_method
    def _paste_into_source(self, text: str) -> None:
        pasteboard = NSPasteboard.generalPasteboard()
        saved = hotkey._snapshot(pasteboard)
        self._copy_text(text)
        app = self._source_app
        pid = int(app.processIdentifier()) if app is not None else 0
        if app is not None:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

        def paste() -> None:
            if pid:
                hotkey.send_paste_to(pid)
            else:
                hotkey.send_paste()

            def restore() -> None:
                hotkey._restore(NSPasteboard.generalPasteboard(), saved)

            AppHelper.callLater(1.2, restore)

        AppHelper.callLater(0.2, paste)

    @objc.python_method
    def _replace_selection(self, text: str) -> bool:
        if not text:
            return False
        target = self._replace_target
        if target is not None and self._write_selected_text(target, text):
            log("replace wrote the selection")
            return True
        if target is None and self._source_app is None:
            return False
        log("replace pasting into the source app")
        self._paste_into_source(text)
        return True

    @objc.python_method
    def _on_menu_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "dismiss":
            self._menu_open = False
            if self._menu_speaking:
                self._menu_speaking = False
                self._cancel_menu_speech()
            return
        if kind == "speak":
            text = self._menu_text
            if text:
                threading.Thread(
                    target=self.speak,
                    args=(text,),
                    kwargs={"from_menu": True},
                    daemon=True,
                ).start()
            return
        if kind == "language":
            return
        if kind == "replace":
            self._menu_open = False
            text = str(event.get("text") or "")
            if self._replace_selection(text):
                self.set_status("Replaced")
            else:
                self._copy_text(text)
                self.set_status("Copied")
            return
        if kind == "copy":
            self._menu_open = False
            self._copy_text(str(event.get("text") or ""))
            self.set_status("Copied")

    @objc.python_method
    def _begin_copy(self):
        pasteboard = NSPasteboard.generalPasteboard()
        self._copy = {
            "before": pasteboard.changeCount(),
            "saved": hotkey._snapshot(pasteboard),
            "deadline": time.monotonic() + 0.6,
        }
        hotkey.send_copy()
        self._poll_copy()

    @objc.python_method
    def _poll_copy(self):
        if self._copy is None:
            return
        pasteboard = NSPasteboard.generalPasteboard()
        if pasteboard.changeCount() != self._copy["before"]:
            value = pasteboard.stringForType_(NSPasteboardTypeString)
            text = str(value).strip() if value else ""
            hotkey._restore(pasteboard, self._copy["saved"])
            self._copy = None
            if text:
                self._open_menu(text)
            else:
                NSBeep()
            return
        if time.monotonic() >= self._copy["deadline"]:
            self._copy = None
            NSBeep()
            return
        AppHelper.callLater(0.05, self._poll_copy)

    @objc.python_method
    def on_event(self, event_type, event):
        kind = int(event_type) & 0xFFFFFFFF
        if kind in (0xFFFFFFFE, 0xFFFFFFFF):
            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, True)
            return event
        if event is None or self._recording:
            return event
        keycode = int(
            Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        )
        if self._menu_open:
            repeat = int(
                Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventAutorepeat
                )
            )
            if keycode == 53:
                if not repeat:
                    AppHelper.callAfter(self._close_menu)
                return None
            number = MENU_KEYS.get(keycode)
            if number is not None:
                if not repeat:
                    AppHelper.callAfter(
                        lambda number=number: self._menu_send({"cmd": "key", "key": number})
                    )
                return None
        if keycode != int(self.config["keyCode"]):
            return event
        flags = int(Quartz.CGEventGetFlags(event)) & (CONTROL | OPTION | SHIFT | COMMAND)
        if flags != modifier_mask(self.config["modifiers"]):
            return event
        repeat = int(
            Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventAutorepeat
            )
        )
        if repeat:
            return None
        AppHelper.callAfter(self.handle_hotkey)
        return None

    @objc.python_method
    def _install_tap(self):
        if self._tap is not None:
            return
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
            event_callback,
            None,
        )
        if tap is None:
            try:
                granted = bool(Quartz.CGPreflightListenEventAccess())
            except Exception:
                granted = False
            log(f"event tap was not created; input monitoring={granted}")
            self.rebuild_menu()
            AppHelper.callLater(3.0, self._install_tap)
            return
        from CoreFoundation import (
            CFMachPortCreateRunLoopSource,
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            kCFRunLoopCommonModes,
        )

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self._tap = tap
        self._tap_source = source
        log("event tap installed")
        self.rebuild_menu()

    @objc.python_method
    def show_settings(self):
        if self._window is None:
            self._build_window()
        self._sync_settings_widgets()
        self._window.makeKeyAndOrderFront_(None)
        self._window.orderFrontRegardless()
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _build_window(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 520, 360),
            style,
            NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("QuickTTS Settings")
        window.setReleasedWhenClosed_(False)
        window.center()
        window.setDelegate_(self)
        content = window.contentView()
        tabs = NSTabView.alloc().initWithFrame_(content.bounds())
        general_item = NSTabViewItem.alloc().initWithIdentifier_("general")
        general_item.setLabel_("General")
        general = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 520, 300))
        self._build_general_tab(general)
        general_item.setView_(general)
        translate_item = NSTabViewItem.alloc().initWithIdentifier_("translate")
        translate_item.setLabel_("Translate")
        translate = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 520, 300))
        self._build_translate_tab(translate)
        translate_item.setView_(translate)
        tabs.addTabViewItem_(general_item)
        tabs.addTabViewItem_(translate_item)
        content.addSubview_(tabs)
        self._window = window

    @objc.python_method
    def _build_general_tab(self, content):
        content.addSubview_(self._label("Model", 24, 228, 90, 24))
        self.model_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(120, 224, 376, 28), False
        )
        for _model_id, title in MODEL_CHOICES:
            self.model_popup.addItemWithTitle_(title)
        self.model_popup.setTarget_(self)
        self.model_popup.setAction_("modelChanged:")
        content.addSubview_(self.model_popup)

        content.addSubview_(self._label("Voice", 24, 180, 90, 24))
        self.voice_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(120, 176, 376, 28), False
        )
        for voice_id, label in voice_menu_entries():
            self.voice_popup.addItemWithTitle_(label)
            self.voice_popup.lastItem().setRepresentedObject_(voice_id)
        self.voice_popup.setTarget_(self)
        self.voice_popup.setAction_("voiceChanged:")
        content.addSubview_(self.voice_popup)

        content.addSubview_(self._label("Shortcut", 24, 132, 90, 24))
        self.shortcut_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(120, 128, 180, 28)
        )
        self.shortcut_field.setEditable_(False)
        self.shortcut_field.setSelectable_(False)
        self.shortcut_field.setBezeled_(True)
        content.addSubview_(self.shortcut_field)
        self.record_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(312, 126, 184, 32)
        )
        self.record_button.setTitle_("Record shortcut")
        self.record_button.setTarget_(self)
        self.record_button.setAction_("recordShortcut:")
        content.addSubview_(self.record_button)

        hint = self._label(
            "The shortcut opens the action menu. Default is Option+`. Add Control if that dead key does not fire.",
            24,
            78,
            472,
            40,
        )
        content.addSubview_(hint)

        test = NSButton.alloc().initWithFrame_(NSMakeRect(24, 24, 140, 32))
        test.setTitle_("Test voice")
        test.setTarget_(self)
        test.setAction_("testVoice:")
        content.addSubview_(test)
        stop = NSButton.alloc().initWithFrame_(NSMakeRect(172, 24, 100, 32))
        stop.setTitle_("Stop")
        stop.setTarget_(self)
        stop.setAction_("stopSpeech:")
        content.addSubview_(stop)
        self.status_field = self._label("Ready", 284, 28, 212, 24)
        content.addSubview_(self.status_field)

    @objc.python_method
    def _build_translate_tab(self, content):
        content.addSubview_(
            self._label(
                "Choose a language for each kind of selection. Ask each time opens the language wheel.",
                24,
                230,
                472,
                40,
            )
        )
        content.addSubview_(self._label("Editable text", 24, 180, 140, 24))
        self.editable_language_popup = self._language_popup(
            NSMakeRect(180, 176, 316, 28), "translateEditableChanged:"
        )
        content.addSubview_(self.editable_language_popup)
        content.addSubview_(self._label("Read-only text", 24, 124, 140, 24))
        self.read_only_language_popup = self._language_popup(
            NSMakeRect(180, 120, 316, 28), "translateReadOnlyChanged:"
        )
        content.addSubview_(self.read_only_language_popup)
        content.addSubview_(
            self._label(
                "Editable text is a selection in a field you can type in. Read-only text cannot be changed.",
                24,
                64,
                472,
                40,
            )
        )

    @objc.python_method
    def _language_popup(self, frame, action: str):
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(frame, False)
        popup.addItemWithTitle_("Ask each time")
        popup.lastItem().setRepresentedObject_("")
        for code, title in TRANSLATE_LANGUAGES:
            popup.addItemWithTitle_(title)
            popup.lastItem().setRepresentedObject_(code)
        popup.setTarget_(self)
        popup.setAction_(action)
        return popup

    @objc.python_method
    def _default_translate_language(self, editable: bool) -> str:
        key = "translateEditable" if editable else "translateReadOnly"
        code = self.config.get(key)
        if isinstance(code, str) and code in TRANSLATE_LANGUAGE_CODES:
            return code
        return ""

    @objc.python_method
    def _label(self, text: str, x: float, y: float, width: float, height: float):
        field = NSTextField.labelWithString_(text)
        field.setFrame_(NSMakeRect(x, y, width, height))
        return field

    @objc.python_method
    def _sync_settings_widgets(self):
        title = dict(MODEL_CHOICES).get(self.config["model"], "Fast (int8)")
        self.model_popup.selectItemWithTitle_(title)
        voice = self.config["voice"]
        if not self._select_voice(voice):
            voice = "af_heart"
            self.config["voice"] = voice
            save_config(self.config)
            self._select_voice(voice)
        self.shortcut_field.setStringValue_(
            shortcut_label(self.config["keyCode"], self.config["modifiers"])
        )
        self._select_language(
            self.editable_language_popup, self.config.get("translateEditable") or ""
        )
        self._select_language(
            self.read_only_language_popup, self.config.get("translateReadOnly") or ""
        )

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        del sender
        return False

    def windowWillClose_(self, notification):
        del notification
        self._stop_recording()

    def modelChanged_(self, sender):
        title = sender.titleOfSelectedItem()
        model_id = next(model for model, name in MODEL_CHOICES if name == title)
        if model_id == self.config["model"] and self.engine.ready:
            return
        self.config["model"] = model_id
        save_config(self.config)
        self.start_load()

    @objc.python_method
    def _select_voice(self, voice_id: str) -> bool:
        for item in self.voice_popup.menu().itemArray():
            if str(item.representedObject() or "") == voice_id:
                self.voice_popup.selectItem_(item)
                return True
        return False

    @objc.python_method
    def _select_language(self, popup, code: str) -> None:
        if code not in TRANSLATE_LANGUAGE_CODES:
            code = ""
        for item in popup.menu().itemArray():
            if str(item.representedObject() or "") == code:
                popup.selectItem_(item)
                return
        popup.selectItemAtIndex_(0)

    def translateEditableChanged_(self, sender):
        self._save_translate_default("translateEditable", sender)

    def translateReadOnlyChanged_(self, sender):
        self._save_translate_default("translateReadOnly", sender)

    @objc.python_method
    def _save_translate_default(self, key: str, sender) -> None:
        code = str(sender.selectedItem().representedObject() or "")
        if code in TRANSLATE_LANGUAGE_CODES:
            self.config[key] = code
        else:
            self.config.pop(key, None)
        save_config(self.config)

    def voiceChanged_(self, sender):
        voice = str(sender.selectedItem().representedObject() or "")
        if not voice or voice == self.config["voice"]:
            return
        self.config["voice"] = voice
        save_config(self.config)

    def recordShortcut_(self, sender):
        del sender
        if self._monitor is not None:
            self._stop_recording()
            return
        self._recording = True
        self.record_button.setTitle_("Press shortcut…")
        self._monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._on_record_key
        )

    @objc.python_method
    def _on_record_key(self, event):
        keycode = int(event.keyCode())
        if keycode == 53:
            self._stop_recording()
            return None
        flags = int(event.modifierFlags()) & (CONTROL | OPTION | SHIFT | COMMAND)
        names = flags_to_names(flags)
        if not names:
            self.set_status("Include Control, Option, Shift, or Command.")
            self._stop_recording()
            return None
        self.config["keyCode"] = keycode
        self.config["modifiers"] = names
        save_config(self.config)
        self.shortcut_field.setStringValue_(shortcut_label(keycode, names))
        self.set_status("Shortcut saved")
        self._stop_recording()
        return None

    @objc.python_method
    def _stop_recording(self):
        self._recording = False
        if self._monitor is not None:
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None
        if self.record_button is not None:
            self.record_button.setTitle_("Record shortcut")

    def testVoice_(self, sender):
        del sender
        threading.Thread(
            target=self.speak,
            args=(test_sentence(self.config["voice"]),),
            daemon=True,
        ).start()

    def speakSelection_(self, sender):
        del sender
        self.handle_hotkey()

    def showActions_(self, sender):
        del sender
        value = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
        text = str(value).strip() if value else ""
        if not text:
            text = "hey can you send me that file when you get a chance thanks"
        self._open_menu(text)

    def stopSpeech_(self, sender):
        del sender
        self.stop_speech()

    def showSettings_(self, sender):
        del sender
        self.show_settings()

    def openPermissions_(self, sender):
        del sender
        subprocess.Popen(
            [
                "/usr/bin/open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ]
        )
        subprocess.Popen(
            [
                "/usr/bin/open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
            ]
        )

    def quitApp_(self, sender):
        del sender
        self.player.stop()
        proc = self._menu_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
        NSApp.terminate_(None)


def event_callback(proxy, event_type, event, refcon):
    del proxy, refcon
    if _app is None:
        return event
    try:
        return _app.on_event(event_type, event)
    except Exception:
        log(traceback.format_exc())
        return event


def self_test() -> None:
    result = Path("/tmp/kokoro-app-self-test.txt")
    engine = Engine()
    engine.load("int8")
    wav = engine.synthesize("Hello from Kokoro.", "af_heart")
    names = voice_names()
    result.write_text(f"ok bytes={len(wav)} voices={len(names)}\n", encoding="utf-8")


def main():
    global _app
    if "--self-test" in sys.argv:
        self_test()
        return
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = KokoroApp.alloc().init()
    _app = delegate
    app.setDelegate_(delegate)
    delegate.start()
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
