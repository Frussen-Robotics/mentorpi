import asyncio
import base64
import contextlib
import os
import signal
from pathlib import Path

from openai import AsyncOpenAI
from identity import apply_identity

RATE = 24000
CHUNK_BYTES = 4800  # 100 ms, PCM16 mono
MIC = os.environ.get("CONVERSATION_MIC", "plughw:CARD=Device,DEV=0")
SPEAKER = os.environ.get("SPEAK_ALSA_DEVICE", "default")


async def stop_process(process):
    if process is None:
        return
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 2)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


async def stream_microphone(connection, recorder):
    while True:
        try:
            pcm = await recorder.stdout.readexactly(CHUNK_BYTES)
        except asyncio.IncompleteReadError:
            raise RuntimeError("La registrazione dal microfono si è interrotta")
        await connection.session.input_audio.append(
            audio=base64.b64encode(pcm).decode("ascii")
        )


async def receive_events(connection, queue):
    previous_speaker = None
    while True:
        event = await connection.recv()
        if event is None:
            raise RuntimeError("Connessione Live terminata")

        if event.type == "session.output_audio.delta":
            pcm = base64.b64decode(event.delta)
            if pcm:
                try:
                    queue.put_nowait(pcm)
                except asyncio.QueueFull:
                    raise RuntimeError("Riproduzione troppo lenta: coda audio piena")

        elif event.type in (
            "session.input_transcript.delta",
            "session.output_transcript.delta",
        ):
            speaker = (
                "Tu" if event.type == "session.input_transcript.delta"
                else "Voce"
            )
            if speaker != previous_speaker:
                print(f"\n{speaker}: ", end="", flush=True)
                previous_speaker = speaker
            print(event.delta, end="", flush=True)

        elif event.type == "error":
            raise RuntimeError(
                f"Live [{event.error.code}]: {event.error.message}"
            )

        elif event.type == "session.closed":
            raise RuntimeError("Sessione Live chiusa dal server")

        elif "delegation" in event.type:
            # This audio prototype has no backend agent.
            print(f"\n[Evento backend non gestito: {event.type}]", flush=True)


async def play_audio(player, queue):
    # Accumulate 200 ms before starting playback.
    initial = bytearray()
    while len(initial) < 9600:
        initial.extend(await queue.get())
    player.stdin.write(initial)
    await player.stdin.drain()

    while True:
        pcm = await queue.get()
        player.stdin.write(pcm)
        await player.stdin.drain()


async def watch_player(player):
    code = await player.wait()
    raise RuntimeError(f"Il lettore audio si è fermato: codice {code}")


async def wait_started(connection):
    async with asyncio.timeout(15):
        while True:
            event = await connection.recv()
            if event.type == "session.started":
                return
            if event.type == "error":
                raise RuntimeError(
                    f"Live [{event.error.code}]: {event.error.message}"
                )


async def main():
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)

    max_seconds = int(os.environ.get("CONVERSATION_MAX_SECONDS", "0"))
    if max_seconds < 0:
        raise ValueError("CONVERSATION_MAX_SECONDS deve essere >= 0")

    instructions_file = os.environ.get("CONVERSATION_INSTRUCTIONS_FILE")
    if instructions_file:
        instructions = Path(instructions_file).expanduser().read_text().strip()
        if not instructions:
            raise ValueError("Il file delle istruzioni è vuoto")
    else:
        instructions = (
            "Parla in italiano in modo naturale, caldo e conciso. "
            "Aspetta che l'utente parli per primo. "
            "Se non capisci, chiedi di ripetere senza inventare. "
            "Non interpretare rumori di fondo come parole. "
            "Non hai strumenti, memoria personale o controllo del robot. "
            "Non promettere azioni e non delegare compiti."
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY assente")

    workspace = os.environ.get("CONVERSATION_WORKSPACE")
    if workspace:
        instructions = apply_identity(instructions, workspace)

    recorder = player = None
    try:
        player = await asyncio.create_subprocess_exec(
            "aplay", "-q", "-D", SPEAKER,
            "-t", "raw", "-f", "S16_LE",
            "-r", str(RATE), "-c", "1",
            "--buffer-time=200000",
            stdin=asyncio.subprocess.PIPE,
        )

        async with AsyncOpenAI() as client:
            async with client.live.connect() as connection:
                await connection.session.start(
                    session={
                        "model": "gpt-live-1",
                        "instructions": instructions,
                        "audio": {
                            "format": {"type": "audio/pcm", "rate": RATE},
                            "output": {
                                "voice": os.environ.get("SPEAK_LIVE_VOICE", "cedar")
                            },
                        },
                        "delegation": {"type": "client"},
                        "store": False,
                    },
                    event_id="conversation_start",
                )
                try:
                    await wait_started(connection)
                    recorder = await asyncio.create_subprocess_exec(
                        "arecord", "-q", "-D", MIC,
                        "-t", "raw", "-f", "S16_LE",
                        "-r", str(RATE), "-c", "1",
                        stdout=asyncio.subprocess.PIPE,
                    )
                    print(
                        "Sessione attiva: il microfono invia audio a OpenAI.\n"
                        "Parla pure. Arresto tramite Ctrl+C o systemctl stop.",
                        flush=True,
                    )
                    queue = asyncio.Queue(maxsize=50)
                    try:
                        async with asyncio.timeout(max_seconds or None):
                            async with asyncio.TaskGroup() as group:
                                group.create_task(stream_microphone(connection, recorder))
                                group.create_task(receive_events(connection, queue))
                                group.create_task(play_audio(player, queue))
                                group.create_task(watch_player(player))
                    except TimeoutError:
                        print("\nDurata configurata raggiunta.", flush=True)
                finally:
                    await stop_process(recorder)
                    recorder = None
                    await stop_process(player)
                    player = None
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(
                            connection.session.close(event_id="conversation_close"),
                            timeout=3,
                        )
    finally:
        await stop_process(recorder)
        await stop_process(player)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nConversazione terminata.")
