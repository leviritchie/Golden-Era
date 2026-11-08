#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..", "..");
const serverPath = path.join(scriptDir, "server.mjs");
const metadataRunnerPath = path.join(scriptDir, "run_ai_start_combat_metadata_probe.mjs");
const freshnessCheckPath = path.join(scriptDir, "check_runtime_freshness.mjs");
const missingBridgeDir = path.join(scriptDir, "__smoke_missing_bridge__");
const timeoutBridgeDir = path.join(scriptDir, "__smoke_timeout_bridge__");
const metadataStaleAiDir = path.join(scriptDir, "__smoke_combat_metadata_stale_ai__");
const metadataStaleLiveDir = path.join(scriptDir, "__smoke_combat_metadata_stale_live__");
const metadataFreshAiDir = path.join(scriptDir, "__smoke_combat_metadata_fresh_ai__");
const metadataFreshLiveDir = path.join(scriptDir, "__smoke_combat_metadata_fresh_live__");
const metadataPoisonAiDir = path.join(scriptDir, "__smoke_combat_metadata_poison_ai__");
const metadataPoisonLiveDir = path.join(scriptDir, "__smoke_combat_metadata_poison_live__");
const metadataInvalidArgsLiveDir = path.join(scriptDir, "__smoke_combat_metadata_invalid_args_live__");
const freshnessStaleAiDir = path.join(scriptDir, "__smoke_freshness_stale_ai__");
const freshnessStaleLiveDir = path.join(scriptDir, "__smoke_freshness_stale_live__");
const freshnessFreshAiDir = path.join(scriptDir, "__smoke_freshness_fresh_ai__");
const freshnessFreshLiveDir = path.join(scriptDir, "__smoke_freshness_fresh_live__");
const aiActSchemaPath = path.join(scriptDir, "schemas", "ai_act_request.schema.json");

const expectedTools = [
  "bridge_info",
  "status",
  "ai_observe",
  "ai_act",
  "screen_dump",
  "visible_snapshot",
  "hover_snapshot",
  "focus_snapshot",
  "pilot_key",
  "pilot_pointer_move",
  "pilot_click",
  "ai_grant_law_points",
  "ai_grant_resources",
  "ai_buy_law",
  "ai_start_match"
];
const absentTools = ["ai_open_town", "ai_start_combat", "pilot_drag"];
const bridgeBackedTools = expectedTools.filter((name) => name !== "bridge_info");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function encode(message) {
  const body = JSON.stringify(message);
  return `Content-Length: ${Buffer.byteLength(body, "utf8")}\r\n\r\n${body}`;
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function comparableSchema(schema) {
  return {
    type: schema.type,
    additionalProperties: schema.additionalProperties,
    required: schema.required,
    properties: schema.properties
  };
}

function decodeAvailable(state) {
  const messages = [];
  while (true) {
    const headerEnd = state.buffer.indexOf("\r\n\r\n");
    if (headerEnd === -1) break;
    const header = state.buffer.subarray(0, headerEnd).toString("utf8");
    const match = /content-length:\s*(\d+)/i.exec(header);
    assert(match, `missing Content-Length in response header: ${header}`);
    const length = Number(match[1]);
    const bodyStart = headerEnd + 4;
    const bodyEnd = bodyStart + length;
    if (state.buffer.length < bodyEnd) break;
    const body = state.buffer.subarray(bodyStart, bodyEnd).toString("utf8");
    state.buffer = state.buffer.subarray(bodyEnd);
    messages.push(JSON.parse(body));
  }
  return messages;
}

function startServer(bridgeDir, extraEnv = {}) {
  const child = spawn(process.execPath, [serverPath, "--bridge-dir", bridgeDir], {
    cwd: repoRoot,
    env: { ...process.env, ...extraEnv },
    stdio: ["pipe", "pipe", "pipe"]
  });

  const state = { buffer: Buffer.alloc(0), responses: new Map(), stderr: "", nextId: 1 };
  child.stdout.on("data", (chunk) => {
    state.buffer = Buffer.concat([state.buffer, chunk]);
    for (const message of decodeAvailable(state)) {
      state.responses.set(message.id, message);
    }
  });
  child.stderr.on("data", (chunk) => {
    state.stderr += chunk.toString("utf8");
  });

  async function request(method, params = {}, timeoutMs = 5000) {
    const id = state.nextId++;
    child.stdin.write(encode({ jsonrpc: "2.0", id, method, params }));
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (state.responses.has(id)) return state.responses.get(id);
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
    throw new Error(`timed out waiting for ${method}; stderr=${state.stderr}`);
  }

  function stop() {
    child.kill();
  }

  return { child, request, stop };
}

function ensureRemoved(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitForExit(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("timed out waiting for child process exit"));
    }, timeoutMs);
    child.on("exit", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}
