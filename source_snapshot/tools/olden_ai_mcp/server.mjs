#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const SERVER_NAME = "olden-ai-driver";
const SERVER_VERSION = "0.1.0";
const DEFAULT_TIMEOUT_MS = Number(process.env.OLDEN_AI_DRIVER_TIMEOUT_MS || 10000);

const instructions = [
  "Use this server only with the dedicated Olden Era AI driver bridge.",
  "Perception: focus_snapshot (SR utterance surface), hover_snapshot (raw hover), screen_dump/visible_snapshot (AI catalogs, not SR-safe).",
  "Control: ai_act (safe observed UI), plus source-prepared pilot_key / pilot_pointer_move / pilot_click.",
  "Setup: ai_grant_law_points, ai_grant_resources, ai_buy_law, ai_start_match.",
  "NVDA must consume focus_snapshot / focus_latest.json only — never screen_dump.",
  "Unproven setup and drag commands are intentionally absent until proven and documented."
].join(" ");

function parseArgs(argv) {
  const result = {};
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--bridge-dir" && argv[i + 1]) {
      result.bridgeDir = argv[++i];
    }
  }
  return result;
}

const args = parseArgs(process.argv);

function candidateBridgeDirs() {
  const dirs = [];
  if (args.bridgeDir) dirs.push(args.bridgeDir);
  if (process.env.OLDEN_AI_DRIVER_BRIDGE_DIR) dirs.push(process.env.OLDEN_AI_DRIVER_BRIDGE_DIR);
  dirs.push(path.join(process.cwd(), "Heroes of Might & Magic Olden Era Playtest", "BepInEx", "plugins", "OfflineUnlockMod", "ai_driver_bridge"));
  dirs.push(path.join(process.cwd(), "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod", "ai_driver_bridge"));
  return [...new Set(dirs.map((dir) => path.resolve(dir)))];
}

function resolveBridgeDir() {
  for (const dir of candidateBridgeDirs()) {
    if (fs.existsSync(dir)) return dir;
  }
  return path.resolve(args.bridgeDir || process.env.OLDEN_AI_DRIVER_BRIDGE_DIR || candidateBridgeDirs()[0]);
}

function readTextIfExists(file) {
  try {
    return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
  } catch {
    return null;
  }
}

function readJsonIfExists(file) {
  const text = readTextIfExists(file);
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    return { ok: false, parseError: String(error), raw: text.slice(0, 4000) };
  }
}

