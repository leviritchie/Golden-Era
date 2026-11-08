#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const DEFAULT_PACKET = path.resolve("docs/ai_start_combat_owner_discovery_probe_packet.json");
const DEFAULT_AI_BRIDGE = "V:\\SteamLibrary\\steamapps\\common\\Heroes of Might and Magic Olden Era - Golden Era\\BepInEx\\plugins\\OfflineUnlockMod\\ai_driver_bridge";
const DEFAULT_LIVE_BRIDGE = "V:\\SteamLibrary\\steamapps\\common\\Heroes of Might and Magic Olden Era - Golden Era\\BepInEx\\plugins\\OfflineUnlockMod\\live_probe_bridge";
const ALLOWED_COMMANDS = new Set(["unity_components_by_type"]);
const CONTROL_PAYLOAD_KEYS = new Set(["id", "token", "command"]);
const OWNER_COMPONENT_TYPES = new Set([
  "Hex.Cheat.UI.BhWindowWorld",
  "Hex.Cheat.UI.BhWindowHero",
  "Hex.Cheat.UI.BhWindowMagic"
]);

function allowedPayloadKeysForCommand(command) {
  if (command === "unity_components_by_type") {
    return new Set(["componentType", "typeName", "scene", "nameContains", "pathContains", "requireActiveHierarchy", "fieldLimit", "limit"]);
  }
  throw new Error(`blocked non-owner-discovery command in packet: ${command}`);
}

function requireArgValue(argv, index, name) {
  if (index >= argv.length) throw new Error(`${name} requires a value`);
  return argv[index];
}

function parseIntegerArg(value, name, min) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min) {
    throw new Error(`${name} must be an integer >= ${min}`);
  }
  return parsed;
}

