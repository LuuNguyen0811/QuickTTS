#!/usr/bin/env python3
"""Local Kokoro TTS. Listens on 127.0.0.1 only."""

import json
import os
import signal
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "kokoro-v1.0.int8.onnx"
VOICES = ROOT / "models" / "voices-v1.0.bin"
HOST = "127.0.0.1"
PORT = 8765
VOICE = "af_heart"
LANG = "en-us"
MAX_CHARS = 4000
MAX_BODY = 100_000

_kokoro = None
_lock = threading.Lock()


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


def load_model():
    global _kokoro
    from kokoro_onnx import Kokoro

    print(f"loading {MODEL.name} voice {VOICE}", flush=True)
    _kokoro = Kokoro(str(MODEL), str(VOICES))
    with _lock:
        _kokoro.create("Hello.", voice=VOICE, speed=1.0, lang=LANG)
    print("model ready", flush=True)


def synthesize(text: str) -> bytes:
    if _kokoro is None:
        raise RuntimeError("model is not loaded")
    with _lock:
        samples, sample_rate = _kokoro.create(
            text, voice=VOICE, speed=1.0, lang=LANG
        )
    return wav_bytes(samples, sample_rate)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/health":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        body = json.dumps({"ok": True, "voice": VOICE}).encode()
        self._send(200, body, "application/json")

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/tts":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, b"bad content length", "text/plain; charset=utf-8")
            return
        if length <= 0 or length > MAX_BODY:
            self._send(400, b"body too large or empty", "text/plain; charset=utf-8")
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            text = payload["text"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            self._send(400, b'expected {"text": "..."}', "text/plain; charset=utf-8")
            return
        if not isinstance(text, str):
            self._send(400, b"text must be a string", "text/plain; charset=utf-8")
            return
        text = text.strip()
        if not text:
            self._send(400, b"empty text", "text/plain; charset=utf-8")
            return
        if len(text) > MAX_CHARS:
            print(f"truncating {len(text)} chars to {MAX_CHARS}", flush=True)
            text = text[:MAX_CHARS]
        try:
            wav = synthesize(text)
        except ValueError as exc:
            self._send(400, str(exc).encode(), "text/plain; charset=utf-8")
            return
        except Exception:
            traceback.print_exc()
            self._send(500, b"synthesis failed", "text/plain; charset=utf-8")
            return
        self._send(200, wav, "audio/wav")

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "server.pid").write_text(str(os.getpid()))
    from ensure_models import ensure_models

    ensure_models(["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"])
    load_model()
    try:
        httpd = Server((HOST, PORT), Handler)
    except OSError as exc:
        print(f"cannot bind {HOST}:{PORT}: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    print(f"listening http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
