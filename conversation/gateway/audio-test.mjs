import { spawn } from "node:child_process";

export async function runAudioTest(client, sessionId, setHandler) {
  const finished = Promise.withResolvers();
  const children = new Set();
  const intentionalStops = new WeakSet();
  let stopping = false;
  let player;
  let statsTimer;
  let sleepTimer;
  let sleepText = "";
  let lastSpeechAt = 0;
  let closing = false;
  let farewellTimer;
  let farewellPoll;
  let lastVoiceAt = -Infinity;
  let lastOutputTextAt = -Infinity;
  let farewellHeardVoice = false;
  let drainPlayback = false;

  function observeOutputAudio(pcm) {
    let sum = 0;
    const count = Math.floor(pcm.length / 2);
    for (let i = 0; i < count; i++) {
      const sample = pcm.readInt16LE(i * 2);
      sum += sample * sample;
    }
    if (count && Math.sqrt(sum / count) >= 120) {
      lastVoiceAt = performance.now();
      if (closing) farewellHeardVoice = true;
    }
  }

  function endFarewell() {
    drainPlayback = true;
    finish();
  }

  function beginFarewell() {
    if (closing || stopping) return;
    closing = true;
    const started = performance.now();
    farewellHeardVoice = started - lastVoiceAt < 1000;
    console.log('Stop riconosciuto: attendo che Ruben finisca il saluto.');

    farewellPoll = setInterval(() => {
      const lastActivity = Math.max(started, lastVoiceAt, lastOutputTextAt);
      if (farewellHeardVoice && performance.now() - lastActivity >= 1800) {
        console.log("Pausa dopo il parlato: completo la riproduzione.");
        endFarewell();
      }
    }, 100);

    farewellTimer = setTimeout(() => {
      console.log("Tempo massimo del saluto raggiunto; chiudo.");
      endFarewell();
    }, 20000);
  }

  function observeSleepPhrase(fragment) {
    if (closing) return;
    const now = performance.now();
    if (now - lastSpeechAt >= 1200) sleepText = "";
    lastSpeechAt = now;
    clearTimeout(sleepTimer);

    sleepText += fragment;
    if (sleepText.length > 512) return;

    const words = sleepText.toLocaleLowerCase("it-IT")
      .match(/[\p{L}\p{N}]+/gu) ?? [];

    if (words.join(" ") === "notte ruben") {
      sleepTimer = setTimeout(() => {
        if (stopping) return;
        beginFarewell();
      }, 800);
    }
  }
  let captured = 0;
  let sent = 0;
  let received = 0;
  let maxRpcMs = 0;
  const started = performance.now();

  function finish(error) {
    if (!stopping) {
      stopping = true;
      finished.resolve(error);
    }
  }

  function launch(command, args, stdio) {
    const child = spawn(command, args, { stdio });
    children.add(child);
    child.on("error", () => finish(new Error(`Avvio di ${command} fallito.`)));
    child.on("close", code => {
      children.delete(child);
      if (!stopping && !intentionalStops.has(child)) {
        finish(new Error(`${command} terminato inaspettatamente: ${code}`));
      }
    });
    return child;
  }

  function startPlayer() {
    const child = launch("aplay", [
      "-q", "-D", process.env.SPEAK_ALSA_DEVICE ?? "default",
      "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1",
      "--buffer-time=200000",
    ], ["pipe", "ignore", "inherit"]);
    child.stdin.on("error", () => {
      if (!stopping && !intentionalStops.has(child)) {
        finish(new Error("Errore nella riproduzione audio."));
      }
    });
    return child;
  }

  const onSignal = () => finish();
  process.on("SIGINT", onSignal);
  process.on("SIGTERM", onSignal);

  let captureTask;
  try {
    player = startPlayer();

    setHandler(payload => {
      if (payload?.relaySessionId !== sessionId) return;

      if (!stopping && payload.type === "transcript" &&
          payload.role === "user" && payload.final === false &&
          typeof payload.text === "string") {
        observeSleepPhrase(payload.text);
      }

      // Le ultime trascrizioni possono arrivare durante la chiusura.
      if (payload.type === "transcript" && payload.final) {
        console.log(`${payload.role === "user" ? "Tu" : "Ruben"}: ${payload.text}`);
      }
      if (stopping) return;

      if (payload.type === "transcript" &&
          payload.role === "assistant" && payload.final === false &&
          typeof payload.text === "string" && payload.text.trim()) {
        lastOutputTextAt = performance.now();
      }

      if (payload.type === "audio") {
        observeOutputAudio(Buffer.from(payload.audioBase64, "base64"));
        received += Buffer.from(payload.audioBase64, "base64").length;
        if (player.stdin.writableLength > 192000) {
          finish(new Error("Riproduzione troppo lenta: buffer audio pieno."));
          return;
        }
        player.stdin.write(Buffer.from(payload.audioBase64, "base64"));
      } else if (payload.type === "clear") {
        intentionalStops.add(player);
        player.kill("SIGKILL");
        player = startPlayer();
      } else if (payload.type === "error") {
        finish(new Error(payload.message ?? "Errore della sessione Live."));
      } else if (payload.type === "close") {
        finish(new Error("La sessione Live è stata chiusa dal Gateway."));
      } else if (payload.type === "mark") {
        finish(new Error("Richiesta di conferma playback non gestita da questa prova."));
      }
    });

    const recorder = launch("arecord", [
      "-q", "-D", process.env.CONVERSATION_MIC ?? "plughw:CARD=Device,DEV=0",
      "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1",
    ], ["ignore", "pipe", "inherit"]);

    captureTask = (async () => {
      let pending = Buffer.alloc(0);
      try {
        for await (const chunk of recorder.stdout) {
          if (stopping) break;
          captured += chunk.length;
          pending = Buffer.concat([pending, chunk]);
          while (pending.length >= 4800 && !stopping) {
            const frame = pending.subarray(0, 4800);
            pending = pending.subarray(4800);
            const rpcStarted = performance.now();
            await client.request("talk.session.appendAudio", {
              sessionId,
              audioBase64: (closing ? Buffer.alloc(frame.length) : frame)
                .toString("base64"),
            }, { timeoutMs: 5000 });
            sent += frame.length;
            maxRpcMs = Math.max(maxRpcMs, performance.now() - rpcStarted);
          }
        }
        if (!stopping) finish(new Error("Flusso del microfono terminato."));
      } catch (error) {
        if (!stopping) finish(error);
      }
    })();

    console.log("\nMicrofono attivo: audio inviato a GPT Live tramite OpenClaw.");
    console.log('Parla direttamente. Di\' "Notte Ruben" o premi Ctrl+C per terminare.\n');
    statsTimer = setInterval(() => {
      console.log(
        `[audio] tempo=${((performance.now() - started) / 1000).toFixed(1)}s` +
        ` acquisito=${(captured / 48000).toFixed(1)}s` +
        ` inviato=${(sent / 48000).toFixed(1)}s` +
        ` ricevuto=${(received / 48000).toFixed(1)}s` +
        ` RPCmax=${Math.round(maxRpcMs)}ms`
      );
    }, 5000);
    const error = await finished.promise;
    if (error) throw error;
  } finally {
    stopping = true;
    clearTimeout(sleepTimer);
    clearTimeout(farewellTimer);
    clearInterval(farewellPoll);
    clearInterval(statsTimer);

    if (drainPlayback && player && children.has(player) &&
        player.stdin.writable && !player.stdin.destroyed) {
      console.log("Attendo lo svuotamento del player...");
      const drained = await new Promise(resolve => {
        const timeout = setTimeout(() => {
          player.removeListener("close", onClose);
          resolve(false);
        }, 8000);
        function onClose(code) {
          clearTimeout(timeout);
          resolve(code === 0);
        }
        player.once("close", onClose);
        player.stdin.end();
      });
      if (!drained) {
        console.error("Riproduzione finale non completata correttamente.");
        process.exitCode = 1;
      }
    }

    const waits = [...children].map(child => new Promise(resolve => {
      const killTimer = setTimeout(() => child.kill("SIGKILL"), 2000);
      child.once("close", () => {
        clearTimeout(killTimer);
        resolve();
      });
      child.kill("SIGTERM");
    }));

    await Promise.all(waits);
    await captureTask;
    process.removeListener("SIGINT", onSignal);
    process.removeListener("SIGTERM", onSignal);
  }
}
