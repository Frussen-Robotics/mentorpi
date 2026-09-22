import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { GatewayClient } from "@openclaw/gateway-client";
import { PROTOCOL_VERSION } from "@openclaw/gateway-protocol/version";

let client;
let liveSessionId;
const lifecycleEvents = [];
let timer;
const secrets = [];

function credential(value) {
  if (typeof value !== "string") return undefined;
  const match = value.match(/^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$/);
  return match ? process.env[match[1]] : value;
}

try {
  const configPath = process.env.OPENCLAW_CONFIG_PATH ??
    join(process.env.OPENCLAW_STATE_DIR ?? join(homedir(), ".openclaw"),
      "openclaw.json");

  let config;
  try {
    config = JSON.parse(readFileSync(configPath, "utf8"));
  } catch {
    throw new Error(
      "Configurazione non leggibile come JSON. Fermiamoci per verificarne il formato."
    );
  }

  const auth = config.gateway?.auth ?? {};
  const token = credential(process.env.OPENCLAW_GATEWAY_TOKEN ?? auth.token);
  const password = credential(
    process.env.OPENCLAW_GATEWAY_PASSWORD ?? auth.password
  );
  secrets.push(...[token, password].filter(Boolean));

  if (!token && !password) {
    throw new Error(
      "Nessuna credenziale semplice disponibile: occorre verificare il metodo di autenticazione."
    );
  }

  const port = config.gateway?.port ?? 18789;
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("Porta Gateway non valida.");
  }

  const connected = Promise.withResolvers();
  client = new GatewayClient({
    url: `ws://127.0.0.1:${port}`,
    token,
    password,
    minProtocol: PROTOCOL_VERSION,
    maxProtocol: PROTOCOL_VERSION,
    role: "operator",
    scopes: ["operator.read", "operator.write"],
    clientDisplayName: "MentorPi Live probe",
    onEvent: event => {
      const payload = event.payload;
      const type = payload?.talkEvent?.type;
      if (["session.ready", "session.error", "session.closed"].includes(type)) {
        lifecycleEvents.push(payload);
      }
    },
    onHelloOk: hello => connected.resolve(hello),
    onConnectError: error => connected.reject(error),
  });

  timer = setTimeout(
    () => connected.reject(new Error("Timeout di connessione al Gateway.")),
    15000
  );

  client.start();
  const hello = await connected.promise;
  clearTimeout(timer);

  console.log("Connessione autenticata: OK");
  console.log("Protocollo:", hello.protocol);

  const catalog = await client.request("talk.catalog", {}, { timeoutMs: 10000 });
  console.log("Catalogo Talk accessibile: OK");
  console.log("Realtime pronto:", catalog.realtime?.ready === true);
  console.log("Provider attivo:", catalog.realtime?.activeProvider ?? "assente");

  const session = await client.request("talk.session.create", {
    sessionKey: "agent:ruben:mentorpi-test",
    provider: "openai",
    model: "gpt-live-1",
    voice: "cedar",
    mode: "realtime",
    transport: "gateway-relay",
    brain: "agent-consult",
  }, { timeoutMs: 20000 });

  liveSessionId = session.sessionId;
  if (!liveSessionId) throw new Error("Il Gateway non ha restituito sessionId.");

  console.log("Sessione creata; attendo la disponibilità del modello.");

  const deadline = Date.now() + 20000;
  let ready = false;
  while (Date.now() < deadline && !ready) {
    while (lifecycleEvents.length) {
      const payload = lifecycleEvents.shift();
      const event = payload.talkEvent;
      if (event.sessionId !== liveSessionId) continue;

      if (event.type === "session.error") {
        throw new Error(
          event.payload?.message ?? payload.message ?? "Errore del provider Live."
        );
      }
      if (event.type === "session.closed") {
        throw new Error("Sessione chiusa prima di diventare pronta.");
      }
      if (event.type === "session.ready") ready = true;
    }
    if (!ready) await new Promise(resolve => setTimeout(resolve, 50));
  }

  if (!ready) throw new Error("Timeout: GPT Live non ha segnalato session.ready.");

  console.log("GPT Live tramite OpenClaw: PRONTO");
  console.log("Sessione agente: agent:ruben:mentorpi-test");
  console.log("Formato audio:", JSON.stringify(session.audio));
} catch (error) {
  let message = String(error?.message ?? error);
  for (const secret of secrets) {
    message = message.split(secret).join("[REDACTED]");
  }
  console.error("Prova fallita:", message);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  if (client && liveSessionId) {
    try {
      await client.request("talk.session.close", {
        sessionId: liveSessionId,
      }, { timeoutMs: 10000 });
      console.log("Sessione Live chiusa: OK");
    } catch {
      console.error("Chiusura non confermata; disconnetto il client.");
      process.exitCode = 1;
    }
  }
  client?.stop();
}
