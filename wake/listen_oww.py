"""Local OpenWakeWord listener; releases the microphone before starting Live."""
import fcntl
import os
import select
import signal
import subprocess
import time
from pathlib import Path

import numpy as np
from openwakeword.model import Model


UNIT = "mentorpi-conversation.service"
MIC = os.environ.get("WAKE_MIC", "plughw:CARD=Device,DEV=0")

MODEL_NAME = os.environ.get("WAKE_OWW_MODEL", "hey_jarvis").strip()
THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.5"))

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280       # 80 ms
CHUNK_BYTES = CHUNK_SAMPLES * 2  # PCM16


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

    if state in (
        "active",
        "activating",
        "reloading",
        "deactivating",
    ):
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

    if process.stdout:
        process.stdout.close()


def reset_model(model):
    reset = getattr(model, "reset", None)
    if callable(reset):
        reset()


def listen_for_wake(model):
    reset_model(model)

    process = subprocess.Popen(
        [
            "arecord",
            "-q",
            "-D",
            MIC,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )

    next_check = 0.0
    audio_buffer = bytearray()

    print(
        f'In ascolto OpenWakeWord: "{MODEL_NAME}" '
        f"(threshold {THRESHOLD:.2f}).",
        flush=True,
    )

    try:
        while True:
            now = time.monotonic()

            if now >= next_check:
                # Se qualcuno avvia Live manualmente, libera il microfono.
                if conversation_busy():
                    return False
                next_check = now + 1.0

            readable, _, _ = select.select(
                [process.stdout], [], [], 0.2
            )

            if not readable:
                if process.poll() is not None:
                    raise RuntimeError("Il registratore si è fermato")
                continue

            data = os.read(process.stdout.fileno(), CHUNK_BYTES)

            if not data:
                raise RuntimeError(
                    "Il microfono non sta più fornendo audio"
                )

            audio_buffer.extend(data)

            while len(audio_buffer) >= CHUNK_BYTES:
                frame = bytes(audio_buffer[:CHUNK_BYTES])
                del audio_buffer[:CHUNK_BYTES]

                audio = np.frombuffer(frame, dtype=np.int16)
                scores = model.predict(audio)

                if not scores:
                    continue

                score = max(float(value) for value in scores.values())

                if score >= 0.10:
                    print(f"Wake score: {score:.3f}", flush=True)

                if score >= THRESHOLD:
                    print(
                        f"Wake rilevata: score={score:.3f}. "
                        "Libero il microfono...",
                        flush=True,
                    )
                    return True

    finally:
        stop_recorder(process)


def handle_stop(signum, frame):
    raise KeyboardInterrupt


def main():
    if not MODEL_NAME:
        raise ValueError("WAKE_OWW_MODEL è vuoto")

    if not 0.0 < THRESHOLD <= 1.0:
        raise ValueError("WAKE_THRESHOLD deve essere tra 0 e 1")

    signal.signal(signal.SIGTERM, handle_stop)

    directory = Path.home() / ".cache/mentorpi/wake"
    directory.mkdir(parents=True, exist_ok=True)

    with (directory / "listener.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Un altro ascoltatore wake è già attivo"
            )

        conversation_busy()

        print(f"Carico modello OpenWakeWord: {MODEL_NAME}", flush=True)

        model = Model(
            wakeword_models=[MODEL_NAME],
            inference_framework="onnx",
        )

        print("Modello OpenWakeWord caricato.", flush=True)

        while True:
            if conversation_busy():
                print(
                    "Conversazione in corso; ascolto wake sospeso.",
                    flush=True,
                )

                while conversation_busy():
                    time.sleep(1)

                print("Conversazione terminata.", flush=True)

            detected = listen_for_wake(model)

            # arecord è già stato chiuso qui.
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
