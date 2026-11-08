#!/usr/bin/env python3
"""Static validation for the Olden AI driver MCP surface.

This intentionally does not contact the running game. Runtime proof still has to
come from Golden Era bridge responses and post-action observations.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOD_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
BRIDGE = MOD_DIR / "Homm3AiDriverBridge.cs"
GAMESYMBOLS = MOD_DIR / "GameSymbols.cs"
CSPROJ = MOD_DIR / "OfflineUnlockMod.csproj"
MCP_DIR = ROOT / "tools" / "olden_ai_mcp"
SERVER = MCP_DIR / "server.mjs"
SMOKE_TEST = MCP_DIR / "smoke_test.mjs"
FRESHNESS_CHECK = MCP_DIR / "check_runtime_freshness.mjs"
COMBAT_METADATA_RUNNER = MCP_DIR / "run_ai_start_combat_metadata_probe.mjs"
OWNER_DISCOVERY_RUNNER = MCP_DIR / "run_ai_start_combat_owner_discovery_probe.mjs"
README = MCP_DIR / "README.md"
SCHEMA_DIR = MCP_DIR / "schemas"
EVIDENCE_NOTE = ROOT / "docs" / "ai_start_combat_cheat_surface_static_evidence.md"
COMBAT_METADATA_PACKET = ROOT / "docs" / "ai_start_combat_live_metadata_probe_packet.json"
OWNER_DISCOVERY_PACKET = ROOT / "docs" / "ai_start_combat_owner_discovery_probe_packet.json"
PLAN_DOC = ROOT / "docs" / "ai_runtime_driver_mcp_plan.md"
AGENTS = ROOT / "AGENTS.md"
DIFF_TYPE_CMD_WORLD_CHEATS = ROOT / "tmp" / "cpp2il_experiment" / "out_dev_diffable_cs" / "DiffableCs" / "Hex" / "Hex" / "Session" / "TypeCmdWorldCheats.cs"
DIFF_STATE_CHEAT_CLICK_NODE = ROOT / "tmp" / "cpp2il_experiment" / "out_dev_diffable_cs" / "DiffableCs" / "Hex" / "Hex" / "Session" / "World" / "StateCheatClickNode.cs"
DIFF_EYS = ROOT / "tmp" / "cpp2il_experiment" / "out_dev_diffable_cs" / "DiffableCs" / "Hex" / "eys.cs"
DIFF_CUX = ROOT / "tmp" / "cpp2il_experiment" / "out_dev_diffable_cs" / "DiffableCs" / "Hex" / "cux.cs"
ISIL_EYS = ROOT / "tmp" / "cpp2il_experiment" / "out_dev_isil" / "IsilDump" / "Hex" / "eys.txt"
ISIL_CUX = ROOT / "tmp" / "cpp2il_experiment" / "out_dev_isil" / "IsilDump" / "Hex" / "cux.txt"
RUNTIME_INTEROP_MAP = ROOT / "experiments" / "cpp2il_readable_csharp" / "samples" / "latest_refresh" / "runtime_interop_map.json"
PROVEN_COMMANDS = [
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
    "ai_start_match",
]
MCP_TOOLS = ["bridge_info", *PROVEN_COMMANDS]
ABSENT_COMMANDS = ["ai_open_town", "ai_start_combat", "pilot_drag"]
FORBIDDEN_MCP_TOKENS = [
    "live_probe_bridge",
    "volatile_",
    "volatile.",
    "set_unity_ui_property",
    "set_nearest_canvas_property",
    "diagnostic_set_ui_property_by_path",
]


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"required file missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def quoted_list(name: str, text: str) -> list[str]:
    unescaped = text.replace('\\"', '"')
    match = re.search(rf'"{re.escape(name)}"\s*:\s*\[(.*?)\]', unescaped, flags=re.S)
    require(match is not None, f"{name} list missing from bridge status JSON")
    return re.findall(r'"([^"]+)"', match.group(1))


def validate_bridge_source() -> None:
    text = read(BRIDGE)
    commands = quoted_list("commands", text)
    absent = quoted_list("absentCommands", text)
    require(commands == PROVEN_COMMANDS, f"bridge commands drifted: {commands}")
    require(absent == ABSENT_COMMANDS, f"bridge absentCommands drifted: {absent}")
    for command in ABSENT_COMMANDS:
        require(f'case "{command}"' not in text, f"unproven command has bridge handler: {command}")
    require("Unproven commands are intentionally absent" in text, "unknown-command guard text missing")
    require("stale_observation" in text, "ai_act stale observation guard missing")
    require("stale_screen" in text, "ai_act stale screen guard missing")
    for code in [
        "unsupported_fingerprint",
        "bad_request",
        "stale_observation",
        "stale_screen",
        "unknown_action",
        "fingerprint_mismatch",
        "target_missing",
        "target_ambiguous",
        "target_not_visible",
        "target_not_interactable",
        "dispatch_failed",
    ]:
        require(code in text, f"ai_act negative guard missing: {code}")
    require("matched more than one active supported UI component" in text, "ai_act ambiguous target guard missing")
    forbidden_bridge_tokens = [
        "volatile_invoke",
        "volatile_set",
        "volatile_write",
        "volatile_autopatch",
        "live_probe_request",
        "Homm3LiveProbeWorkbench",
    ]
    for token in forbidden_bridge_tokens:
        require(token not in text, f"forbidden bridge implementation token leaked into AI bridge: {token}")


def validate_mcp_server() -> None:
    text = read(SERVER)
    match = re.search(r"function toolSchemas\(\) \{(.*?)\n\}\n\nasync function callTool", text, flags=re.S)
    require(match is not None, "MCP toolSchemas block missing")
    tool_names = re.findall(r'name:\s*"([^"]+)"', match.group(1))
    require(tool_names == MCP_TOOLS, f"MCP tool list drifted: {tool_names}")
    call_tool_match = re.search(r"async function callTool\(name, args = \{\}\) \{(.*?)\n\}\n\nfunction resourceList", text, flags=re.S)
    require(call_tool_match is not None, "MCP callTool block missing")
    call_tool_cases = re.findall(r'case\s+"([^"]+)"', call_tool_match.group(1))
    require(call_tool_cases == MCP_TOOLS, f"MCP callTool case list drifted: {call_tool_cases}")
    bridge_calls = re.findall(r'callBridge\("([^"]+)"', call_tool_match.group(1))
    require(bridge_calls == PROVEN_COMMANDS, f"MCP bridge command dispatch drifted: {bridge_calls}")
    for command in ABSENT_COMMANDS:
        require(command not in text, f"unproven command leaked into MCP server: {command}")
    for token in FORBIDDEN_MCP_TOKENS:
        require(token not in text, f"forbidden MCP token leaked into AI MCP: {token}")
    require('arg === "--bridge-dir"' in text, "MCP explicit --bridge-dir targeting support missing")
    require("OLDEN_AI_DRIVER_BRIDGE_DIR" in text, "MCP bridge-dir environment override missing")
    require("    bridgeDir," in text, "MCP bridgeInfo object does not return resolved bridgeDir")
    require("Current bridgeDir: ${info.bridgeDir}" in text, "MCP bridge-info resource does not report resolved bridgeDir")
    require('callBridge("ai_observe"' in text, "MCP ai_observe bridge call missing")
    require('callBridge("ai_act"' in text, "MCP ai_act bridge call missing")
    require('callBridge("screen_dump"' in text, "MCP screen_dump bridge call missing")
    require('callBridge("hover_snapshot"' in text, "MCP hover_snapshot bridge call missing")
    require('callBridge("pilot_click"' in text, "MCP pilot_click bridge call missing")
    require('callBridge("ai_start_match"' in text, "MCP ai_start_match bridge call missing")


def validate_mcp_smoke_test() -> None:
    text = read(SMOKE_TEST)
    require("spawn(process.execPath" in text, "MCP smoke test must spawn the server with Node")
    require("--bridge-dir" in text, "MCP smoke test must exercise explicit bridge-dir targeting")
    require("Content-Length" in text, "MCP smoke test must exercise framed JSON-RPC messages")
    for tool in MCP_TOOLS:
        require(f'"{tool}"' in text, f"MCP smoke test missing proven tool assertion: {tool}")
    for command in ABSENT_COMMANDS:
        require(f'"{command}"' in text, f"MCP smoke test missing absent tool assertion: {command}")
    require("bridge_unavailable" in text, "MCP smoke test must prove tokenless bridge calls fail closed")
    require("bridgeBackedTools" in text, "MCP smoke test must cover every exposed bridge-backed tool")
    require("for (const name of bridgeBackedTools)" in text, "MCP smoke test must loop over bridge-backed tools")
    require("bridge_unavailable should not create inbox requests" in text, "MCP smoke test must prove all bridge-backed tools avoid inbox writes when unavailable")
    require("should fail closed as an unknown tool" in text, "MCP smoke test must prove absent tools fail closed before bridge requests")
    require("Unknown tool:" in text, "MCP smoke test must assert absent tool rejection text")
    require("rejection should not include a stack trace" in text, "MCP smoke test must prove absent tool errors stay concise")
    require("String(error?.message || error)" in read(SERVER), "MCP server must not return stack traces for unknown tools")
    require("status resource read should not create bridge inbox requests" in text, "MCP smoke test must prove tokenless status does not enqueue bridge requests")
    require("aiActFingerprintKinds" in text, "MCP smoke test must inspect ai_act fingerprint kinds from tools/list")
    require("ai_act input schema must advertise only screen_path fingerprints" in text, "MCP smoke test must prove ai_act tools/list schema is screen_path-only")
    require("aiActSchemaPath" in text, "MCP smoke test must load the standalone ai_act request schema")
    require("stableStringify(comparableSchema(aiActTool.inputSchema))" in text, "MCP smoke test must compare ai_act tools/list schema with standalone schema")
    require("ai_act tools/list input schema drifted from schemas/ai_act_request.schema.json" in text, "MCP smoke test must fail on ai_act schema drift")
    require("assertEmptyObjectToolSchema" in text, "MCP smoke test must prove empty-argument tool schemas stay empty")
    require("hover_snapshot" in text and "ai_start_match" in text, "MCP smoke test must include hover_snapshot/ai_start_match in empty-schema drift checks")
    require("ai_observe uiLimit bounds drifted" in text, "MCP smoke test must assert ai_observe uiLimit bounds")
    require("screen_dump elementLimit bounds drifted" in text, "MCP smoke test must assert screen_dump elementLimit bounds")
    require("pilot_key required args drifted" in text, "MCP smoke test must assert pilot_key required args")
    require("pilot_click required args drifted" in text, "MCP smoke test must assert pilot_click required args")
    require("ai_grant_law_points count bounds drifted" in text, "MCP smoke test must assert law-point grant count bounds")
    require("ai_grant_resources native resource enum drifted" in text, "MCP smoke test must assert native resource enum")
    require("ai_grant_resources amount bounds drifted" in text, "MCP smoke test must assert resource amount bounds")
    require("ai_buy_law rank bounds drifted" in text, "MCP smoke test must assert native law-buy rank bounds")
    require("resources/read" in text, "MCP smoke test must exercise resource reads")
    require("olden-ai-driver://status" in text, "MCP smoke test must read the status resource")
    require("missing bridge status resource should fail closed" in text, "MCP smoke test must prove missing status resource fails closed")
    require("status resource read should not create bridge inbox requests" in text, "MCP smoke test must prove status resource read does not enqueue requests")
    require("olden-ai-driver://unknown" in text, "MCP smoke test must exercise unknown resource rejection")
    require("unknown resource should fail closed locally as a JSON-RPC invalid params error" in text, "MCP smoke test must prove unknown resources fail closed as JSON-RPC errors")
    require("unknown resource read should not create bridge inbox requests" in text, "MCP smoke test must prove unknown resource reads do not enqueue requests")
    require("__smoke_timeout_bridge__" in text, "MCP smoke test must exercise tokened nonresponsive bridge timeout cleanup")
    require("OLDEN_AI_DRIVER_TIMEOUT_MS" in text, "MCP smoke test must force a short bridge timeout")
    require("bridge_timeout" in text, "MCP smoke test must assert timeout fail-closed code")
    require("requestCleanedUp === true" in text, "MCP smoke test must prove timeout request cleanup is reported")
    require("bridge timeout should remove pending inbox requests" in text, "MCP smoke test must prove timed-out inbox request files are removed")
    require("malformedRequests" in text, "MCP smoke test must exercise malformed bridge-backed tool requests")
    require("invalid_request" in text, "MCP smoke test must assert malformed requests fail locally")
    require("should not create bridge inbox requests" in text, "MCP smoke test must prove malformed requests do not enqueue bridge writes")
    require("extra status argument" in text, "MCP smoke test must reject extra top-level tool args")
    require("extra ai_act fingerprint argument" in text, "MCP smoke test must reject extra targetFingerprint args")
    require("unsupported ai_act fingerprint kind" in text, "MCP smoke test must reject unsupported ai_act fingerprint kinds locally")
    require("run_ai_start_combat_metadata_probe.mjs" in text, "MCP smoke test must exercise the combat metadata runner")
    require("__smoke_combat_metadata_stale_ai__" in text, "MCP smoke test must create a fake stale AI bridge for combat metadata")
    require("__smoke_combat_metadata_stale_live__" in text, "MCP smoke test must create a fake stale live bridge for combat metadata")
    require("combat metadata runner stale freshness should fail closed" in text, "MCP smoke test must prove combat metadata runner blocks stale runtime")
    require("runtime_not_fresh" in text, "MCP smoke test must assert combat metadata stale error code")
    require("combat metadata stale runner should not create live inbox requests" in text, "MCP smoke test must prove stale combat metadata runner does not write live inbox requests")
    require("__smoke_combat_metadata_fresh_ai__" in text, "MCP smoke test must create a fake fresh AI bridge for combat metadata timeout cleanup")
    require("__smoke_combat_metadata_fresh_live__" in text, "MCP smoke test must create a fake fresh live bridge for combat metadata timeout cleanup")
    require("combat metadata fresh but nonresponsive live probe should fail closed with exit 1" in text, "MCP smoke test must prove combat metadata runner fails closed when live probe is nonresponsive")
    require("combat metadata timeout should report live_probe_timeout" in text, "MCP smoke test must require structured combat metadata timeout explanation")
    require("combat metadata stale --out report should preserve runtime_not_fresh" in text, "MCP smoke test must prove stale metadata failures write --out reports")
    require("combat metadata timeout --out report should preserve live_probe_timeout" in text, "MCP smoke test must prove timeout metadata failures write --out reports")
    require("poison command override" in text, "MCP smoke test must include poisoned combat metadata command-override packet")
    require("combat metadata poison payload command override should fail closed" in text, "MCP smoke test must prove poisoned metadata packets fail closed")
    require("combat metadata poison payload should not create live inbox requests" in text, "MCP smoke test must prove poisoned metadata packets do not write live inbox requests")
    require("combat metadata poison payload should be structured stdout JSON" in text, "MCP smoke test must prove poisoned metadata packets avoid stderr stacks")
    require("poisonPayload.error === \"invalid_packet\"" in text, "MCP smoke test must prove poisoned metadata packets return invalid_packet")
    require("combat metadata poison --out report should preserve invalid_packet" in text, "MCP smoke test must prove invalid_packet failures write --out reports")
    require("combat metadata invalid sample-ms should fail closed" in text, "MCP smoke test must reject invalid combat metadata sample-ms")
    require("invalidArgsPayload.error === \"invalid_args\"" in text, "MCP smoke test must prove invalid combat metadata args return invalid_args")
    require("combat metadata invalid args should not create live inbox requests" in text, "MCP smoke test must prove invalid combat metadata args do not write live inbox requests")
    require("statusAgeMs" in text and "statusLastWriteTimeUtc" in text, "MCP smoke test must prove freshness reports include status-file age/timestamp")
    require("statusFileStale === true" in text and "statusFileStale === false" in text, "MCP smoke test must prove stale-status-file flag behavior")
    require("freshness --require-fresh should exit 1 for stale frames" in text, "MCP smoke test must prove --require-fresh exits 1 on stale frames")
    require("freshness --require-fresh should exit 0 for advancing frames" in text, "MCP smoke test must prove --require-fresh exits 0 on advancing frames")
    require("freshness stale hard gate should not create AI inbox requests" in text, "MCP smoke test must prove --require-fresh remains read-only for AI bridge")
    require("freshness stale hard gate should not create live inbox requests" in text, "MCP smoke test must prove --require-fresh remains read-only for live bridge")
    require("combat metadata timeout should clean pending live inbox requests" in text, "MCP smoke test must prove combat metadata timeout removes pending live inbox requests")
    require("live_probe_timeout" in text, "MCP smoke test must assert structured combat metadata timeout code")
    require("requestCleanedUp === true" in text, "MCP smoke test must require combat metadata timeout cleanup reporting")
    require("freshStderr.trim() === \"\"" in text, "MCP smoke test must prove combat metadata timeout avoids stderr stack text")
    server_text = read(SERVER)
    require("function invalidRequest" in server_text, "MCP server must have local invalid_request helper")
    require("function rejectExtraKeys" in server_text, "MCP server must reject extra tool arguments locally")
    require("function requireString" in server_text, "MCP server must validate required string arguments locally")
    require("function optionalInteger" in server_text, "MCP server must validate bounded integer arguments locally")
    require("function validateAiActArgs" in server_text, "MCP server must validate ai_act request arguments locally")
    require("RESOURCE_NAMES" in server_text, "MCP server must validate ai_grant_resources resourceName locally")
    require("String(args." not in server_text, "MCP server must not coerce missing required tool args into empty strings")
    require("Math.max" not in server_text and "Math.min" not in server_text, "MCP server must not clamp invalid tool numeric args before bridge calls")
    server_text = read(SERVER)
    require("requestCleanedUp" in server_text, "MCP server must report timeout request cleanup")
    require("fs.unlinkSync(requestPath)" in server_text, "MCP server must remove still-pending inbox requests after timeout")

def validate_runtime_freshness_helper() -> None:
    text = read(FRESHNESS_CHECK)
    require("--ai-bridge-dir" in text, "runtime freshness helper must require explicit AI bridge dir")
    require("--live-bridge-dir" in text, "runtime freshness helper must require explicit live bridge dir")
    require("frameAdvanced" in text, "runtime freshness helper must report frame advancement")
    require("statusAgeMs" in text, "runtime freshness helper must report status-file age")
    require("statusFileStale" in text, "runtime freshness helper must report explicit stale-status-file flag")
    require("statusLastWriteTimeUtc" in text, "runtime freshness helper must report status-file timestamp")
    require("--require-fresh" in text, "runtime freshness helper must expose hard-fail --require-fresh mode")
    require("process.exit(1)" in text, "runtime freshness helper must exit nonzero when --require-fresh sees stale frames")
    require("do not claim fresh runtime proof" in text, "runtime freshness helper must warn against stale runtime proof")
    require("fs.readFileSync" in text, "runtime freshness helper must be read-only status sampling")
    for token in ["inbox", "outbox", "writeFile", "rename", "unlink", "rmSync"]:
        require(token not in text, f"runtime freshness helper must not write bridge files: {token}")

def validate_combat_metadata_runner() -> None:
    text = read(COMBAT_METADATA_RUNNER)
    require("ai_start_combat_live_metadata_probe_packet.json" in text, "combat metadata runner must target the exact packet")
    require("ai-start-combat-live-metadata-probe.v1" in text, "combat metadata runner must validate packet schema")
    require("source-prepared-only" in text, "combat metadata runner must preserve source-prepared-only status")
    require('new Set(["method_signatures", "resolve_decomp_method"])' in text, "combat metadata runner must allow only read-only metadata commands")
    require("runtime_not_fresh" in text, "combat metadata runner must fail closed when freshness does not advance")
    require("invalid_packet" in text, "combat metadata runner must return structured invalid_packet JSON")
    require("invalid_args" in text, "combat metadata runner must return structured invalid_args JSON")
    require("parseIntegerArg" in text, "combat metadata runner must parse numeric args explicitly")
    require("Number(argv[++i]) ||" not in text, "combat metadata runner must not default invalid numeric args")
    require("Math.max(100" not in text and "Math.max(500" not in text, "combat metadata runner must not clamp invalid sample/timeout args")
    require("before freshness sampling or live_probe_bridge inbox writes" in text, "combat metadata runner must reject invalid packets before freshness/live writes")
    require("AI and live bridge frames must both advance" in text, "combat metadata runner must explain freshness gate")
    require("statusAgeMs" in text, "combat metadata runner must include status-file age in freshness output")
    require("statusFileStale" in text, "combat metadata runner must include explicit stale-status-file flag")
    require("statusLastWriteTimeUtc" in text, "combat metadata runner must include status-file timestamp in freshness output")
    require("packet.freshnessPreflight?.requiredBeforeLiveProbe" in text, "combat metadata runner must require packet freshness preflight")
    require("packet.freshnessPreflight?.command?.includes(\"--require-fresh\")" in text, "combat metadata runner must require packet hard-fail freshness command")
    require("CONTROL_PAYLOAD_KEYS" in text, "combat metadata runner must block payload control-key overrides")
    require("allowedPayloadKeysForCommand" in text, "combat metadata runner must use exact metadata payload shapes")
    require("blocked payload control key" in text, "combat metadata runner must reject control keys inside payloads")
    require("validateMetadataPayload(request)" in text, "combat metadata runner must validate each packet request payload")
    require("...metadataPayload, command: request.command" in text, "combat metadata runner must prevent payload command override when writing live requests")
    require("command: request.command, ...request.payload" not in text, "combat metadata runner must not allow payload spread to override command")
    require("payload.typeName" in text, "combat metadata runner must require payload typeName")
    require("fs.writeFileSync(requestPath" in text, "combat metadata runner live writes must stay isolated to gated requestLiveProbe")
    require("checkFreshness(args.aiBridgeDir, args.liveBridgeDir" in text, "combat metadata runner must check both bridge dirs before requests")
    require("if (!freshness.fresh)" in text, "combat metadata runner must block before writing requests when stale")
    require("error: \"live_probe_timeout\"" in text, "combat metadata runner must return structured timeout JSON")
    require("requestCleanedUp: Boolean(error.requestCleanedUp)" in text, "combat metadata runner must report timeout cleanup status")
    require("failedRequest: error.failedRequest" in text, "combat metadata runner must report failed metadata request")
    require("partialResults: results" in text, "combat metadata runner must preserve partial read-only results on timeout")
    require("function writeReport" in text, "combat metadata runner must write failure and success reports through one helper")
    require("writeReport(args.out, blocked)" in text, "combat metadata runner must write runtime_not_fresh reports to --out")
    require("writeReport(args.out, failed)" in text, "combat metadata runner must write live_probe_timeout reports to --out")
    freshness_check_pos = text.find("if (!freshness.fresh)")
    first_request_call_pos = text.find("requestLiveProbe(args.liveBridgeDir")
    require(freshness_check_pos != -1 and first_request_call_pos != -1 and freshness_check_pos < first_request_call_pos, "combat metadata runner must gate live requests after freshness check")
    for forbidden in ["volatile_", "compile_probe"]:
        require(forbidden not in text, f"combat metadata runner must not include volatile/probe helper token: {forbidden}")


def validate_combat_owner_discovery_runner() -> None:
    text = read(OWNER_DISCOVERY_RUNNER)
    require("ai_start_combat_owner_discovery_probe_packet.json" in text, "combat owner-discovery runner must target the exact packet")
    require("ai-start-combat-owner-discovery-probe.v1" in text, "combat owner-discovery runner must validate packet schema")
    require("source-prepared-only" in text, "combat owner-discovery runner must preserve source-prepared-only status")
    require('new Set(["unity_components_by_type"])' in text, "combat owner-discovery runner must allow only exact component discovery")
    require("OWNER_COMPONENT_TYPES" in text, "combat owner-discovery runner must constrain owner component types")
    for owner_type in ["Hex.Cheat.UI.BhWindowWorld", "Hex.Cheat.UI.BhWindowHero", "Hex.Cheat.UI.BhWindowMagic"]:
        require(owner_type in text, f"combat owner-discovery runner missing owner type: {owner_type}")
    for forbidden in ["component_member_path", "allowProperties", "get_sideCheats", "set_sideCheats", "volatile_", "compile_probe"]:
        require(forbidden not in text, f"combat owner-discovery runner must not include unapproved proof token: {forbidden}")
    require("runtime_not_fresh" in text, "combat owner-discovery runner must fail closed when freshness does not advance")
    require("invalid_packet" in text, "combat owner-discovery runner must return structured invalid_packet JSON")
    require("invalid_args" in text, "combat owner-discovery runner must return structured invalid_args JSON")
    require("parseIntegerArg" in text, "combat owner-discovery runner must parse numeric args explicitly")
    require("Number(argv[++i]) ||" not in text, "combat owner-discovery runner must not default invalid numeric args")
    require("CONTROL_PAYLOAD_KEYS" in text, "combat owner-discovery runner must block payload control-key overrides")
    require("allowedPayloadKeysForCommand" in text, "combat owner-discovery runner must use exact discovery payload shapes")
    require("blocked payload control key" in text, "combat owner-discovery runner must reject control keys inside payloads")
    require("validateDiscoveryPayload(request)" in text, "combat owner-discovery runner must validate each packet request payload")
    require("...discoveryPayload, command: request.command" in text, "combat owner-discovery runner must prevent payload command override when writing live requests")
    require("componentType" in text, "combat owner-discovery runner must require componentType")
    require("fieldLimit" in text and "payload.fieldLimit" in text, "combat owner-discovery runner must bound fieldLimit")
    require("checkFreshness(args.aiBridgeDir, args.liveBridgeDir" in text, "combat owner-discovery runner must check both bridge dirs before requests")
    require("if (!freshness.fresh)" in text, "combat owner-discovery runner must block before writing requests when stale")
    require("error: \"live_probe_timeout\"" in text, "combat owner-discovery runner must return structured timeout JSON")
    require("requestCleanedUp: Boolean(error.requestCleanedUp)" in text, "combat owner-discovery runner must report timeout cleanup status")
    require("partialResults: results" in text, "combat owner-discovery runner must preserve partial read-only results on timeout")
    freshness_check_pos = text.find("if (!freshness.fresh)")
    first_request_call_pos = text.find("requestLiveProbe(args.liveBridgeDir")
    require(freshness_check_pos != -1 and first_request_call_pos != -1 and freshness_check_pos < first_request_call_pos, "combat owner-discovery runner must gate live requests after freshness check")

def validate_mcp_readme() -> None:
    text = read(README)
    require("--bridge-dir" in text, "MCP README does not document explicit bridge-dir targeting")
    require("OLDEN_AI_DRIVER_BRIDGE_DIR" in text, "MCP README does not document bridge-dir environment override")
    require("Golden Era" in text, "MCP README does not tie runtime proof to Golden Era")
    require("Do not rely on the repo-local default" in text, "MCP README missing repo-local default warning")
    require("check_runtime_freshness.mjs" in text, "MCP README must document read-only freshness preflight")
    require("fresh=false" in text, "MCP README must document stale freshness result handling")
    require("--require-fresh" in text, "MCP README must document freshness hard-fail mode")
    require("exits with code 1" in text, "MCP README must document stale --require-fresh exit behavior")
    require("does not write inbox/outbox requests" in text, "MCP README must state freshness helper is read-only")
    require("--ai-bridge-dir" in text and "--live-bridge-dir" in text, "MCP README must document explicit freshness bridge dirs")
    require("Fail-Closed Adapter Behavior" in text, "MCP README must document fail-closed adapter behavior")
    require("invalid_request" in text, "MCP README must document local invalid_request handling")
    require("do not create `inbox` files" in text, "MCP README must document malformed requests do not write inbox files")
    require("Required strings are not coerced to empty values" in text, "MCP README must document no empty-string coercion")
    require("numeric arguments are not clamped" in text, "MCP README must document no numeric clamping")
    require("Unknown extra tool arguments are rejected" in text, "MCP README must document exact argument shape enforcement")
    require("bridge_timeout" in text, "MCP README must document bridge timeout behavior")
    require("removes any still-pending `inbox/<id>.json`" in text, "MCP README must document timeout inbox cleanup")
    require("stale setup/action work" in text, "MCP README must document stale request prevention")


def validate_schemas() -> None:
    required = {
        "ai_observation.schema.json",
        "ai_act_request.schema.json",
    }
    seen = {path.name for path in SCHEMA_DIR.glob("*.json")}
    require(required <= seen, f"schema files missing: {sorted(required - seen)}")
    parsed_schemas: dict[str, dict] = {}
    for name in sorted(required):
        with (SCHEMA_DIR / name).open("r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        require(isinstance(parsed, dict), f"schema is not a JSON object: {name}")
        parsed_schemas[name] = parsed

    def require_required(schema: dict, expected: list[str], label: str) -> None:
        actual = schema.get("required")
        require(actual == expected, f"{label} required fields drifted: {actual}")

    def require_array_bound(schema: dict, property_name: str, max_items: int, label: str) -> None:
        prop = schema["properties"][property_name]
        require(prop.get("type") == "array", f"{label}.{property_name} must stay an array")
        require(prop.get("maxItems") == max_items, f"{label}.{property_name} maxItems drifted: {prop.get('maxItems')}")

    def require_fingerprint_shape(schema: dict, label: str, expected_kinds: list[str]) -> None:
        require(schema.get("additionalProperties") is False, f"{label} fingerprint must reject extra properties")
        require_required(schema, ["kind", "value"], f"{label} fingerprint")
        kinds = schema["properties"]["kind"].get("enum")
        require(kinds == expected_kinds, f"{label} fingerprint kind enum drifted: {kinds}")
        require(schema["properties"]["value"].get("minLength") == 1, f"{label} fingerprint value minLength drifted")

    observation = parsed_schemas["ai_observation.schema.json"]
    act_request = parsed_schemas["ai_act_request.schema.json"]

    require(observation.get("type") == "object", "observation schema must stay an object")
    require(observation.get("additionalProperties") is False, "observation schema must reject extra top-level properties")
    require(observation["properties"]["schemaVersion"].get("const") == "ai-driver.v1.observation", "observation schemaVersion const drifted")
    require_required(
        observation,
        [
            "schemaVersion",
            "observationId",
            "screenId",
            "scene",
            "frame",
            "mode",
            "timestamp",
            "uiElements",
            "gameObjects",
            "actions",
            "gaps",
        ],
        "observation",
    )
    modes = observation["properties"]["mode"].get("enum")
    require(modes == ["main_menu", "adventure_map", "town", "battle", "loading", "unknown"], f"observation mode enum drifted: {modes}")
    require_array_bound(observation, "uiElements", 256, "observation")
    require_array_bound(observation, "gameObjects", 256, "observation")
    require_array_bound(observation, "actions", 128, "observation")
    require_array_bound(observation, "gaps", 64, "observation")

    defs = observation["$defs"]
    require_required(defs["uiElement"], ["id", "role", "name", "path", "rect", "visible", "enabled", "interactable", "fingerprint"], "uiElement")
    require_required(defs["gameObject"], ["id", "kind", "name", "visible", "fingerprint"], "gameObject")
    require_required(defs["action"], ["actionId", "kind", "role", "targetId", "targetFingerprint", "screenId"], "action")
    require_required(defs["gap"], ["code", "message"], "gap")
    require_fingerprint_shape(defs["fingerprint"], "observation", ["runtime_instance_id", "semantic", "native_sid", "screen_path"])

    action_kinds = defs["action"]["properties"]["kind"].get("enum")
    require(action_kinds == ["click", "submit"], f"observation action kind enum exposes unproven kinds: {action_kinds}")
    require("key" not in defs["action"]["properties"], "observation action schema must not carry unimplemented key payloads")
    require(defs["action"].get("additionalProperties") is False, "action schema must reject extra properties")

    require(act_request.get("type") == "object", "ai_act request schema must stay an object")
    require(act_request.get("additionalProperties") is False, "ai_act request schema must reject extra top-level properties")
    require(act_request["properties"]["schemaVersion"].get("const") == "ai-driver.v1.act-request", "ai_act request schemaVersion const drifted")
    require_required(act_request, ["schemaVersion", "observationId", "screenId", "actionId", "targetFingerprint"], "ai_act request")
    require_fingerprint_shape(act_request["properties"]["targetFingerprint"], "ai_act request", ["screen_path"])
    server = read(SERVER)
    require('kind: { type: "string", enum: ["screen_path"] }' in server, "MCP ai_act input schema must advertise only screen_path fingerprints")

    bridge = read(BRIDGE)
    require('var actionKind = IsClickUiType(typeName) ? "click" : "submit"' in bridge, "bridge action emission must stay limited to click/submit")
    for unproven_kind in ["double_click", "hover", "key"]:
        require(unproven_kind not in json.dumps(observation), f"observation schema exposes unproven action kind: {unproven_kind}")
    # Observed ai_act action kinds only — do not confuse with hover_snapshot / pilot_key bridge commands.
    require('"kind":"hover"' not in bridge.replace(" ", "") and 'kind = "hover"' not in bridge, "bridge must not emit hover as an ai_act action kind")
    require('"kind":"double_click"' not in bridge.replace(" ", "") and 'kind = "double_click"' not in bridge, "bridge must not emit double_click as an ai_act action kind")
    require('actionKind = "key"' not in bridge and 'Kind = "key"' not in bridge, "bridge must not emit key as an ai_act action kind")

    # Perception / pilot sibling schemas
    perception_required = {
        "screen_dump.schema.json",
        "visible_snapshot.schema.json",
        "hover_snapshot.schema.json",
    }
    require(perception_required <= seen, f"perception schema files missing: {sorted(perception_required - seen)}")
    screen_dump = json.loads(read(SCHEMA_DIR / "screen_dump.schema.json"))
    require(screen_dump["properties"]["schemaVersion"].get("const") == "ai-driver.v1.screen-dump", "screen_dump schemaVersion drifted")
    require(screen_dump["properties"]["srSafe"].get("const") is False, "screen_dump must declare srSafe=false")
    require(screen_dump["$defs"]["fingerprint"]["properties"]["kind"].get("const") == "dump_path", "screen_dump fingerprints must be dump_path only")
    dump_kinds = set(screen_dump["$defs"]["dumpElement"]["properties"]["kind"]["enum"])
    require({"selectable", "text_only", "map_object", "map_marker", "map_hero"} <= dump_kinds, f"screen_dump kind enum missing map catalog kinds: {sorted(dump_kinds)}")
    hover_schema = json.loads(read(SCHEMA_DIR / "hover_snapshot.schema.json"))
    require(hover_schema["properties"]["schemaVersion"].get("const") == "ai-driver.v1.hover-snapshot", "hover_snapshot schemaVersion drifted")
    require("screen_dump" in read(BRIDGE) and "hover_snapshot" in read(BRIDGE) and "focus_snapshot" in read(BRIDGE) and "pilot_click" in read(BRIDGE), "bridge must wire perception/pilot/focus siblings")
    require((SCHEMA_DIR / "focus_snapshot.schema.json").exists(), "focus_snapshot schema must exist")
    focus_schema = json.loads(read(SCHEMA_DIR / "focus_snapshot.schema.json"))
    require(focus_schema["properties"]["schemaVersion"].get("const") == "ai-driver.v1.focus-snapshot", "focus_snapshot schemaVersion drifted")
    require(focus_schema["properties"]["speechSafe"].get("type") == "boolean", "focus_snapshot must declare speechSafe")
    require("utterance" in focus_schema["properties"], "focus_snapshot must require utterance")
    focus_cs = read(ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3AiDriverBridge.Focus.cs")
    require("BuildFocusSnapshotJson" in focus_cs, "focus partial must emit BuildFocusSnapshotJson")
    require("IsPlaceholderSpeechLabel" in focus_cs, "focus must reject placeholder labels")
    require("focus_latest.json" in focus_cs, "focus must write focus_latest.json")
    nvda = read(ROOT / "tools" / "olden_a11y_nvda" / "watch_hover_nvda.py")
    require("focus_latest.json" in nvda, "NVDA companion must prefer focus_latest.json")
    require("does not read screen_dump" in nvda, "NVDA companion must not consume screen_dump")
    screen_dump_cs = read(ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3AiDriverBridge.ScreenDump.cs")
    require("dump_path" in screen_dump_cs, "screen dump partial must emit dump_path fingerprints")
    require("AppendMapWorldDumpElements" in screen_dump_cs, "screen_dump must emit adventure-map world catalog via AppendMapWorldDumpElements")
    require('"map_object"' in screen_dump_cs and '"map_marker"' in screen_dump_cs and '"map_hero"' in screen_dump_cs, "screen_dump must emit map_object/map_marker/map_hero kinds")
    require("map_world_objects_undumped" in screen_dump_cs, "screen_dump must retain map_world_objects_undumped as a fail-closed gap")
    require("map_world_resolve_failed" in screen_dump_cs, "screen_dump must emit map_world_resolve_failed when Map/MapData resolve fails")
    # Undumped gap must not be the unconditional first story once map kinds exist.
    require("mapRowsEmitted" in screen_dump_cs or "map_rows_emitted" in screen_dump_cs or "emittedMapRows" in screen_dump_cs, "screen_dump must gate map_world_objects_undumped on whether map rows were emitted")
    require("ScreenDumpCacheTtlFrames" in screen_dump_cs, "screen_dump must cache dumps across frames")
    require("_placedScanAllCold" in screen_dump_cs, "screen_dump must skip repeated zero-hit FindObjectsOfTypeAll scans")
    require("FindObjectsOfTypeAll<Camera>" not in screen_dump_cs, "screen_dump must not full-scan all Cameras (FPS hitch)")
    require("_cachedAdventureDumpCamera" in screen_dump_cs, "screen_dump must cache adventure projection camera")
    require("MapNodeToWorld" in screen_dump_cs or "TryProjectMapNode" in screen_dump_cs, "screen_dump must project map nodes to screen rects without relying on placed FindObjectsOfTypeAll")
    require("TryResolveAdventureMapFogOfWar" in screen_dump_cs, "screen_dump must resolve adventure Side.fogData / DataFogOfWar")
    require("ApplyFogVisibilityToPoint" in screen_dump_cs, "screen_dump must gate map onScreen with FoW visibility")
    require("map_fog_visibility_applied" in screen_dump_cs and "map_fog_visibility_unresolved" in screen_dump_cs, "screen_dump must emit FoW applied/unresolved gaps")
    require("BuildWorldHeroDumpIndex" in screen_dump_cs, "screen_dump must resolve live world-hero transforms for map_hero rows")
    require("map_world_hero_node_unresolved" in screen_dump_cs, "screen_dump must emit map_world_hero_node_unresolved when hero tile/rect is unproven")
    require("TryResolveSessionDataHeroNode" in screen_dump_cs, "screen_dump must resolve Hex.Session.Data.Hero node for map_hero rows")
    require("FogVisible" in screen_dump_cs, "screen_dump must carry FogVisible on map rows")
    require("fogVisible" in json.dumps(screen_dump), "screen_dump schema must allow optional fogVisible")
    require("Homm3AiDriverFogCache" in screen_dump_cs or (MOD_DIR / "Homm3AiDriverFogCache.cs").exists(), "AI driver must cache live DataFogOfWar for screen_dump")
    fog_cache = read(MOD_DIR / "Homm3AiDriverFogCache.cs")
    require("FogVisibilityRead" in fog_cache or "PostfixFogVisibilityRead" in fog_cache, "FoW cache must patch DataFogOfWar visibility read")
    require("Method_Public_get_Side_0" in read(GAMESYMBOLS), "GameSymbols DataSides current side must prefer live Method_Public_get_Side_0")
    require("TryFindSessionRootFromStaticHolders" in screen_dump_cs, "screen_dump must resolve session.world via static holders (not WORLD MonoBehaviour scan)")
    require("SessionHolderTypeHints" in read(ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"), "GameSymbols must pin session holder types for FoW")
    require("MapDataObjectsNodesFields" in read(ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "GameSymbols.cs"), "GameSymbols must pin MapDataObjects.nodes for node projection")
    hover_cs = read(ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3AiDriverBridge.Hover.cs")
    require("FindObjectsOfType<MonoBehaviour>" not in hover_cs.replace(" ", ""), "hover must not FindObjectsOfType MonoBehaviour every tick (FPS hitch)")
    require("ResolveCachedMapHoverOwner" in hover_cs, "hover must cache typed map hover owner")
    require("HoverTickMinFrameGap" in hover_cs, "hover tick must be frame-throttled")
    require("One catalog row per MapData.objects entry" in screen_dump_cs, "screen_dump must not explode MapData.objects ids into duplicate rows")
    require("elements.Count < elementLimit" in screen_dump_cs and "CollectSupportedUiComponents" in screen_dump_cs, "screen_dump must skip UI scan when catalog already filled")
    require("_cachedDumpRecords" in screen_dump_cs, "visible_snapshot must reuse cached dump records instead of a second full scan")
    pilot_cs = read(ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3AiDriverBridge.Pilot.cs")
    require("win32_sendinput_mouse" in pilot_cs, "pilot_click must document SendInput mouse route")
    require("win32_sendinput_key" in pilot_cs, "pilot_key must document SendInput route")
    require('string.Equals(record.Kind, "key"' not in bridge, "bridge source exposes unproven key action route")
    require('"kind":"key"' not in bridge, "bridge source emits unproven key action kind")


def validate_static_decomp_artifacts() -> None:
    type_cmd = read(DIFF_TYPE_CMD_WORLD_CHEATS)
    state_click = read(DIFF_STATE_CHEAT_CLICK_NODE)
    eys_diff = read(DIFF_EYS)
    cux_diff = read(DIFF_CUX)
    eys_isil = read(ISIL_EYS)
    cux_isil = read(ISIL_CUX)
    interop = read(RUNTIME_INTEROP_MAP)

    for token in ["BattleAutoWin = 12", "CreateSquad = 16", "CreateRandomSquad = 17"]:
        require(token in type_cmd, f"TypeCmdWorldCheats decomp evidence missing: {token}")
    for token in ["CreateSquad = 1", "CreateRandomSquad = 2"]:
        require(token in state_click, f"StateCheatClickNode decomp evidence missing: {token}")
    for token in [
        "public StateCheatClickNode cixc; //Field offset: 0x3C",
        "public void dvf()",
        "public void bhzm()",
        "public void bhzo()",
        "public void bhzj(bool a)",
    ]:
        require(token in eys_diff, f"eys DiffableCs evidence missing: {token}")
    for token in [
        "public int cafe; //Field offset: 0x20",
        "public int caff; //Field offset: 0x24",
        "public bool cafi; //Field offset: 0x34",
        "public int cafp; //Field offset: 0x64",
        "public int cafq; //Field offset: 0x68",
        "public int cafr; //Field offset: 0x6C",
        "public virtual ECmd hsf()",
    ]:
        require(token in cux_diff, f"cux DiffableCs evidence missing: {token}")
    for token in [
        "Method: System.Void dvf()",
        "CallVoid eys.bhzo",
        "CallVoid eys.bhzm",
        "Method: System.Void bhzm()",
        "mov [rbx+64h],eax",
        "mov [rbx+68h],eax",
        "mov [rbx+6Ch],eax",
        "mov dword ptr [rbx+20h],10h",
    ]:
        require(token in eys_isil, f"eys ISIL evidence missing: {token}")
    for token in [
        "Method: Hex.Processing.ECmd hsf()",
        "mov eax,71h",
        "movsxd rax,dword ptr [rdi+20h]",
        "cmp eax,16h",
        "mov ecx,[rdx+rax*4+2BE4C3Ch]",
        "add rcx,rdx",
        "jmp rcx",
        "mov ebx,[rdi+68h]",
        "mov edx,[rdi+68h]",
        "mov r9d,[rdi+6Ch]",
    ]:
        require(token in cux_isil, f"cux ISIL evidence missing: {token}")
    for token in [
        "ObjectPublicInciObInciBoObStInciUnique",
        "Object1PublicIncaStIncaBoStcaInStUnique",
        "Hex.Cheat.UI.BhWindowWorld",
        "Hex.Cheat.UI.BhWindowHero",
        "Hex.Cheat.UI.BhWindowMagic",
        "ObjectPublicObBhcjObIncjSiObIncoUnique",
        "get_sideCheats",
        "set_sideCheats",
        "get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0",
    ]:
        require(token in interop, f"runtime interop map missing generated combat setup candidate: {token}")

def validate_game_symbols() -> None:
    text = read(GAMESYMBOLS)
    require(re.search(r"internal static (?:partial )?class AiDriverCombatSetup\b", text) is not None, "GameSymbols missing AI combat setup symbol group")
    for token in [
        "WorldCheatControllerTypeNames",
        "WorldCheatCommandTypeNames",
        "eys",
        "cux",
        "ObjectPublicInciObInciBoObStInciUnique",
        "Object1PublicIncaStIncaBoStcaInStUnique",
        "WorldCheatUiOwnerTypeNames",
        "Hex.Cheat.UI.BhWindowWorld",
        "Hex.Cheat.UI.BhWindowHero",
        "Hex.Cheat.UI.BhWindowMagic",
        "WorldCheatSessionRootTypeNames",
        "ObjectPublicObBhcjObIncjSiObIncoUnique",
        "UiOwnerSideCheatsGetter",
        "SessionRootSideCheatsGetter",
        "get_sideCheats",
        "get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0",
        "DispatchClickState",
        "BuildCreateSquadCommand",
        "BuildCreateRandomSquadCommand",
        "BuildBattleAutoWinCommand",
        "WorldCheatCommandTypeGetter",
        "CheatClickStateField",
        "CommandSelectorField",
        "CommandContextField",
        "CommandBoolField",
        "CommandXField",
        "CommandYField",
        "CommandZField",
        "StateCheatClickNodeCreateSquad = 1",
        "StateCheatClickNodeCreateRandomSquad = 2",
        "TypeCmdWorldCheatsBattleAutoWin = 12",
        "TypeCmdWorldCheatsCreateSquad = 16",
        "TypeCmdWorldCheatsCreateRandomSquad = 17",
        "WorldCheatOuterCommandType = 0x71",
        "CheatClickStateFieldOffset = 0x3C",
        "CommandSelectorFieldOffset = 0x20",
        "CommandBoolFieldOffset = 0x34",
        "CommandXFieldOffset = 0x64",
        "CommandYFieldOffset = 0x68",
        "CommandZFieldOffset = 0x6C",
    ]:
        require(token in text, f"GameSymbols missing AI combat setup token: {token}")
    require("must not be treated as a proven command route" in text, "GameSymbols AI combat setup group must preserve unproven-route warning")
    require("owner-discovery evidence only" in text, "GameSymbols owner-discovery symbols must preserve unproven warning")

def validate_static_evidence_notes() -> None:
    text = read(EVIDENCE_NOTE)
    require("Runtime proof: blocked" in text, "combat evidence note must keep runtime proof blocked")
    require("Command exposure: unchanged" in text, "combat evidence note must keep command exposure unchanged")
    require("`ai_start_combat` and `ai_open_town` must remain absent" in text, "combat evidence note must keep unproven commands absent")
    for token in [
        "BattleAutoWin = 12",
        "CreateSquad = 16",
        "CreateRandomSquad = 17",
        "CreateSquad = 1",
        "CreateRandomSquad = 2",
        "StateCheatClickNode cixc",
        "[rbx+20h] = 0x10",
        "[rbx+20h] = 0x11",
        "[rbx+20h] = 0x0C",
        "ECmd` value `0x71`",
        "[rdx+rax*4+2BE4C3Ch]",
        "jmp rcx",
        "create-squad coordinate reads",
        "BhWindowWorld",
        "BhWindowHero",
        "BhWindowMagic",
        "get_sideCheats()",
        "ObjectPublicObBhcjObIncjSiObIncoUnique",
        "get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0",
    ]:
        require(token in text, f"combat evidence note missing static token: {token}")
    require("does not prove a deterministic combat-entry setup command" in text, "combat evidence note must state deterministic combat entry is unproven")
    require('ai_observe.mode == "battle"' in text, "combat evidence note must require battle-mode post-observation proof")
    for item in [
        "Fresh live bridge responsiveness",
        "Runtime metadata resolution",
        "Read-only live owner/instance discovery",
        "generated owner candidates",
        "Centralized `GameSymbols` entries are source-prepared",
    ]:
        require(item in text, f"combat evidence note missing future proof requirement: {item}")


def validate_combat_metadata_packet() -> None:
    with COMBAT_METADATA_PACKET.open("r", encoding="utf-8") as handle:
        packet = json.load(handle)
    require(packet.get("schemaVersion") == "ai-start-combat-live-metadata-probe.v1", "combat metadata packet schemaVersion drifted")
    require(packet.get("status") == "source-prepared-only", "combat metadata packet must remain source-prepared only")
    exposure = packet.get("commandExposure", "")
    require("ai_start_combat and ai_open_town must remain absent" in exposure, "combat metadata packet must preserve absent command warning")
    freshness = packet.get("freshnessPreflight", {})
    require(freshness.get("requiredBeforeLiveProbe") is True, "combat metadata packet must require freshness preflight")
    require("check_runtime_freshness.mjs" in freshness.get("command", ""), "combat metadata packet must point at freshness helper")
    require("--require-fresh" in freshness.get("command", ""), "combat metadata packet must require hard-fail freshness preflight")
    require(freshness.get("lastKnownBlockedState", {}).get("fresh") is False, "combat metadata packet must record current stale runtime state")
    boundaries = "\n".join(packet.get("evidenceBoundary", []))
    for token in [
        "read-only metadata/listing inspection",
        "does not invoke methods",
        "method_signatures lists metadata only",
        "Owner getter resolve requests are metadata-only",
        "do not call getters or discover live instances",
        "Do not expose ai_start_combat",
        "ai_observe confirms mode battle",
    ]:
        require(token in boundaries, f"combat metadata packet evidence boundary missing: {token}")
    requests = packet.get("liveProbeRequests")
    require(isinstance(requests, list) and len(requests) >= 11, "combat metadata packet must keep the full metadata request set")
    allowed_commands = {"method_signatures", "resolve_decomp_method"}
    labels = set()
    for request in requests:
        labels.add(request.get("label"))
        require(request.get("command") in allowed_commands, f"combat metadata packet contains non-read-only command: {request.get('command')}")
        payload = request.get("payload", {})
        require(isinstance(payload, dict), "combat metadata packet request payload must be an object")
        require("typeName" in payload, f"combat metadata packet request missing typeName: {request}")
        forbidden_payload_keys = {"invoke", "apply", "set", "write", "token"}
        require(not (forbidden_payload_keys & set(payload)), f"combat metadata packet payload contains mutation-looking key: {request}")
    for label in [
        "eys method signatures",
        "cux method signatures",
        "owner BhWindowWorld signatures",
        "owner BhWindowHero signatures",
        "owner BhWindowMagic signatures",
        "session root fda signatures",
        "resolve eys dvf",
        "resolve eys bhzm",
        "resolve eys bhzo",
        "resolve eys bhzj",
        "resolve cux hsf",
        "resolve owner BhWindowWorld get_sideCheats",
        "resolve owner BhWindowHero get_sideCheats",
        "resolve owner BhWindowMagic get_sideCheats",
        "resolve session root fda sideCheats getter",
    ]:
        require(label in labels, f"combat metadata packet missing request: {label}")
    packet_text = json.dumps(packet, sort_keys=True)
    for token in [
        "ObjectPublicInciObInciBoObStInciUnique",
        "Object1PublicIncaStIncaBoStcaInStUnique",
        "Hex.Cheat.UI.BhWindowWorld",
        "Hex.Cheat.UI.BhWindowHero",
        "Hex.Cheat.UI.BhWindowMagic",
        "ObjectPublicObBhcjObIncjSiObIncoUnique",
        "System.Void dvf()",
        "System.Void bhzm()",
        "System.Void bhzo()",
        "System.Void bhzj(System.Boolean a)",
        "Hex.Processing.ECmd hsf()",
        "ObjectPublicInciObInciBoObStInciUnique get_sideCheats()",
        "ObjectPublicInciObInciBoObStInciUnique get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0()",
        "signature_match",
        "After getter metadata resolves",
        "runtime_callable_ordinal_match",
    ]:
        require(token in packet_text, f"combat metadata packet missing token: {token}")

def validate_combat_owner_discovery_packet() -> None:
    with OWNER_DISCOVERY_PACKET.open("r", encoding="utf-8") as handle:
        packet = json.load(handle)
    require(packet.get("schemaVersion") == "ai-start-combat-owner-discovery-probe.v1", "combat owner-discovery packet schemaVersion drifted")
    require(packet.get("status") == "source-prepared-only", "combat owner-discovery packet must remain source-prepared only")
    exposure = packet.get("commandExposure", "")
    require("ai_start_combat and ai_open_town must remain absent" in exposure, "combat owner-discovery packet must preserve absent command warning")
    freshness = packet.get("freshnessPreflight", {})
    require(freshness.get("requiredBeforeLiveProbe") is True, "combat owner-discovery packet must require freshness preflight")
    require("check_runtime_freshness.mjs" in freshness.get("command", ""), "combat owner-discovery packet must point at freshness helper")
    require("--require-fresh" in freshness.get("command", ""), "combat owner-discovery packet must require hard-fail freshness preflight")
    require(freshness.get("lastKnownBlockedState", {}).get("fresh") is False, "combat owner-discovery packet must record current stale runtime state")
    boundaries = "\n".join(packet.get("evidenceBoundary", []))
    for token in [
        "read-only exact Unity component discovery",
        "does not invoke methods, call getters, or mutate state",
        "does not use component_member_path or allowProperties",
        "Do not expose ai_start_combat",
        "ai_observe confirms mode battle",
    ]:
        require(token in boundaries, f"combat owner-discovery packet evidence boundary missing: {token}")
    requests = packet.get("liveProbeRequests")
    require(isinstance(requests, list) and len(requests) >= 4, "combat owner-discovery packet must keep the owner component request set")
    labels = set()
    component_types = set()
    for request in requests:
        labels.add(request.get("label"))
        require(request.get("command") == "unity_components_by_type", f"combat owner-discovery packet contains non-discovery command: {request.get('command')}")
        payload = request.get("payload", {})
        require(isinstance(payload, dict), "combat owner-discovery packet request payload must be an object")
        component_type = payload.get("componentType") or payload.get("typeName")
        component_types.add(component_type)
        require(component_type in {"Hex.Cheat.UI.BhWindowWorld", "Hex.Cheat.UI.BhWindowHero", "Hex.Cheat.UI.BhWindowMagic"}, f"combat owner-discovery packet has unsupported component type: {component_type}")
        require(payload.get("fieldLimit", 0) <= 40, "combat owner-discovery packet fieldLimit too broad")
        require(payload.get("limit", 0) <= 120, "combat owner-discovery packet limit too broad")
        forbidden_payload_keys = {"invoke", "apply", "set", "write", "token", "command", "memberPath", "allowProperties"}
        require(not (forbidden_payload_keys & set(payload)), f"combat owner-discovery packet payload contains forbidden key: {request}")
    for label in [
        "discover active BhWindowWorld owners",
        "discover inactive BhWindowWorld owners",
        "discover active BhWindowHero owners",
        "discover active BhWindowMagic owners",
    ]:
        require(label in labels, f"combat owner-discovery packet missing request: {label}")
    require({"Hex.Cheat.UI.BhWindowWorld", "Hex.Cheat.UI.BhWindowHero", "Hex.Cheat.UI.BhWindowMagic"} <= component_types, "combat owner-discovery packet missing generated owner component type")
    packet_text = json.dumps(packet, sort_keys=True)
    for token in [
        "unity_components_by_type",
        "Hex.Cheat.UI.BhWindowWorld",
        "Hex.Cheat.UI.BhWindowHero",
        "Hex.Cheat.UI.BhWindowMagic",
        "objectIds",
        "Do not enable allowProperties or call get_sideCheats()",
    ]:
        require(token in packet_text, f"combat owner-discovery packet missing token: {token}")
def validate_handoff_docs() -> None:
    plan = read(PLAN_DOC)
    agents = read(AGENTS)
    require("Current step: continue Step 4" in plan, "plan must preserve current Step 4 handoff")
    require("setup-command proof/exposure for `ai_open_town` or `ai_start_combat`" in plan, "plan must name current town/combat setup focus")
    require("Still unproven/absent: `ai_open_town`, `ai_start_combat`" in plan, "plan must keep town/combat commands unproven/absent")
    require("Latest `ai_open_town` proof attempt is falsified" in plan, "plan must preserve falsified town-open route warning")
    require("Step 4 is partially complete" in plan, "plan status must keep Step 4 partial, not complete")
    require("Supported emitted/executable actions: `click`, `submit`" in plan, "plan must limit action kinds to proven click/submit")
    for unproven_kind in ["double_click", "hover", "key"]:
        require(f"`{unproven_kind}`" in plan and "remain unexposed" in plan, f"plan must record unproven action kind boundary: {unproven_kind}")
    require("static/protocol proof only" in plan, "plan must distinguish protocol proof from runtime proof")
    require("MCP-level unproven-command rejection" in plan, "plan must preserve MCP-only absent-command proof boundary")
    for command in PROVEN_COMMANDS:
        require(f"`{command}`" in plan or command in plan, f"plan missing proven command breadcrumb: {command}")
    for command in ABSENT_COMMANDS:
        require(f"`{command}`" in agents, f"AGENTS missing absent command breadcrumb: {command}")
    require("not live runtime proof" in agents, "AGENTS must distinguish static/protocol proof from live runtime proof")
    require("broader stale-action negatives and town/combat remain unproven" in agents, "AGENTS must preserve remaining negative/runtime gaps")

def validate_release_exclusion() -> None:
    text = read(CSPROJ)
    require("RELEASE_CANDIDATE_BUILD" in text, "release candidate define missing")
    for name in [
        "Homm3AiDriverBridge.cs",
        "Homm3AiDriverBridge.ScreenDump.cs",
        "Homm3AiDriverBridge.Hover.cs",
        "Homm3AiDriverBridge.Focus.cs",
        "Homm3AiDriverBridge.Pilot.cs",
    ]:
        pattern = rf'<Compile\s+Remove="{re.escape(name)}"\s+Condition="\'\$\(ReleaseCandidateBuild\)\' == \'true\'"\s*/>'
        require(re.search(pattern, text) is not None, f"{name} release-candidate compile exclusion missing")


def main() -> int:
    try:
        validate_bridge_source()
        validate_mcp_server()
        validate_mcp_smoke_test()
        validate_runtime_freshness_helper()
        validate_combat_metadata_runner()
        validate_combat_owner_discovery_runner()
        validate_mcp_readme()
        validate_schemas()
        validate_static_decomp_artifacts()
        validate_game_symbols()
        validate_static_evidence_notes()
        validate_combat_metadata_packet()
        validate_combat_owner_discovery_packet()
        validate_handoff_docs()
        validate_release_exclusion()
    except AssertionError as exc:
        print(f"AI driver static validation failed: {exc}", file=sys.stderr)
        return 1
    print("AI driver static validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



