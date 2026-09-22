import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { GatewayClient } from "@openclaw/gateway-client";
import { PROTOCOL_VERSION } from "@openclaw/gateway-protocol/version";

let client;
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
    scopes: ["operator.read"],
    clientDisplayName: "MentorPi connection probe",
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
} catch (error) {
  let message = String(error?.message ?? error);
  for (const secret of secrets) {
    message = message.split(secret).join("[REDACTED]");
  }
  console.error("Prova fallita:", message);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  client?.stop();
}
