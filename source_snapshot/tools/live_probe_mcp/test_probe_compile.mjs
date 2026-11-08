import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile, copyFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const serverPath = path.join(repoRoot, "tools", "live_probe_mcp", "server.mjs");

function findCecilPath() {
  const candidates = [process.env.OLDEN_LIVE_PROBE_TEST_CECIL];
  const packageRoot = path.join(os.homedir(), ".nuget", "packages", "mono.cecil");
  return readdir(packageRoot, { withFileTypes: true })
    .then((entries) => entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort().reverse())
    .then((names) => {
      for (const version of names) candidates.push(path.join(packageRoot, version, "lib", "netstandard2.0", "Mono.Cecil.dll"));
      return firstExisting(candidates);
    })
    .catch(() => {
      return firstExisting(candidates);
    });
}

async function firstExisting(candidates) {
  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      await stat(candidate);
      return candidate;
    } catch {
    }
  }
  throw new Error("Mono.Cecil is required by this isolated fixture; set OLDEN_LIVE_PROBE_TEST_CECIL or restore the repo's Mono.Cecil tool dependency.");
}

function frame(message) {
  const body = JSON.stringify(message);
  return `Content-Length: ${Buffer.byteLength(body, "utf8")}\r\n\r\n${body}`;
}

function createClient(bridgeDir, tempDir, dotnetHome) {
  const child = spawn(process.execPath, [serverPath], {
    cwd: repoRoot,
    env: {
      ...process.env,
      OLDEN_LIVE_PROBE_BRIDGE_DIR: bridgeDir,
      OLDEN_LIVE_PROBE_TIMEOUT_MS: "5000",
      TEMP: tempDir,
      TMP: tempDir,
      TMPDIR: tempDir,
      DOTNET_CLI_HOME: dotnetHome,
      DOTNET_CLI_TELEMETRY_OPTOUT: "1",
      DOTNET_SKIP_FIRST_TIME_EXPERIENCE: "1",
      NUGET_PACKAGES: path.join(dotnetHome, "nuget")
    },
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true
  });
  let buffer = Buffer.alloc(0);
  const responses = new Map();
  const waiters = new Map();
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr = (stderr + chunk.toString()).slice(-8000); });
  child.stdout.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    while (true) {
      const headerEnd = buffer.indexOf("\r\n\r\n");
      if (headerEnd < 0) return;
      const header = buffer.subarray(0, headerEnd).toString("utf8");
      const match = /content-length:\s*(\d+)/i.exec(header);
      if (!match) throw new Error(`Invalid MCP header: ${header}`);
      const bodyStart = headerEnd + 4;
      const bodyEnd = bodyStart + Number(match[1]);
      if (buffer.length < bodyEnd) return;
      const parsed = JSON.parse(buffer.subarray(bodyStart, bodyEnd).toString("utf8"));
      buffer = buffer.subarray(bodyEnd);
      const waiter = waiters.get(parsed.id);
      if (waiter) {
        waiters.delete(parsed.id);
        waiter.resolve(parsed);
      } else {
        responses.set(parsed.id, parsed);
      }
    }
  });
  return {
    child,
    get stderr() { return stderr; },
    request(id, method, params) {
      const existing = responses.get(id);
      if (existing) {
        responses.delete(id);
        return Promise.resolve(existing);
      }
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          waiters.delete(id);
          reject(new Error(`MCP request ${id} timed out. stderr: ${stderr}`));
        }, 150000);
        waiters.set(id, { resolve: (value) => { clearTimeout(timer); resolve(value); } });
        child.stdin.write(frame({ jsonrpc: "2.0", id, method, params }));
      });
    }
  };
}