function bridgeInfo() {
  const bridgeDir = resolveBridgeDir();
  const tokenPath = path.join(bridgeDir, "token.txt");
  const statusPath = path.join(bridgeDir, "status.json");
  return {
    bridgeDir,
    tokenPath,
    statusPath,
    available: fs.existsSync(bridgeDir) && fs.existsSync(tokenPath),
    status: readJsonIfExists(statusPath)
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function callBridge(command, payload = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const info = bridgeInfo();
  if (!info.available) {
    return {
      ok: false,
      error: {
        code: "bridge_unavailable",
        message: "AI driver bridge is unavailable. Enable homm3AiDriverBridge or homm3_ai_driver.flag in Golden Era, then launch the game."
      },
      bridge: info
    };
  }

  const token = readTextIfExists(info.tokenPath)?.trim();
  if (!token) {
    return { ok: false, error: { code: "missing_token", message: "Bridge token file is empty." }, bridge: info };
  }

  fs.mkdirSync(path.join(info.bridgeDir, "inbox"), { recursive: true });
  fs.mkdirSync(path.join(info.bridgeDir, "outbox"), { recursive: true });

  const id = crypto.randomUUID ? crypto.randomUUID() : crypto.randomBytes(16).toString("hex");
  const requestPath = path.join(info.bridgeDir, "inbox", `${id}.json`);
  const tmpRequestPath = path.join(info.bridgeDir, "inbox", `${id}.json.${process.pid}.${Date.now()}.tmp`);
  const responsePath = path.join(info.bridgeDir, "outbox", `${id}.json`);
  const request = { id, token, command, ...payload };
  fs.writeFileSync(tmpRequestPath, JSON.stringify(request));
  fs.renameSync(tmpRequestPath, requestPath);

  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const response = readJsonIfExists(responsePath);
    if (response) {
      try {
        fs.unlinkSync(responsePath);
      } catch {
      }
      return response;
    }
    await sleep(100);
  }

  let requestCleanedUp = false;
  try {
    if (fs.existsSync(requestPath)) {
      fs.unlinkSync(requestPath);
      requestCleanedUp = true;
    }
  } catch {
  }
  try {
    if (fs.existsSync(tmpRequestPath)) fs.unlinkSync(tmpRequestPath);
  } catch {
  }

  return {
    id,
    ok: false,
    error: {
      code: "bridge_timeout",
      message: `No response from AI driver bridge within ${timeoutMs} ms.`
    },
    bridge: info,
    requestCleanedUp
  };
}

function toolSchemas() {
  return [
    {
      name: "bridge_info",
      description: "Inspect where the MCP adapter is looking for the AI driver bridge and whether it is available.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "status",
      description: "Read dedicated AI driver bridge status. Action/setup routes remain absent until proven.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "ai_observe",
      description: "Return a bounded read-only observation from the dedicated AI driver bridge. This emits legal action descriptors but does not execute input or gameplay.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {
          uiLimit: { type: "integer", minimum: 1, maximum: 256, description: "Maximum UI elements to include. Defaults to 128." }
        }
      }
    },
    {
      name: "ai_act",
      description: "Execute an input-like action emitted by the latest ai_observe after freshness and target revalidation.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["schemaVersion", "observationId", "screenId", "actionId", "targetFingerprint"],
        properties: {
          schemaVersion: { const: "ai-driver.v1.act-request" },
          observationId: { type: "string", minLength: 16 },
          screenId: { type: "string", minLength: 16 },
          actionId: { type: "string", minLength: 16 },
          targetFingerprint: {
            type: "object",
            additionalProperties: false,
            required: ["kind", "value"],
            properties: {
              kind: { type: "string", enum: ["screen_path"] },
              value: { type: "string", minLength: 1 }
            }
          }
        }
      }
    },
    {
      name: "screen_dump",
      description: "AI catalog dump of on-screen UI (selectables + optional text_only). Not screen-reader safe. dump_path fingerprints must never be passed to ai_act.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {
          elementLimit: { type: "integer", minimum: 1, maximum: 512, description: "Maximum dump elements. Defaults to 256." },
          includeTextOnly: { type: "boolean", description: "Include non-selectable TMP labels. Defaults to true." }
        }
      }
    },
    {
      name: "visible_snapshot",
      description: "Pare a live screen dump to on-screen visible candidates. Still not SR-ordered.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {
          elementLimit: { type: "integer", minimum: 1, maximum: 256, description: "Maximum visible elements. Defaults to 128." },
          includeTextOnly: { type: "boolean", description: "Include non-selectable TMP labels. Defaults to true." }
        }
      }
    },
    {
      name: "hover_snapshot",
      description: "Raw cursor hover lane (UI EventSystem + optional adventure HoverContext node). Prefer focus_snapshot for speech.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "focus_snapshot",
      description: "Screen-reader utterance surface (speechSafe + human utterance + context). NVDA must consume this, not screen_dump.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "pilot_key",
      description: "Source-prepared human-parity key injection via Win32 SendInput. Returns postHover readback.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["key"],
        properties: {
          key: { type: "string", minLength: 1, description: "A-Z, 0-9, Escape, Enter, Space, arrows, or F1-F12." },
          phase: { type: "string", enum: ["tap", "down", "up"], description: "Defaults to tap." }
        }
      }
    },
    {
      name: "pilot_pointer_move",
      description: "Source-prepared cursor move via SetCursorPos using Unity screen coordinates. Updates hover stream.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["x", "y"],
        properties: {
          x: { type: "number" },
          y: { type: "number" }
        }
      }
    },
    {
      name: "pilot_click",
      description: "Source-prepared screen-point UI click via EventSystem raycast+ExecuteEvents. Fails closed when no UI hit (map/world click unproven).",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["x", "y"],
        properties: {
          x: { type: "number" },
          y: { type: "number" },
          button: { type: "string", enum: ["left"], description: "Only left is exposed." }
        }
      }
    },
    {
      name: "ai_grant_law_points",
      description: "Grant custom faction law points through the exact native dtj.LevelUp route and return before/after state.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["factionSid"],
        properties: {
          factionSid: { type: "string", minLength: 1, description: "Custom faction SID such as homm3_dungeon." },
          count: { type: "integer", minimum: 1, maximum: 10, default: 1 }
        }
      }
    },
    {
      name: "ai_grant_resources",
      description: "Grant one exact native resource through Data.Side.res -> ResHeap.<resource> -> Resource.addValue and return before/after state.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["factionSid", "resourceName"],
        properties: {
          factionSid: { type: "string", minLength: 1, description: "Custom faction SID such as homm3_fortress." },
          resourceName: { type: "string", enum: ["gold", "wood", "ore", "gemstones", "crystals", "mercury", "dust", "graal", "starDust"] },
          amount: { type: "integer", minimum: 1, maximum: 1000000, default: 1 }
        }
      }
    },
    {
      name: "ai_buy_law",
      description: "Buy one custom faction law rank through native canApply and native law apply, returning before/after state.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["lawSid"],
        properties: {
          lawSid: { type: "string", minLength: 1, description: "Custom law SID such as fraction_law_homm3_fortress_6." },
          rank: { type: "integer", minimum: 1, maximum: 3, default: 1 }
        }
      }
    },
    {
      name: "ai_start_match",
      description: "Start the configured local match through the existing OfflineLauncherConfig startup path.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    }
  ];
}