function parseArgs(argv) {
  const args = {
    packet: DEFAULT_PACKET,
    aiBridgeDir: DEFAULT_AI_BRIDGE,
    liveBridgeDir: DEFAULT_LIVE_BRIDGE,
    sampleMs: 1500,
    timeoutMs: 8000,
    out: ""
  };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--packet") args.packet = requireArgValue(argv, ++i, arg);
    else if (arg === "--ai-bridge-dir") args.aiBridgeDir = requireArgValue(argv, ++i, arg);
    else if (arg === "--live-bridge-dir") args.liveBridgeDir = requireArgValue(argv, ++i, arg);
    else if (arg === "--sample-ms") args.sampleMs = parseIntegerArg(requireArgValue(argv, ++i, arg), arg, 100);
    else if (arg === "--timeout-ms") args.timeoutMs = parseIntegerArg(requireArgValue(argv, ++i, arg), arg, 500);
    else if (arg === "--out") args.out = requireArgValue(argv, ++i, arg);
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function writeReport(outPath, report) {
  const output = JSON.stringify(report, null, 2);
  if (outPath) {
    fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
    fs.writeFileSync(path.resolve(outPath), output + "\n", "utf8");
  }
  return output;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function readStatusFileMetadata(statusPath) {
  try {
    const stat = fs.statSync(statusPath);
    return {
      statusLastWriteTimeUtc: stat.mtime.toISOString(),
      statusAgeMs: Math.max(0, Math.round(Date.now() - stat.mtimeMs))
    };
  } catch {
    return { statusLastWriteTimeUtc: null, statusAgeMs: null };
  }
}

function readStatus(bridgeDir) {
  const statusPath = path.join(path.resolve(bridgeDir), "status.json");
  try {
    return { statusPath, ...readStatusFileMetadata(statusPath), status: readJson(statusPath) };
  } catch (error) {
    return { statusPath, ...readStatusFileMetadata(statusPath), status: { ok: false, readError: String(error?.message || error) } };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function summarizeBridge(first, second, sampleMs) {
  const firstFrame = Number(first.status?.frame);
  const secondFrame = Number(second.status?.frame);
  const frameAdvanced = Number.isFinite(firstFrame) && Number.isFinite(secondFrame) && secondFrame > firstFrame;
  const statusFileStale = !frameAdvanced && Number.isFinite(second.statusAgeMs) && second.statusAgeMs > sampleMs;
  return {
    statusPath: second.statusPath,
    statusLastWriteTimeUtc: second.statusLastWriteTimeUtc,
    statusAgeMs: second.statusAgeMs,
    statusFileStale,
    ok: Boolean(first.status?.ok && second.status?.ok),
    state: second.status?.state || null,
    firstScene: first.status?.scene || null,
    secondScene: second.status?.scene || null,
    firstFrame: Number.isFinite(firstFrame) ? firstFrame : null,
    secondFrame: Number.isFinite(secondFrame) ? secondFrame : null,
    frameAdvanced
  };
}

async function checkFreshness(aiBridgeDir, liveBridgeDir, sampleMs) {
  const firstAi = readStatus(aiBridgeDir);
  const firstLive = readStatus(liveBridgeDir);
  await sleep(sampleMs);
  const secondAi = readStatus(aiBridgeDir);
  const secondLive = readStatus(liveBridgeDir);
  const ai = summarizeBridge(firstAi, secondAi, sampleMs);
  const live = summarizeBridge(firstLive, secondLive, sampleMs);
  return {
    ok: true,
    sampleMs,
    ai,
    live,
    fresh: Boolean(ai.frameAdvanced && live.frameAdvanced)
  };
}

function validateDiscoveryPayload(request) {
  if (!ALLOWED_COMMANDS.has(request.command)) {
    throw new Error(`blocked non-owner-discovery command in packet: ${request.command}`);
  }
  const payload = request.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(`request ${request.label || "(unlabeled)"} is missing discovery payload`);
  }
  const allowed = allowedPayloadKeysForCommand(request.command);
  for (const key of Object.keys(payload)) {
    if (CONTROL_PAYLOAD_KEYS.has(key)) {
      throw new Error(`blocked payload control key in request ${request.label || "(unlabeled)"}: ${key}`);
    }
    if (!allowed.has(key)) {
      throw new Error(`blocked unsupported payload key in request ${request.label || "(unlabeled)"}: ${key}`);
    }
  }
  const componentType = payload.componentType || payload.typeName;
  if (typeof componentType !== "string" || componentType.trim() === "") {
    throw new Error(`request ${request.label || "(unlabeled)"} is missing payload.componentType`);
  }
  if (!OWNER_COMPONENT_TYPES.has(componentType)) {
    throw new Error(`request ${request.label || "(unlabeled)"} uses unsupported owner component type: ${componentType}`);
  }
  if (payload.typeName !== undefined && payload.typeName !== componentType) {
    throw new Error(`request ${request.label || "(unlabeled)"} has mismatched componentType/typeName`);
  }
  if (payload.scene !== undefined && typeof payload.scene !== "string") {
    throw new Error(`request ${request.label || "(unlabeled)"} has invalid scene`);
  }
  if (payload.nameContains !== undefined && typeof payload.nameContains !== "string") {
    throw new Error(`request ${request.label || "(unlabeled)"} has invalid nameContains`);
  }
  if (payload.pathContains !== undefined && typeof payload.pathContains !== "string") {
    throw new Error(`request ${request.label || "(unlabeled)"} has invalid pathContains`);
  }
  if (payload.requireActiveHierarchy !== undefined && typeof payload.requireActiveHierarchy !== "boolean") {
    throw new Error(`request ${request.label || "(unlabeled)"} has invalid requireActiveHierarchy`);
  }
  if (payload.fieldLimit !== undefined && (!Number.isInteger(payload.fieldLimit) || payload.fieldLimit < 0 || payload.fieldLimit > 40)) {
    throw new Error(`request ${request.label || "(unlabeled)"} has invalid fieldLimit`);
  }
  if (payload.limit !== undefined && (!Number.isInteger(payload.limit) || payload.limit < 1 || payload.limit > 120)) {
    throw new Error(`request ${request.label || "(unlabeled)"} has invalid limit`);
  }
  return payload;
}

function validatePacket(packet) {
  if (packet?.schemaVersion !== "ai-start-combat-owner-discovery-probe.v1") {
    throw new Error("packet schemaVersion mismatch");
  }
  if (packet.status !== "source-prepared-only") {
    throw new Error("packet must remain source-prepared-only");
  }
  if (!packet.freshnessPreflight?.requiredBeforeLiveProbe) {
    throw new Error("packet must require freshness preflight");
  }
  if (!packet.freshnessPreflight?.command?.includes("--require-fresh")) {
    throw new Error("packet freshness preflight must use --require-fresh");
  }
  if (!Array.isArray(packet.liveProbeRequests) || packet.liveProbeRequests.length === 0) {
    throw new Error("packet has no liveProbeRequests");
  }
  for (const request of packet.liveProbeRequests) {
    validateDiscoveryPayload(request);
  }
}

async function requestLiveProbe(liveBridgeDir, request, timeoutMs) {
  const bridgeDir = path.resolve(liveBridgeDir);
  const tokenPath = path.join(bridgeDir, "token.txt");
  const inbox = path.join(bridgeDir, "inbox");
  const outbox = path.join(bridgeDir, "outbox");
  const token = fs.readFileSync(tokenPath, "utf8").trim();
  const id = randomUUID();
  const discoveryPayload = validateDiscoveryPayload(request);
  const payload = { id, token, ...discoveryPayload, command: request.command };
  const requestPath = path.join(inbox, `${id}.json`);
  const responsePath = path.join(outbox, `${id}.json`);
  fs.writeFileSync(requestPath, JSON.stringify(payload), "utf8");

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(responsePath)) return readJson(responsePath);
    await sleep(100);
  }
  let requestCleanedUp = false;
  try {
    fs.rmSync(requestPath, { force: true });
    requestCleanedUp = !fs.existsSync(requestPath);
  } catch {
    requestCleanedUp = false;
  }
  const error = new Error(`timed out waiting for live owner discovery response: ${request.label || request.command}`);
  error.code = "live_probe_timeout";
  error.requestId = id;
  error.requestPath = requestPath;
  error.requestCleanedUp = requestCleanedUp;
  error.failedRequest = { label: request.label || null, command: request.command, payload: request.payload };
  throw error;
}

let args;
try {
  args = parseArgs(process.argv);
} catch (error) {
  console.log(writeReport("", {
    ok: false,
    error: "invalid_args",
    note: "Combat owner-discovery runner argument validation failed before freshness sampling or live_probe_bridge inbox writes.",
    message: String(error?.message || error)
  }));
  process.exit(1);
}
let packet;
try {
  packet = readJson(path.resolve(args.packet));
  validatePacket(packet);
} catch (error) {
  const invalid = {
    ok: false,
    error: "invalid_packet",
    note: "Combat owner-discovery packet validation failed before freshness sampling or live_probe_bridge inbox writes.",
    message: String(error?.message || error)
  };
  console.log(writeReport(args.out, invalid));
  process.exit(1);
}
const freshness = await checkFreshness(args.aiBridgeDir, args.liveBridgeDir, args.sampleMs);
if (!freshness.fresh) {
  const blocked = {
    ok: false,
    error: "runtime_not_fresh",
    note: "AI and live bridge frames must both advance before this packet may write live_probe_bridge inbox requests.",
    freshness
  };
  console.log(writeReport(args.out, blocked));
  process.exit(1);
}

const results = [];
try {
  for (const request of packet.liveProbeRequests) {
    const response = await requestLiveProbe(args.liveBridgeDir, request, args.timeoutMs);
    results.push({ label: request.label, command: request.command, payload: request.payload, response });
  }
} catch (error) {
  if (error?.code === "live_probe_timeout") {
    const failed = {
      ok: false,
      error: "live_probe_timeout",
      note: "Live owner-discovery request timed out after freshness passed; pending live_probe_bridge inbox request was removed before exit.",
      freshness,
      failedRequest: error.failedRequest || null,
      requestId: error.requestId || null,
      requestPath: error.requestPath || null,
      requestCleanedUp: Boolean(error.requestCleanedUp),
      partialResults: results
    };
    console.log(writeReport(args.out, failed));
    process.exit(1);
  }
  throw error;
}

const report = {
  ok: true,
  schemaVersion: packet.schemaVersion,
  freshness,
  results,
  evidenceBoundary: packet.evidenceBoundary
};
console.log(writeReport(args.out, report));