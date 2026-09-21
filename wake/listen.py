"""Local wake phrase listener; releases the microphone before starting Live."""
import fcntl
import json
import os
import select
import signal
import subprocess
import time
from pathlib import Path

from vosk import Model, KaldiRecognizer

UNIT = "mentorpi-conversation.service"
MIC = os.environ.get("WAKE_MIC", "plughw:CARD=Device,DEV=0")
PHRASE = os.environ.get("WAKE_PHRASE", "ciao ruben").strip().lower()
MODEL_PATH = Path(os.environ.get(
    "WAKE_MODEL_PATH",
    str(Path.home() / ".cache/mentorpi/wake/models/vosk-model-small-it-0.22"),
)).expanduser()


def systemctl(*args):
    result = subprocess.run(
        ["systemctl", "--user", *args],
        text=True,
        capture_output=True,
        timeout=15,
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or f"systemctl failed: {result.returncode}"
        )
    return result.stdout


def conversation_busy():
    output = systemctl(
        "show", UNIT, "-p", "LoadState", "-p", "ActiveState"
    )
    fields = dict(
        line.split("=", 1) for line in output.splitlines() if "=" in line
    )
    if fields.get("LoadState") != "loaded":
        raise RuntimeError("Servizio conversazionale non installato")
    state = fields.get("ActiveState")
    if state in ("inactive", "failed"):
        return False
    if state in ("active", "activating", "reloading", "deactivating"):
        return True
    raise RuntimeError(f"Stato del servizio inatteso: {state}")


def stop_recorder(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    process.stdout.close()


def listen_for_phrase(model):
    recognizer = KaldiRecognizer(model, 16000)
    process = subprocess.Popen(
        [
            "arecord", "-q", "-D", MIC,
            "-t", "raw", "-f", "S16_LE",
            "-r", "16000", "-c", "1",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    next_check = 0.0
    print(f'In ascolto locale: di’ "{PHRASE}".', flush=True)

    try:
        while True:
            now = time.monotonic()
            if now >= next_check:
                # Also release the mic if someone starts Live manually.
                if conversation_busy():
                    return False
                next_check = now + 1

            readable, _, _ = select.select([process.stdout], [], [], 0.2)
            if not readable:
                if process.poll() is not None:
                    raise RuntimeError("Il registratore si è fermato")
                continue

            data = os.read(process.stdout.fileno(), 3200)
            if not data:
                raise RuntimeError("Il microfono non sta più fornendo audio")

            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    print(f"Vosk: {text!r}", flush=True)
                if text.lower() == PHRASE:
                    print("Frase riconosciuta. Libero il microfono...", flush=True)
                    return True
    finally:
        stop_recorder(process)


def handle_stop(signum, frame):
    raise KeyboardInterrupt


def main():
    if not PHRASE:
        raise ValueError("WAKE_PHRASE è vuota")
    if not MODEL_PATH.is_dir():
        raise ValueError(f"Modello non trovato: {MODEL_PATH}")

    signal.signal(signal.SIGTERM, handle_stop)

    directory = Path.home() / ".cache/mentorpi/wake"
    directory.mkdir(parents=True, exist_ok=True)

    with (directory / "listener.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Un altro ascoltatore wake è già attivo")

        conversation_busy()  # Verify the service before loading the model.
        model = Model(str(MODEL_PATH))

        while True:
            if conversation_busy():
                print("Conversazione in corso; ascolto wake sospeso.", flush=True)
                while conversation_busy():
                    time.sleep(1)
                print("Conversazione terminata.", flush=True)

            detected = listen_for_phrase(model)
            # The recorder has been closed before reaching this point.
            if detected:
                systemctl("start", UNIT)
                print("Avvio conversazione richiesto.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAscoltatore wake fermato.", flush=True)
    except Exception as error:
        print(f"\nErrore: {error}", flush=True)
        raise SystemExit(1)