const RESOURCE_NAMES = new Set(["gold", "wood", "ore", "gemstones", "crystals", "mercury", "dust", "graal", "starDust"]);

function invalidRequest(message) {
  return { ok: false, error: { code: "invalid_request", message } };
}

function rejectExtraKeys(args, allowedKeys, label) {
  if (!args || typeof args !== "object" || Array.isArray(args)) return { error: `${label} arguments must be an object.` };
  const allowed = new Set(allowedKeys);
  const extra = Object.keys(args).filter((key) => !allowed.has(key));
  if (extra.length > 0) return { error: `${label} has unsupported argument(s): ${extra.join(", ")}.` };
  return {};
}

function requireString(args, name) {
  const value = args?.[name];
  if (typeof value !== "string" || value.length === 0) return { error: `${name} is required and must be a non-empty string.` };
  return { value };
}

function optionalInteger(args, name, defaultValue, minimum, maximum) {
  const value = args?.[name];
  if (value === undefined) return { value: defaultValue };
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    return { error: `${name} must be an integer from ${minimum} to ${maximum}.` };
  }
  return { value };
}

function validateAiActArgs(args) {
  for (const name of ["schemaVersion", "observationId", "screenId", "actionId"]) {
    const result = requireString(args, name);
    if (result.error) return { error: result.error };
  }
  if (args.schemaVersion !== "ai-driver.v1.act-request") {
    return { error: "schemaVersion must be ai-driver.v1.act-request." };
  }
  const fingerprint = args.targetFingerprint;
  if (!fingerprint || typeof fingerprint !== "object" || Array.isArray(fingerprint)) {
    return { error: "targetFingerprint is required and must be an object." };
  }
  const fingerprintKeys = rejectExtraKeys(fingerprint, ["kind", "value"], "targetFingerprint");
  if (fingerprintKeys.error) return { error: fingerprintKeys.error };
  if (fingerprint.kind !== "screen_path") {
    return { error: "targetFingerprint.kind must be screen_path." };
  }
  if (typeof fingerprint.value !== "string" || fingerprint.value.length === 0) {
    return { error: "targetFingerprint.value is required and must be a non-empty string." };
  }
  return {
    value: {
      schemaVersion: args.schemaVersion,
      observationId: args.observationId,
      screenId: args.screenId,
      actionId: args.actionId,
      targetFingerprint: { kind: fingerprint.kind, value: fingerprint.value }
    }
  };
}