async function waitForBridgeRequest(bridgeDir, seenIds, timeoutMs = 120000) {
  const inbox = path.join(bridgeDir, "inbox");
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let entries = [];
    try {
      entries = await readdir(inbox);
    } catch {
    }
    for (const name of entries.filter((item) => item.endsWith(".json"))) {
      const id = path.basename(name, ".json");
      if (seenIds.has(id)) continue;
      const request = JSON.parse(await readFile(path.join(inbox, name), "utf8"));
      seenIds.add(id);
      return request;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("Timed out waiting for the fake bridge request.");
}

async function respondToBridge(bridgeDir, request, response) {
  const outbox = path.join(bridgeDir, "outbox");
  await mkdir(outbox, { recursive: true });
  await writeFile(path.join(outbox, `${request.id}.json`), JSON.stringify({ id: request.id, ...response }), "utf8");
}

async function run() {
  const cecilPath = await findCecilPath();
  const scratchRoot = await mkdtemp(path.join(repoRoot, ".tmp_live_probe_compile_"));
  const tempDir = path.join(scratchRoot, "temp");
  const dotnetHome = path.join(scratchRoot, "dotnet-home");
  const bridgeDir = path.join(scratchRoot, "fixture", "BepInEx", "plugins", "OfflineUnlockMod", "live_probe_bridge");
  const cecilDir = path.join(scratchRoot, "fixture", "BepInEx", "core");
  const seenIds = new Set();
  const startedAt = Date.now();
  let compileMs = 0;
  let failClosedMs = 0;
  let client;
  try {
    await Promise.all([mkdir(tempDir, { recursive: true }), mkdir(dotnetHome, { recursive: true }), mkdir(bridgeDir, { recursive: true }), mkdir(cecilDir, { recursive: true })]);
    await copyFile(cecilPath, path.join(cecilDir, "Mono.Cecil.dll"));
    await writeFile(path.join(bridgeDir, "token.txt"), "fixture-token\n", "utf8");
    client = createClient(bridgeDir, tempDir, dotnetHome);

    const validStarted = Date.now();
    const validPromise = client.request(1, "tools/call", {
      name: "volatile_compile_and_run_csharp",
      arguments: {
        source: "namespace Fixture { public static class Entrypoint { public static string Run(string value) { return value; } } }",
        typeName: "Fixture.Entrypoint",
        methodName: "Run",
        reason: "isolated compile contract test",
        payload: "fixture",
        timeoutMs: 5000
      }
    });
    const validBridgeRequest = await waitForBridgeRequest(bridgeDir, seenIds);
    assert.equal(validBridgeRequest.command, "volatile_load_probe_assembly");
    assert.equal(validBridgeRequest.typeName, "Fixture.Entrypoint");
    const acceptedDll = validBridgeRequest.assemblyPath;
    await respondToBridge(bridgeDir, validBridgeRequest, { ok: true, resultText: "fake bridge accepted" });
    const validResponse = await validPromise;
    compileMs = Date.now() - validStarted;
    const validResult = JSON.parse(validResponse.result.content[0].text);
    assert.equal(validResult.ok, true, JSON.stringify(validResult));
    assert.equal(validResult.probe.typeName, "Fixture.Entrypoint");
    assert.equal(validResult.probe.methodName, "Run");
    assert.equal(await stat(acceptedDll).then((item) => item.isFile()), true);

    const projectPath = path.join(validResult.probe.workDir, "LiveProbe.csproj");
    const evaluated = spawn(process.env.DOTNET_EXE || "dotnet", ["msbuild", projectPath, "-nologo", "-getItem:Compile"], {
      cwd: repoRoot,
      env: { ...process.env, DOTNET_CLI_HOME: dotnetHome, DOTNET_CLI_TELEMETRY_OPTOUT: "1", NUGET_PACKAGES: path.join(dotnetHome, "nuget") },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true
    });
    let evaluatedOut = "";
    let evaluatedErr = "";
    evaluated.stdout.on("data", (chunk) => { evaluatedOut += chunk.toString(); });
    evaluated.stderr.on("data", (chunk) => { evaluatedErr += chunk.toString(); });
    const evaluatedCode = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { evaluated.kill(); reject(new Error("MSBuild item evaluation timed out.")); }, 30000);
      evaluated.on("error", reject);
      evaluated.on("close", (code) => { clearTimeout(timer); resolve(code); });
    });
    assert.equal(evaluatedCode, 0, evaluatedErr || evaluatedOut);
    const compileItems = JSON.parse(evaluatedOut).Items.Compile.map((item) => item.Identity);
    assert.ok(compileItems.some((item) => path.basename(item) === "LiveProbe.cs"), `LiveProbe.cs missing from evaluated Compile items: ${evaluatedOut}`);

    const requestsBeforeInvalid = seenIds.size;
    const invalidStarted = Date.now();
    const invalidPromise = client.request(2, "tools/call", {
      name: "volatile_compile_and_run_csharp",
      arguments: {
        source: "namespace Fixture { public static class DifferentType { public static string Run() { return \"not requested\"; } } }",
        typeName: "Fixture.MissingType",
        methodName: "Run",
        reason: "isolated wrong-type rejection test",
        timeoutMs: 5000
      }
    });
    const invalidResponse = await invalidPromise;
    failClosedMs = Date.now() - invalidStarted;
    const invalidResult = JSON.parse(invalidResponse.result.content[0].text);
    assert.equal(invalidResult.ok, false);
    assert.equal(invalidResult.error.code, "compile_failed");
    assert.match(`${invalidResult.stdout}\n${invalidResult.stderr}`, /does not contain a concrete, non-generic requested type/i);
    assert.equal(seenIds.size, requestsBeforeInvalid, "wrong requested type reached the fake bridge");
    assert.equal(await stat(path.join(invalidResult.deployDir, "LiveProbe.dll")).then(() => true, () => false), false, "wrong-type assembly was copied into bridge probes");

    const signatureStarted = Date.now();
    const signaturePromise = client.request(3, "tools/call", {
      name: "volatile_compile_and_run_csharp",
      arguments: {
        source: "namespace Fixture { public static class UnsupportedEntrypoint { public static string Run(int value) { return value.ToString(); } } }",
        typeName: "Fixture.UnsupportedEntrypoint",
        methodName: "Run",
        reason: "isolated unsupported-signature rejection test",
        timeoutMs: 5000
      }
    });
    const signatureResponse = await signaturePromise;
    const signatureResult = JSON.parse(signatureResponse.result.content[0].text);
    assert.equal(signatureResult.ok, false);
    assert.equal(signatureResult.error.code, "compile_failed");
    assert.match(`${signatureResult.stdout}\n${signatureResult.stderr}`, /must declare a static non-generic Run\(\) or Run\(string\) entry point/i);
    assert.equal(seenIds.size, requestsBeforeInvalid, "unsupported entrypoint reached the fake bridge");
    assert.equal(await stat(path.join(signatureResult.deployDir, "LiveProbe.dll")).then(() => true, () => false), false, "unsupported-entrypoint assembly was copied into bridge probes");
    failClosedMs += Date.now() - signatureStarted;

    console.log(`PASS probe compile contract: Compile includes LiveProbe.cs; supported Run(string) accepted; wrong type and signature rejected before fake bridge (${Date.now() - startedAt} ms total, valid=${compileMs} ms, fail-closed=${failClosedMs} ms).`);
  } finally {
    if (client?.child && !client.child.killed) {
      client.child.kill();
      await new Promise((resolve) => client.child.once("close", resolve));
    }
    await rm(scratchRoot, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(`FAIL probe compile contract: ${error.stack || error}`);
  process.exitCode = 1;
});