function writeReadyStatus(dir, frame) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "status.json"), JSON.stringify({
    ok: true,
    state: "ready",
    scene: "cityDungeon",
    frame
  }), "utf8");
}

async function main() {
  ensureRemoved(missingBridgeDir);
  ensureRemoved(timeoutBridgeDir);
  ensureRemoved(metadataStaleAiDir);
  ensureRemoved(metadataStaleLiveDir);
  ensureRemoved(metadataPoisonAiDir);
  ensureRemoved(metadataPoisonLiveDir);
  ensureRemoved(metadataInvalidArgsLiveDir);

  const missing = startServer(missingBridgeDir);
  try {
    const init = await missing.request("initialize", { protocolVersion: "2024-11-05" });
    assert(init.result?.serverInfo?.name === "olden-ai-driver", "initialize returned wrong server name");

    const tools = await missing.request("tools/list");
    const toolNames = tools.result?.tools?.map((tool) => tool.name) || [];
    assert(JSON.stringify(toolNames) === JSON.stringify(expectedTools), `tool list drifted: ${JSON.stringify(toolNames)}`);
    for (const name of absentTools) {
      assert(!toolNames.includes(name), `unproven tool leaked into MCP smoke surface: ${name}`);
    }

    const aiActTool = tools.result.tools.find((tool) => tool.name === "ai_act");
    const aiActFingerprintKinds = aiActTool?.inputSchema?.properties?.targetFingerprint?.properties?.kind?.enum || [];
    assert(JSON.stringify(aiActFingerprintKinds) === JSON.stringify(["screen_path"]), `ai_act input schema must advertise only screen_path fingerprints: ${JSON.stringify(aiActFingerprintKinds)}`);
    const aiActRequestSchema = JSON.parse(fs.readFileSync(aiActSchemaPath, "utf8"));
    assert(stableStringify(comparableSchema(aiActTool.inputSchema)) === stableStringify(comparableSchema(aiActRequestSchema)), "ai_act tools/list input schema drifted from schemas/ai_act_request.schema.json");

    const toolByName = new Map(tools.result.tools.map((tool) => [tool.name, tool]));
    function assertEmptyObjectToolSchema(name) {
      const schema = toolByName.get(name)?.inputSchema;
      assert(schema?.type === "object", `${name} input schema must stay an object`);
      assert(schema?.additionalProperties === false, `${name} input schema must reject extra properties`);
      assert(Object.keys(schema?.properties || {}).length === 0, `${name} input schema must stay argument-free`);
      assert(!schema?.required || schema.required.length === 0, `${name} input schema must not grow required args`);
    }
    for (const name of ["bridge_info", "status", "ai_start_match", "hover_snapshot", "focus_snapshot"]) {
      assertEmptyObjectToolSchema(name);
    }

    const observeSchema = toolByName.get("ai_observe")?.inputSchema;
    assert(observeSchema?.additionalProperties === false, "ai_observe input schema must reject extra properties");
    assert(observeSchema?.properties?.uiLimit?.minimum === 1 && observeSchema.properties.uiLimit.maximum === 256, "ai_observe uiLimit bounds drifted");

    const dumpSchema = toolByName.get("screen_dump")?.inputSchema;
    assert(dumpSchema?.additionalProperties === false, "screen_dump input schema must reject extra properties");
    assert(dumpSchema?.properties?.elementLimit?.minimum === 1 && dumpSchema.properties.elementLimit.maximum === 512, "screen_dump elementLimit bounds drifted");

    const visibleSchema = toolByName.get("visible_snapshot")?.inputSchema;
    assert(visibleSchema?.additionalProperties === false, "visible_snapshot input schema must reject extra properties");
    assert(visibleSchema?.properties?.elementLimit?.minimum === 1 && visibleSchema.properties.elementLimit.maximum === 256, "visible_snapshot elementLimit bounds drifted");

    const pilotKeySchema = toolByName.get("pilot_key")?.inputSchema;
    assert(JSON.stringify(pilotKeySchema?.required) === JSON.stringify(["key"]), "pilot_key required args drifted");
    assert(pilotKeySchema?.additionalProperties === false, "pilot_key must reject extra properties");

    const pilotClickSchema = toolByName.get("pilot_click")?.inputSchema;
    assert(JSON.stringify(pilotClickSchema?.required) === JSON.stringify(["x", "y"]), "pilot_click required args drifted");
    assert(pilotClickSchema?.additionalProperties === false, "pilot_click must reject extra properties");

    const lawPointSchema = toolByName.get("ai_grant_law_points")?.inputSchema;
    assert(JSON.stringify(lawPointSchema?.required) === JSON.stringify(["factionSid"]), "ai_grant_law_points required args drifted");
    assert(lawPointSchema?.additionalProperties === false, "ai_grant_law_points must reject extra properties");
    assert(lawPointSchema?.properties?.count?.minimum === 1 && lawPointSchema.properties.count.maximum === 10, "ai_grant_law_points count bounds drifted");

    const resourceSchema = toolByName.get("ai_grant_resources")?.inputSchema;
    assert(JSON.stringify(resourceSchema?.required) === JSON.stringify(["factionSid", "resourceName"]), "ai_grant_resources required args drifted");
    assert(resourceSchema?.additionalProperties === false, "ai_grant_resources must reject extra properties");
    assert(JSON.stringify(resourceSchema?.properties?.resourceName?.enum) === JSON.stringify(["gold", "wood", "ore", "gemstones", "crystals", "mercury", "dust", "graal", "starDust"]), "ai_grant_resources native resource enum drifted");
    assert(resourceSchema?.properties?.amount?.minimum === 1 && resourceSchema.properties.amount.maximum === 1000000, "ai_grant_resources amount bounds drifted");

    const buyLawSchema = toolByName.get("ai_buy_law")?.inputSchema;
    assert(JSON.stringify(buyLawSchema?.required) === JSON.stringify(["lawSid"]), "ai_buy_law required args drifted");
    assert(buyLawSchema?.additionalProperties === false, "ai_buy_law must reject extra properties");
    assert(buyLawSchema?.properties?.rank?.minimum === 1 && buyLawSchema.properties.rank.maximum === 3, "ai_buy_law rank bounds drifted");

    const resources = await missing.request("resources/list");
    const resourceUris = resources.result?.resources?.map((resource) => resource.uri) || [];
    assert(resourceUris.includes("olden-ai-driver://bridge-info"), "bridge-info resource missing");
    assert(resourceUris.includes("olden-ai-driver://status"), "status resource missing");

    const bridgeInfoResource = await missing.request("resources/read", { uri: "olden-ai-driver://bridge-info" });
    const bridgeInfoText = bridgeInfoResource.result?.contents?.[0]?.text || "";
    const bridgeInfo = JSON.parse(bridgeInfoText);
    assert(path.resolve(bridgeInfo.bridgeDir) === path.resolve(missingBridgeDir), "explicit bridge-dir was not honored");
    assert(bridgeInfo.available === false, "missing smoke bridge should be unavailable");

    const statusResource = await missing.request("resources/read", { uri: "olden-ai-driver://status" });
    const statusText = statusResource.result?.contents?.[0]?.text || "";
    const statusPayload = JSON.parse(statusText);
    assert(statusPayload.ok === false && statusPayload.error === "status unavailable", `missing bridge status resource should fail closed: ${statusText}`);
    assert(!fs.existsSync(path.join(missingBridgeDir, "inbox")), "status resource read should not create bridge inbox requests");

    const unknownResource = await missing.request("resources/read", { uri: "olden-ai-driver://unknown" });
    assert(unknownResource.error?.code === -32602, "unknown resource should fail closed locally as a JSON-RPC invalid params error");
    assert(unknownResource.error?.message?.includes("Unknown resource: olden-ai-driver://unknown"), "unknown resource rejection should explain the resource URI");
    assert(!fs.existsSync(path.join(missingBridgeDir, "inbox")), "unknown resource read should not create bridge inbox requests");

    const validBridgeArgs = {
      status: {},
      ai_observe: {},
      ai_act: {
        schemaVersion: "ai-driver.v1.act-request",
        observationId: "observation-0001",
        screenId: "screen-000000001",
        actionId: "action-000000001",
        targetFingerprint: { kind: "screen_path", value: "screen/path/Button" }
      },
      screen_dump: {},
      visible_snapshot: {},
      hover_snapshot: {},
      focus_snapshot: {},
      pilot_key: { key: "Escape" },
      pilot_pointer_move: { x: 10, y: 10 },
      pilot_click: { x: 10, y: 10 },
      ai_grant_law_points: { factionSid: "homm3_fortress" },
      ai_grant_resources: { factionSid: "homm3_fortress", resourceName: "wood" },
      ai_buy_law: { lawSid: "fraction_law_homm3_fortress_6" },
      ai_start_match: {}
    };
    for (const name of bridgeBackedTools) {
      const unavailable = await missing.request("tools/call", { name, arguments: validBridgeArgs[name] });
      assert(unavailable.result?.isError === true, `${name} against tokenless smoke bridge should fail closed`);
      const payload = JSON.parse(unavailable.result.content[0].text);
      assert(payload.error?.code === "bridge_unavailable", `unexpected ${name} error: ${JSON.stringify(payload)}`);
      assert(path.resolve(payload.bridge?.bridgeDir || "") === path.resolve(missingBridgeDir), `${name} did not report explicit bridge-dir`);
      assert(!fs.existsSync(path.join(missingBridgeDir, "inbox")), `${name} bridge_unavailable should not create inbox requests`);
    }

    for (const name of absentTools) {
      const rejected = await missing.request("tools/call", { name, arguments: {} });
      assert(rejected.result?.isError === true, `${name} should fail closed as an unknown tool`);
      const rejectedText = rejected.result?.content?.[0]?.text || "";
      assert(rejectedText === `Unknown tool: ${name}`, `${name} rejection should be concise and explain the unknown tool`);
      assert(!rejectedText.includes("\n") && !rejectedText.includes(" at "), `${name} rejection should not include a stack trace`);
      assert(!fs.existsSync(path.join(missingBridgeDir, "inbox")), `${name} rejection should not create bridge inbox requests`);
    }
  } finally {
    missing.stop();
  }

  fs.mkdirSync(timeoutBridgeDir, { recursive: true });
  fs.writeFileSync(path.join(timeoutBridgeDir, "token.txt"), "smoke-token\n");
  const timeout = startServer(timeoutBridgeDir, { OLDEN_AI_DRIVER_TIMEOUT_MS: "150" });
  try {
    const malformedRequests = [
      { name: "ai_act", arguments: { schemaVersion: "ai-driver.v1.act-request" }, label: "malformed ai_act" },
      { name: "ai_grant_law_points", arguments: {}, label: "missing factionSid law point grant" },
      { name: "ai_grant_resources", arguments: { factionSid: "homm3_fortress", resourceName: "invalid_resource" }, label: "invalid resource grant" },
      { name: "ai_buy_law", arguments: { lawSid: "fraction_law_homm3_fortress_6", rank: 0 }, label: "invalid law rank" },
      { name: "ai_observe", arguments: { uiLimit: 999 }, label: "invalid observe limit" },
      { name: "status", arguments: { unexpected: true }, label: "extra status argument" },
      { name: "ai_grant_law_points", arguments: { factionSid: "homm3_fortress", extra: "ignored-before" }, label: "extra law point argument" },
      {
        name: "ai_act",
        arguments: {
          schemaVersion: "ai-driver.v1.act-request",
          observationId: "observation-0001",
          screenId: "screen-000000001",
          actionId: "action-000000001",
          targetFingerprint: { kind: "screen_path", value: "screen/path/Button", extra: "ignored-before" }
        },
        label: "extra ai_act fingerprint argument"
      },
      {
        name: "ai_act",
        arguments: {
          schemaVersion: "ai-driver.v1.act-request",
          observationId: "observation-0001",
          screenId: "screen-000000001",
          actionId: "action-000000001",
          targetFingerprint: { kind: "runtime_instance_id", value: "12345" }
        },
        label: "unsupported ai_act fingerprint kind"
      }
    ];
    for (const malformed of malformedRequests) {
      const rejected = await timeout.request("tools/call", { name: malformed.name, arguments: malformed.arguments }, 3000);
      assert(rejected.result?.isError === true, `${malformed.label} should fail closed locally`);
      const rejectedPayload = JSON.parse(rejected.result.content[0].text);
      assert(rejectedPayload.error?.code === "invalid_request", `${malformed.label} should return invalid_request: ${JSON.stringify(rejectedPayload)}`);
      const inbox = path.join(timeoutBridgeDir, "inbox");
      const pending = fs.existsSync(inbox) ? fs.readdirSync(inbox).filter((name) => name.endsWith(".json") || name.includes(".tmp")) : [];
      assert(pending.length === 0, `${malformed.label} should not create bridge inbox requests, found: ${pending.join(",")}`);
    }

    const timedOut = await timeout.request("tools/call", { name: "status", arguments: {} }, 3000);
    assert(timedOut.result?.isError === true, "tokened nonresponsive bridge should fail closed on timeout");
    const payload = JSON.parse(timedOut.result.content[0].text);
    assert(payload.error?.code === "bridge_timeout", `unexpected timeout payload: ${JSON.stringify(payload)}`);
    assert(payload.requestCleanedUp === true, "bridge timeout should report that the pending inbox request was cleaned up");
    const inbox = path.join(timeoutBridgeDir, "inbox");
    const pending = fs.existsSync(inbox) ? fs.readdirSync(inbox).filter((name) => name.endsWith(".json") || name.includes(".tmp")) : [];
    assert(pending.length === 0, `bridge timeout should remove pending inbox requests, found: ${pending.join(",")}`);
  } finally {
    timeout.stop();
    ensureRemoved(timeoutBridgeDir);
  }


  writeReadyStatus(freshnessStaleAiDir, 501);
  writeReadyStatus(freshnessStaleLiveDir, 601);
  try {
    const staleFreshness = spawnSync(process.execPath, [
      freshnessCheckPath,
      "--ai-bridge-dir",
      freshnessStaleAiDir,
      "--live-bridge-dir",
      freshnessStaleLiveDir,
      "--sample-ms",
      "100",
      "--require-fresh"
    ], {
      cwd: repoRoot,
      encoding: "utf8"
    });
    assert(staleFreshness.status === 1, `freshness --require-fresh should exit 1 for stale frames; stdout=${staleFreshness.stdout} stderr=${staleFreshness.stderr}`);
    const staleFreshnessPayload = JSON.parse(staleFreshness.stdout);
    assert(staleFreshnessPayload.fresh === false, `freshness stale hard gate should report fresh=false: ${staleFreshness.stdout}`);
    assert(staleFreshnessPayload.ai?.statusFileStale === true, `freshness stale hard gate should flag stale AI status: ${staleFreshness.stdout}`);
    assert(!fs.existsSync(path.join(freshnessStaleAiDir, "inbox")), "freshness stale hard gate should not create AI inbox requests");
    assert(!fs.existsSync(path.join(freshnessStaleLiveDir, "inbox")), "freshness stale hard gate should not create live inbox requests");
  } finally {
    ensureRemoved(freshnessStaleAiDir);
    ensureRemoved(freshnessStaleLiveDir);
  }

  writeReadyStatus(freshnessFreshAiDir, 701);
  writeReadyStatus(freshnessFreshLiveDir, 801);
  try {
    const freshFreshness = spawn(process.execPath, [
      freshnessCheckPath,
      "--ai-bridge-dir",
      freshnessFreshAiDir,
      "--live-bridge-dir",
      freshnessFreshLiveDir,
      "--sample-ms",
      "300",
      "--require-fresh"
    ], {
      cwd: repoRoot,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let freshFreshnessStdout = "";
    let freshFreshnessStderr = "";
    freshFreshness.stdout.on("data", (chunk) => { freshFreshnessStdout += chunk.toString("utf8"); });
    freshFreshness.stderr.on("data", (chunk) => { freshFreshnessStderr += chunk.toString("utf8"); });
    let hardGateAiFrame = 701;
    let hardGateLiveFrame = 801;
    const hardGateTicker = setInterval(() => {
      hardGateAiFrame += 1;
      hardGateLiveFrame += 1;
      writeReadyStatus(freshnessFreshAiDir, hardGateAiFrame);
      writeReadyStatus(freshnessFreshLiveDir, hardGateLiveFrame);
    }, 50);
    const freshFreshnessExit = await waitForExit(freshFreshness, 3000);
    clearInterval(hardGateTicker);
    assert(freshFreshnessExit === 0, `freshness --require-fresh should exit 0 for advancing frames; stdout=${freshFreshnessStdout} stderr=${freshFreshnessStderr}`);
    assert(freshFreshnessStderr.trim() === "", `freshness fresh hard gate should not write stderr: ${freshFreshnessStderr}`);
    const freshFreshnessPayload = JSON.parse(freshFreshnessStdout);
    assert(freshFreshnessPayload.fresh === true, `freshness fresh hard gate should report fresh=true: ${freshFreshnessStdout}`);
    assert(freshFreshnessPayload.ai?.statusFileStale === false, `freshness fresh hard gate should not flag stale AI status: ${freshFreshnessStdout}`);
  } finally {
    ensureRemoved(freshnessFreshAiDir);
    ensureRemoved(freshnessFreshLiveDir);
  }

  writeReadyStatus(metadataStaleAiDir, 101);
  writeReadyStatus(metadataStaleLiveDir, 201);
  fs.mkdirSync(path.join(metadataStaleLiveDir, "inbox"), { recursive: true });
  fs.mkdirSync(path.join(metadataStaleLiveDir, "outbox"), { recursive: true });
  const staleOutPath = path.join(metadataStaleLiveDir, "stale-report.json");
  try {
    const staleMetadata = spawnSync(process.execPath, [
      metadataRunnerPath,
      "--ai-bridge-dir",
      metadataStaleAiDir,
      "--live-bridge-dir",
      metadataStaleLiveDir,
      "--sample-ms",
      "100",
      "--out",
      staleOutPath
    ], {
      cwd: repoRoot,
      encoding: "utf8"
    });
    assert(staleMetadata.status === 1, `combat metadata runner stale freshness should fail closed; stdout=${staleMetadata.stdout} stderr=${staleMetadata.stderr}`);
    const stalePayload = JSON.parse(staleMetadata.stdout);
    assert(stalePayload.error === "runtime_not_fresh", `combat metadata runner should report runtime_not_fresh: ${staleMetadata.stdout}`);
    const staleOutPayload = JSON.parse(fs.readFileSync(staleOutPath, "utf8"));
    assert(staleOutPayload.error === "runtime_not_fresh", `combat metadata stale --out report should preserve runtime_not_fresh: ${JSON.stringify(staleOutPayload)}`);
    assert(stalePayload.freshness?.ai?.frameAdvanced === false, "combat metadata stale AI frame should not advance");
    assert(typeof stalePayload.freshness?.ai?.statusAgeMs === "number", "combat metadata stale report should include AI statusAgeMs");
    assert(stalePayload.freshness?.ai?.statusFileStale === true, "combat metadata stale report should flag stale AI status file");
    assert(typeof stalePayload.freshness?.live?.statusLastWriteTimeUtc === "string", "combat metadata stale report should include live statusLastWriteTimeUtc");
    assert(stalePayload.freshness?.live?.frameAdvanced === false, "combat metadata stale live frame should not advance");
    const liveInbox = path.join(metadataStaleLiveDir, "inbox");
    const liveRequests = fs.readdirSync(liveInbox).filter((name) => name.endsWith(".json") || name.includes(".tmp"));
    assert(liveRequests.length === 0, `combat metadata stale runner should not create live inbox requests, found: ${liveRequests.join(",")}`);
  } finally {
    ensureRemoved(metadataStaleAiDir);
    ensureRemoved(metadataStaleLiveDir);
  ensureRemoved(metadataPoisonAiDir);
  ensureRemoved(metadataPoisonLiveDir);
  ensureRemoved(metadataInvalidArgsLiveDir);
  }

  fs.mkdirSync(path.join(metadataInvalidArgsLiveDir, "inbox"), { recursive: true });
  try {
    const invalidArgsMetadata = spawnSync(process.execPath, [
      metadataRunnerPath,
      "--live-bridge-dir",
      metadataInvalidArgsLiveDir,
      "--sample-ms",
      "0"
    ], {
      cwd: repoRoot,
      encoding: "utf8"
    });
    assert(invalidArgsMetadata.status === 1, `combat metadata invalid sample-ms should fail closed; stdout=${invalidArgsMetadata.stdout} stderr=${invalidArgsMetadata.stderr}`);
    assert(invalidArgsMetadata.stderr.trim() === "", `combat metadata invalid args should be structured stdout JSON, not stderr stack text: ${invalidArgsMetadata.stderr}`);
    const invalidArgsPayload = JSON.parse(invalidArgsMetadata.stdout);
    assert(invalidArgsPayload.error === "invalid_args", `combat metadata invalid args should report invalid_args: ${invalidArgsMetadata.stdout}`);
    assert(invalidArgsPayload.message.includes("--sample-ms must be an integer >= 100"), `combat metadata invalid args should explain sample-ms minimum: ${invalidArgsMetadata.stdout}`);
    const invalidArgsRequests = fs.readdirSync(path.join(metadataInvalidArgsLiveDir, "inbox")).filter((name) => name.endsWith(".json") || name.includes(".tmp"));
    assert(invalidArgsRequests.length === 0, `combat metadata invalid args should not create live inbox requests, found: ${invalidArgsRequests.join(",")}`);
  } finally {
    ensureRemoved(metadataInvalidArgsLiveDir);
  }

  fs.mkdirSync(path.join(metadataPoisonLiveDir, "inbox"), { recursive: true });
  fs.mkdirSync(path.join(metadataPoisonLiveDir, "outbox"), { recursive: true });
  const poisonPacketPath = path.join(metadataPoisonLiveDir, "poison-packet.json");
  const poisonOutPath = path.join(metadataPoisonLiveDir, "poison-report.json");
  fs.writeFileSync(poisonPacketPath, JSON.stringify({
    schemaVersion: "ai-start-combat-live-metadata-probe.v1",
    status: "source-prepared-only",
    freshnessPreflight: {
      requiredBeforeLiveProbe: true,
      command: "node tools\\olden_ai_mcp\\check_runtime_freshness.mjs --sample-ms 100 --require-fresh"
    },
    liveProbeRequests: [{
      label: "poison command override",
      command: "method_signatures",
      payload: {
        typeName: "ObjectPublicInciObInciBoObStInciUnique",
        command: "volatile_reflection_invoke",
        limit: 1
      }
    }]
  }), "utf8");
  try {
    const poisonMetadata = spawnSync(process.execPath, [
      metadataRunnerPath,
      "--packet",
      poisonPacketPath,
      "--ai-bridge-dir",
      metadataPoisonAiDir,
      "--live-bridge-dir",
      metadataPoisonLiveDir,
      "--sample-ms",
      "100",
      "--out",
      poisonOutPath
    ], {
      cwd: repoRoot,
      encoding: "utf8"
    });
    assert(poisonMetadata.status === 1, `combat metadata poison payload command override should fail closed; stdout=${poisonMetadata.stdout} stderr=${poisonMetadata.stderr}`);
    assert(poisonMetadata.stderr.trim() === "", `combat metadata poison payload should be structured stdout JSON, not stderr stack text: ${poisonMetadata.stderr}`);
    const poisonPayload = JSON.parse(poisonMetadata.stdout);
    assert(poisonPayload.error === "invalid_packet", `combat metadata poison payload should report invalid_packet: ${poisonMetadata.stdout}`);
    const poisonOutPayload = JSON.parse(fs.readFileSync(poisonOutPath, "utf8"));
    assert(poisonOutPayload.error === "invalid_packet", `combat metadata poison --out report should preserve invalid_packet: ${JSON.stringify(poisonOutPayload)}`);
    assert(poisonPayload.message.includes("blocked payload control key"), `combat metadata poison payload should explain rejected control key: ${poisonMetadata.stdout}`);
    const poisonLiveInbox = path.join(metadataPoisonLiveDir, "inbox");
    const poisonLiveRequests = fs.readdirSync(poisonLiveInbox).filter((name) => name.endsWith(".json") || name.includes(".tmp"));
    assert(poisonLiveRequests.length === 0, `combat metadata poison payload should not create live inbox requests, found: ${poisonLiveRequests.join(",")}`);
  } finally {
    ensureRemoved(metadataPoisonAiDir);
    ensureRemoved(metadataPoisonLiveDir);
  ensureRemoved(metadataInvalidArgsLiveDir);
  }

  writeReadyStatus(metadataFreshAiDir, 301);
  writeReadyStatus(metadataFreshLiveDir, 401);
  fs.mkdirSync(path.join(metadataFreshLiveDir, "inbox"), { recursive: true });
  fs.mkdirSync(path.join(metadataFreshLiveDir, "outbox"), { recursive: true });
  fs.writeFileSync(path.join(metadataFreshLiveDir, "token.txt"), "smoke-live-token\n");
  const freshOutPath = path.join(metadataFreshLiveDir, "timeout-report.json");
  try {
    const freshMetadata = spawn(process.execPath, [
      metadataRunnerPath,
      "--ai-bridge-dir",
      metadataFreshAiDir,
      "--live-bridge-dir",
      metadataFreshLiveDir,
      "--sample-ms",
      "300",
      "--timeout-ms",
      "500",
      "--out",
      freshOutPath
    ], {
      cwd: repoRoot,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let freshStdout = "";
    let freshStderr = "";
    freshMetadata.stdout.on("data", (chunk) => { freshStdout += chunk.toString("utf8"); });
    freshMetadata.stderr.on("data", (chunk) => { freshStderr += chunk.toString("utf8"); });
    let freshAiFrame = 301;
    let freshLiveFrame = 401;
    const frameTicker = setInterval(() => {
      freshAiFrame += 1;
      freshLiveFrame += 1;
      writeReadyStatus(metadataFreshAiDir, freshAiFrame);
      writeReadyStatus(metadataFreshLiveDir, freshLiveFrame);
    }, 50);
    const freshExit = await waitForExit(freshMetadata, 3000);
    clearInterval(frameTicker);
    assert(freshExit === 1, `combat metadata fresh but nonresponsive live probe should fail closed with exit 1; stdout=${freshStdout} stderr=${freshStderr}`);
    assert(freshStderr.trim() === "", `combat metadata timeout should be structured stdout JSON, not stderr stack text: ${freshStderr}`);
    const freshPayload = JSON.parse(freshStdout);
    assert(freshPayload.error === "live_probe_timeout", `combat metadata timeout should report live_probe_timeout: ${freshStdout}`);
    const freshOutPayload = JSON.parse(fs.readFileSync(freshOutPath, "utf8"));
    assert(freshOutPayload.error === "live_probe_timeout", `combat metadata timeout --out report should preserve live_probe_timeout: ${JSON.stringify(freshOutPayload)}`);
    assert(freshPayload.requestCleanedUp === true, `combat metadata timeout should report request cleanup: ${freshStdout}`);
    assert(typeof freshPayload.freshness?.ai?.statusAgeMs === "number", `combat metadata timeout should include AI statusAgeMs: ${freshStdout}`);
    assert(freshPayload.freshness?.ai?.statusFileStale === false, `combat metadata timeout with advancing frames should not flag stale AI status file: ${freshStdout}`);
    assert(typeof freshPayload.freshness?.live?.statusLastWriteTimeUtc === "string", `combat metadata timeout should include live statusLastWriteTimeUtc: ${freshStdout}`);
    assert(freshPayload.failedRequest?.command === "method_signatures", `combat metadata timeout should identify the failed metadata request: ${freshStdout}`);
    const freshLiveInbox = path.join(metadataFreshLiveDir, "inbox");
    const freshLiveRequests = fs.readdirSync(freshLiveInbox).filter((name) => name.endsWith(".json") || name.includes(".tmp"));
    assert(freshLiveRequests.length === 0, `combat metadata timeout should clean pending live inbox requests, found: ${freshLiveRequests.join(",")}`);
  } finally {
    ensureRemoved(metadataFreshAiDir);
    ensureRemoved(metadataFreshLiveDir);
  }
  console.log("Olden AI MCP smoke test passed.");
}

await main();