async function callTool(name, args = {}) {
  switch (name) {
    case "bridge_info": {
      const keys = rejectExtraKeys(args, [], "bridge_info");
      if (keys.error) return invalidRequest(keys.error);
      return bridgeInfo();
    }
    case "status": {
      const keys = rejectExtraKeys(args, [], "status");
      if (keys.error) return invalidRequest(keys.error);
      return callBridge("status");
    }
    case "ai_observe": {
      const keys = rejectExtraKeys(args, ["uiLimit"], "ai_observe");
      if (keys.error) return invalidRequest(keys.error);
      const uiLimit = optionalInteger(args, "uiLimit", 128, 1, 256);
      if (uiLimit.error) return invalidRequest(uiLimit.error);
      return callBridge("ai_observe", { uiLimit: uiLimit.value });
    }
    case "ai_act": {
      const request = validateAiActArgs(args);
      if (request.error) return invalidRequest(request.error);
      return callBridge("ai_act", request.value);
    }
    case "screen_dump": {
      const keys = rejectExtraKeys(args, ["elementLimit", "includeTextOnly"], "screen_dump");
      if (keys.error) return invalidRequest(keys.error);
      const elementLimit = optionalInteger(args, "elementLimit", 256, 1, 512);
      if (elementLimit.error) return invalidRequest(elementLimit.error);
      const includeTextOnly = args.includeTextOnly === undefined ? true : args.includeTextOnly;
      if (typeof includeTextOnly !== "boolean") return invalidRequest("includeTextOnly must be a boolean when provided.");
      return callBridge("screen_dump", { elementLimit: elementLimit.value, includeTextOnly });
    }
    case "visible_snapshot": {
      const keys = rejectExtraKeys(args, ["elementLimit", "includeTextOnly"], "visible_snapshot");
      if (keys.error) return invalidRequest(keys.error);
      const elementLimit = optionalInteger(args, "elementLimit", 128, 1, 256);
      if (elementLimit.error) return invalidRequest(elementLimit.error);
      const includeTextOnly = args.includeTextOnly === undefined ? true : args.includeTextOnly;
      if (typeof includeTextOnly !== "boolean") return invalidRequest("includeTextOnly must be a boolean when provided.");
      return callBridge("visible_snapshot", { elementLimit: elementLimit.value, includeTextOnly });
    }
    case "hover_snapshot": {
      const keys = rejectExtraKeys(args, [], "hover_snapshot");
      if (keys.error) return invalidRequest(keys.error);
      return callBridge("hover_snapshot");
    }
    case "focus_snapshot": {
      const keys = rejectExtraKeys(args, [], "focus_snapshot");
      if (keys.error) return invalidRequest(keys.error);
      return callBridge("focus_snapshot");
    }
    case "pilot_key": {
      const keys = rejectExtraKeys(args, ["key", "phase"], "pilot_key");
      if (keys.error) return invalidRequest(keys.error);
      const key = requireString(args, "key");
      if (key.error) return invalidRequest(key.error);
      const phase = args.phase === undefined ? "tap" : args.phase;
      if (!["tap", "down", "up"].includes(phase)) return invalidRequest("phase must be tap, down, or up.");
      return callBridge("pilot_key", { key: key.value, phase });
    }
    case "pilot_pointer_move": {
      const keys = rejectExtraKeys(args, ["x", "y"], "pilot_pointer_move");
      if (keys.error) return invalidRequest(keys.error);
      if (typeof args.x !== "number" || typeof args.y !== "number") return invalidRequest("x and y must be numbers.");
      return callBridge("pilot_pointer_move", { x: args.x, y: args.y });
    }
    case "pilot_click": {
      const keys = rejectExtraKeys(args, ["x", "y", "button"], "pilot_click");
      if (keys.error) return invalidRequest(keys.error);
      if (typeof args.x !== "number" || typeof args.y !== "number") return invalidRequest("x and y must be numbers.");
      const button = args.button === undefined ? "left" : args.button;
      if (button !== "left") return invalidRequest("button must be left.");
      return callBridge("pilot_click", { x: args.x, y: args.y, button });
    }
    case "ai_grant_law_points": {
      const keys = rejectExtraKeys(args, ["factionSid", "count"], "ai_grant_law_points");
      if (keys.error) return invalidRequest(keys.error);
      const factionSid = requireString(args, "factionSid");
      if (factionSid.error) return invalidRequest(factionSid.error);
      const count = optionalInteger(args, "count", 1, 1, 10);
      if (count.error) return invalidRequest(count.error);
      return callBridge("ai_grant_law_points", { factionSid: factionSid.value, count: count.value });
    }
    case "ai_grant_resources": {
      const keys = rejectExtraKeys(args, ["factionSid", "resourceName", "amount"], "ai_grant_resources");
      if (keys.error) return invalidRequest(keys.error);
      const factionSid = requireString(args, "factionSid");
      if (factionSid.error) return invalidRequest(factionSid.error);
      const resourceName = requireString(args, "resourceName");
      if (resourceName.error) return invalidRequest(resourceName.error);
      if (!RESOURCE_NAMES.has(resourceName.value)) return invalidRequest("resourceName is not a supported native resource.");
      const amount = optionalInteger(args, "amount", 1, 1, 1000000);
      if (amount.error) return invalidRequest(amount.error);
      return callBridge("ai_grant_resources", {
        factionSid: factionSid.value,
        resourceName: resourceName.value,
        amount: amount.value
      });
    }
    case "ai_buy_law": {
      const keys = rejectExtraKeys(args, ["lawSid", "rank"], "ai_buy_law");
      if (keys.error) return invalidRequest(keys.error);
      const lawSid = requireString(args, "lawSid");
      if (lawSid.error) return invalidRequest(lawSid.error);
      const rank = optionalInteger(args, "rank", 1, 1, 3);
      if (rank.error) return invalidRequest(rank.error);
      return callBridge("ai_buy_law", { lawSid: lawSid.value, rank: rank.value });
    }
    case "ai_start_match": {
      const keys = rejectExtraKeys(args, [], "ai_start_match");
      if (keys.error) return invalidRequest(keys.error);
      return callBridge("ai_start_match");
    }
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function resourceList() {
  const info = bridgeInfo();
  return [
    {
      uri: "olden-ai-driver://status",
      name: "AI driver bridge status",
      mimeType: "application/json",
      description: "Current status.json from the dedicated AI driver bridge, if available."
    },
    {
      uri: "olden-ai-driver://bridge-info",
      name: "AI driver MCP bridge configuration",
      mimeType: "application/json",
      description: `Adapter bridge lookup state. Current bridgeDir: ${info.bridgeDir}`
    }
  ];
}

function readResource(uri) {
  if (uri === "olden-ai-driver://bridge-info") {
    return JSON.stringify(bridgeInfo(), null, 2);
  }
  if (uri === "olden-ai-driver://status") {
    return JSON.stringify(bridgeInfo().status || { ok: false, error: "status unavailable" }, null, 2);
  }
  throw new Error(`Unknown resource: ${uri}`);
}

async function handleRequest(request) {
  const { id, method, params = {} } = request;
  if (method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: params.protocolVersion || "2024-11-05",
        capabilities: { tools: {}, resources: {} },
        serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
        instructions
      }
    };
  }
  if (method === "ping") {
    return { jsonrpc: "2.0", id, result: {} };
  }
  if (method === "tools/list") {
    return { jsonrpc: "2.0", id, result: { tools: toolSchemas() } };
  }
  if (method === "tools/call") {
    try {
      const result = await callTool(params.name, params.arguments || {});
      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          isError: Boolean(result && result.ok === false)
        }
      };
    } catch (error) {
      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: String(error?.message || error) }],
          isError: true
        }
      };
    }
  }
  if (method === "resources/list") {
    return { jsonrpc: "2.0", id, result: { resources: resourceList() } };
  }
  if (method === "resources/read") {
    try {
      return {
        jsonrpc: "2.0",
        id,
        result: {
          contents: [{ uri: params.uri, mimeType: "application/json", text: readResource(params.uri) }]
        }
      };
    } catch (error) {
      return { jsonrpc: "2.0", id, error: { code: -32602, message: String(error.message || error) } };
    }
  }
  if (method?.startsWith("notifications/")) {
    return null;
  }
  return { jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } };
}

