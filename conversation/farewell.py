"""Speak a farewell in the current Live session, then drain local playback."""
import asyncio
import base64
import math
import sys
import time
from array import array


def rms(pcm):
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0
    return math.sqrt(sum(value * value for value in samples) / len(samples))


async def say_goodnight(connection, queue):
    await asyncio.wait_for(
        connection.session.commentary.append(
            content=(
                "L'utente ha chiesto di terminare la conversazione. "
                "Pronuncia subito soltanto: Buonanotte. "
                "Poi rimani in silenzio."
            ),
            delegation_id=None,
            event_id="conversation_farewell",
        ),
        timeout=5,
    )

    started = time.monotonic()
    last_activity = started
    heard_voice = False

    while True:
        now = time.monotonic()
        if now - started >= 20:
            print("\nTempo massimo del saluto raggiunto; chiudo.", flush=True)
            return
        if heard_voice and now - last_activity >= 1.8:
            return

        try:
            event = await asyncio.wait_for(connection.recv(), timeout=0.2)
        except asyncio.TimeoutError:
            continue

        if event is None:
            raise RuntimeError("Connessione terminata durante il saluto")

        if event.type == "session.output_audio.delta":
            pcm = base64.b64decode(event.delta)
            if pcm:
                if rms(pcm) >= 120:
                    heard_voice = True
                    last_activity = time.monotonic()
                try:
                    queue.put_nowait(pcm)
                except asyncio.QueueFull:
                    raise RuntimeError("Coda audio piena durante il saluto")

        elif event.type == "session.output_transcript.delta":
            print(event.delta, end="", flush=True)
            if event.delta.strip():
                last_activity = time.monotonic()

        elif event.type == "error":
            raise RuntimeError(
                f"Live [{event.error.code}]: {event.error.message}"
            )

        elif event.type == "session.closed":
            raise RuntimeError("Sessione chiusa durante il saluto")


async def finish_playback(player, queue):
    # Called after the streaming tasks have been cancelled and awaited.
    # Flush queued audio and let aplay finish instead of terminating it.
    async with asyncio.timeout(8):
        while not queue.empty():
            player.stdin.write(queue.get_nowait())
        await player.stdin.drain()
        player.stdin.close()
        code = await player.wait()
        if code:
            raise RuntimeError(f"Riproduzione terminata con codice {code}")
