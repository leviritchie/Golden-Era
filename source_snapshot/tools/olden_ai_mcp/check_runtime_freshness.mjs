#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";

function parseArgs(argv) {
  const result = { sampleMs: 1500, requireFresh: false };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--ai-bridge-dir" && argv[i + 1]) result.aiBridgeDir = argv[++i];
    else if (arg === "--live-bridge-dir" && argv[i + 1]) result.liveBridgeDir = argv[++i];
    else if (arg === "--sample-ms" && argv[i + 1]) result.sampleMs = Math.max(100, Number(argv[++i]) || result.sampleMs);
    else if (arg === "--require-fresh") result.requireFresh = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return result;
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    return { ok: false, readError: String(error?.message || error) };
  }
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
  return { bridgeDir: path.resolve(bridgeDir), statusPath, ...readStatusFileMetadata(statusPath), status: readJson(statusPath) };
}

function summarizePair(first, second, sampleMs) {
  const firstStatus = first.status || {};
  const secondStatus = second.status || {};
  const firstFrame = Number(firstStatus.frame);
  const secondFrame = Number(secondStatus.frame);
  const frameAdvanced = Number.isFinite(firstFrame) && Number.isFinite(secondFrame) && secondFrame > firstFrame;
  const statusFileStale = !frameAdvanced && Number.isFinite(second.statusAgeMs) && second.statusAgeMs > sampleMs;
  return {
    bridgeDir: first.bridgeDir,
    statusPath: first.statusPath,
    statusLastWriteTimeUtc: second.statusLastWriteTimeUtc,
    statusAgeMs: second.statusAgeMs,
    statusFileStale,
    ok: Boolean(firstStatus.ok && secondStatus.ok),
    state: secondStatus.state || null,
    profile: secondStatus.profile || null,
    firstFrame: Number.isFinite(firstFrame) ? firstFrame : null,
    secondFrame: Number.isFinite(secondFrame) ? secondFrame : null,
    firstScene: firstStatus.scene || null,
    secondScene: secondStatus.scene || null,
    frameAdvanced,
    stale: !frameAdvanced,
    commands: Array.isArray(secondStatus.commands) ? secondStatus.commands : [],
    absentCommands: Array.isArray(secondStatus.absentCommands) ? secondStatus.absentCommands : []
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const args = parseArgs(process.argv);
if (!args.aiBridgeDir || !args.liveBridgeDir) {
  console.error("Usage: node tools/olden_ai_mcp/check_runtime_freshness.mjs --ai-bridge-dir <path> --live-bridge-dir <path> [--sample-ms 1500] [--require-fresh]");
  process.exit(2);
}

const firstAi = readStatus(args.aiBridgeDir);
const firstLive = readStatus(args.liveBridgeDir);
await sleep(args.sampleMs);
const secondAi = readStatus(args.aiBridgeDir);
const secondLive = readStatus(args.liveBridgeDir);

const result = {
  ok: true,
  sampleMs: args.sampleMs,
  ai: summarizePair(firstAi, secondAi, args.sampleMs),
  live: summarizePair(firstLive, secondLive, args.sampleMs)
};
result.fresh = Boolean(result.ai.frameAdvanced && result.live.frameAdvanced);
result.note = result.fresh
  ? "AI and live bridge status frames advanced during the read-only sample window."
  : "One or both bridge status frames did not advance during the read-only sample window; do not claim fresh runtime proof from this process.";

console.log(JSON.stringify(result, null, 2));
if (args.requireFresh && !result.fresh) process.exit(1);