function encodeMessage(message) {
  const body = JSON.stringify(message);
  return `Content-Length: ${Buffer.byteLength(body, "utf8")}\r\n\r\n${body}`;
}

function send(message) {
  if (!message) return;
  process.stdout.write(encodeMessage(message));
}

let buffer = Buffer.alloc(0);

function tryReadOneMessage() {
  const headerEnd = buffer.indexOf("\r\n\r\n");
  if (headerEnd === -1) return null;
  const header = buffer.subarray(0, headerEnd).toString("utf8");
  const match = /content-length:\s*(\d+)/i.exec(header);
  if (!match) {
    buffer = Buffer.alloc(0);
    throw new Error("Missing Content-Length header");
  }
  const length = Number(match[1]);
  const bodyStart = headerEnd + 4;
  const bodyEnd = bodyStart + length;
  if (buffer.length < bodyEnd) return null;
  const body = buffer.subarray(bodyStart, bodyEnd).toString("utf8");
  buffer = buffer.subarray(bodyEnd);
  return JSON.parse(body);
}

process.stdin.on("data", async (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  while (true) {
    let message;
    try {
      message = tryReadOneMessage();
    } catch (error) {
      send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: String(error.message || error) } });
      return;
    }
    if (!message) return;
    try {
      send(await handleRequest(message));
    } catch (error) {
      send({ jsonrpc: "2.0", id: message.id ?? null, error: { code: -32603, message: String(error.message || error) } });
    }
  }
});

process.stdin.resume();
