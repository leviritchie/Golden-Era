#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import os from "node:os";
import { spawn } from "node:child_process";

const SERVER_NAME = "olden-live-probe";
const SERVER_VERSION = "0.1.0";
const DEFAULT_TIMEOUT_MS = Number(process.env.OLDEN_LIVE_PROBE_TIMEOUT_MS || 10000);

const instructions = [
  "Use this server to inspect the live Olden Era Golden Era probe bridge.",
  "Prefer read-only tools. Treat workbench evidence as diagnostic evidence, not a production fix.",
  "Volatile probe assembly execution is intentionally unsafe and may crash or mutate live game state.",
  "If the bridge is unavailable, ask the user to enable homm3LiveProbeWorkbench or homm3_live_probe_workbench.flag and launch the game."
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
  if (process.env.OLDEN_LIVE_PROBE_BRIDGE_DIR) dirs.push(process.env.OLDEN_LIVE_PROBE_BRIDGE_DIR);
  dirs.push(path.join(process.cwd(), "Heroes of Might & Magic Olden Era Playtest", "BepInEx", "plugins", "OfflineUnlockMod", "live_probe_bridge"));
  dirs.push(path.join(process.cwd(), "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod", "live_probe_bridge"));
  return [...new Set(dirs.map((dir) => path.resolve(dir)))];
}

function resolveBridgeDir() {
  for (const dir of candidateBridgeDirs()) {
    if (fs.existsSync(dir)) return dir;
  }
  return path.resolve(args.bridgeDir || process.env.OLDEN_LIVE_PROBE_BRIDGE_DIR || candidateBridgeDirs()[0]);
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
        message: "Live probe bridge is unavailable. Enable the workbench in-game and pass --bridge-dir or OLDEN_LIVE_PROBE_BRIDGE_DIR if needed."
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

  return {
    id,
    ok: false,
    error: {
      code: "bridge_timeout",
      message: `No response from live probe bridge within ${timeoutMs} ms.`
    },
    bridge: info
  };
}

function xmlEscape(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function existingDlls(dir) {
  try {
    if (!dir || !fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
      .filter((name) => name.toLowerCase().endsWith(".dll"))
      .map((name) => path.join(dir, name));
  } catch {
    return [];
  }
}

function probeReferenceDlls(bridgeDir) {
  const pluginDir = path.dirname(bridgeDir);
  const pluginsDir = path.dirname(pluginDir);
  const bepInExDir = path.dirname(pluginsDir);
  const refs = [
    path.join(pluginDir, "OfflineUnlockMod.dll"),
    ...existingDlls(path.join(bepInExDir, "core")),
    ...existingDlls(path.join(bepInExDir, "interop")),
    ...existingDlls(pluginDir)
  ];
  return [...new Set(refs.map((p) => path.resolve(p)).filter((p) => fs.existsSync(p)))];
}

function runProcess(file, args, options = {}) {
  return new Promise((resolve) => {
    const timeoutMs = Math.max(1000, Math.min(Number(options.timeoutMs || 30000), 120000));
    const spawnOptions = { ...options };
    delete spawnOptions.timeoutMs;
    const child = spawn(file, args, { ...spawnOptions, windowsHide: true });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const limit = 120000;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try {
        child.kill("SIGKILL");
      } catch {
      }
      resolve({ code: -1, timedOut: true, stdout, stderr: `${stderr}\nProcess timed out after ${timeoutMs} ms.` });
    }, timeoutMs);
    const append = (kind, chunk) => {
      const text = chunk.toString();
      if (kind === "stdout") stdout = (stdout + text).slice(-limit);
      else stderr = (stderr + text).slice(-limit);
    };
    child.stdout?.on("data", (chunk) => append("stdout", chunk));
    child.stderr?.on("data", (chunk) => append("stderr", chunk));
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: -1, stdout, stderr: `${stderr}\n${error.message}` });
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code, stdout, stderr });
    });
  });
}

async function compileAndRunCSharpProbe(input = {}) {
  const source = String(input.source || "");
  const typeName = String(input.typeName || "LiveProbe.Script");
  const methodName = String(input.methodName || "Run");
  const reason = String(input.reason || "");
  if (!source.trim()) {
    return { ok: false, error: { code: "bad_request", message: "source is required." } };
  }
  if (!reason.trim()) {
    return { ok: false, error: { code: "bad_request", message: "reason is required." } };
  }
  if (Buffer.byteLength(source, "utf8") > 512000) {
    return { ok: false, error: { code: "source_too_large", message: "source is limited to 512 KiB." } };
  }

  const info = bridgeInfo();
  if (!info.available) {
    return {
      ok: false,
      error: { code: "bridge_unavailable", message: "Live probe bridge is unavailable; cannot locate probe output directory." },
      bridge: info
    };
  }

  const probeRoot = path.join(info.bridgeDir, "probes");
  fs.mkdirSync(probeRoot, { recursive: true });
  const id = crypto.randomUUID ? crypto.randomUUID() : crypto.randomBytes(16).toString("hex");
  const workDir = path.join(os.tmpdir(), "olden-live-probe", `probe_${id}`);
  const deployDir = path.join(probeRoot, `probe_${id}`);
  fs.mkdirSync(workDir, { recursive: true });
  fs.mkdirSync(deployDir, { recursive: true });
  const outputDir = path.join(workDir, "bin");
  const builtDllPath = path.join(outputDir, "LiveProbe.dll");
  const dllPath = path.join(deployDir, "LiveProbe.dll");
  const references = probeReferenceDlls(info.bridgeDir);
  const cecilPath = references.find((ref) => path.basename(ref).toLowerCase() === "mono.cecil.dll");
  if (!cecilPath) {
    return {
      ok: false,
      error: { code: "metadata_verifier_unavailable", message: "Mono.Cecil is required to validate the compiled probe before deployment." },
      workDir,
      deployDir
    };
  }
  const referenceXml = references.map((ref, index) => {
    const include = path.basename(ref, ".dll") || `ProbeRef${index}`;
    return `    <Reference Include="${xmlEscape(include)}"><HintPath>${xmlEscape(ref)}</HintPath><Private>false</Private></Reference>`;
  }).join("\n");
  const csproj = `<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>disable</Nullable>
    <LangVersion>latest</LangVersion>
    <AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <CopyLocalLockFileAssemblies>false</CopyLocalLockFileAssemblies>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
    <!-- The SDK excludes OutputPath from default Compile globs; keep it below the source root. -->
    <OutputPath>${xmlEscape(outputDir)}\\</OutputPath>
  </PropertyGroup>
  <ItemGroup>
${referenceXml}
  </ItemGroup>
  <UsingTask TaskName="ValidateLiveProbeAssembly" TaskFactory="RoslynCodeTaskFactory" AssemblyFile="$(MSBuildToolsPath)\\Microsoft.Build.Tasks.Core.dll">
    <ParameterGroup>
      <AssemblyPath ParameterType="System.String" Required="true" />
      <RequestedTypeName ParameterType="System.String" Required="true" />
      <RequestedMethodName ParameterType="System.String" Required="true" />
    </ParameterGroup>
    <Task>
      <Reference Include="${xmlEscape(cecilPath)}" />
      <Using Namespace="System" />
      <Using Namespace="System.IO" />
      <Using Namespace="Mono.Cecil" />
      <Code Type="Fragment" Language="cs"><![CDATA[
using (var module = ModuleDefinition.ReadModule(AssemblyPath))
{
    var typeName = RequestedTypeName.Replace('+', '/');
    var type = module.GetType(typeName);
    if (type == null || type.HasGenericParameters || type.IsInterface)
    {
        Log.LogError("Probe assembly does not contain a concrete, non-generic requested type: " + RequestedTypeName);
        return false;
    }

    var hasSupportedEntryPoint = false;
    foreach (var method in type.Methods)
    {
        if (method.Name != RequestedMethodName || !method.IsStatic || method.IsAbstract || method.HasGenericParameters)
            continue;
        if (method.Parameters.Count == 0)
        {
            hasSupportedEntryPoint = true;
            break;
        }
        if (method.Parameters.Count == 1
            && method.Parameters[0].ParameterType.MetadataType == MetadataType.String)
        {
            hasSupportedEntryPoint = true;
            break;
        }
    }

    if (!hasSupportedEntryPoint)
    {
        Log.LogError("Probe type " + RequestedTypeName + " must declare a static non-generic "
            + RequestedMethodName + "() or " + RequestedMethodName + "(string) entry point.");
        return false;
    }
}
      ]]></Code>
    </Task>
  </UsingTask>
  <Target Name="ValidateLiveProbeAssembly" AfterTargets="Build">
    <ValidateLiveProbeAssembly AssemblyPath="$(TargetPath)" RequestedTypeName="${xmlEscape(typeName)}" RequestedMethodName="${xmlEscape(methodName)}" />
  </Target>
</Project>
`;
  fs.writeFileSync(path.join(workDir, "LiveProbe.csproj"), csproj, "utf8");
  fs.writeFileSync(path.join(workDir, "LiveProbe.cs"), source, "utf8");

  const compileTimeoutMs = Math.max(1000, Math.min(Number(input.compileTimeoutMs || 30000), 120000));
  const build = await runProcess("dotnet", ["build", "LiveProbe.csproj", "-c", "Release", "-v", "minimal", "-nologo"], { cwd: workDir, timeoutMs: compileTimeoutMs });
  if (build.timedOut) {
    return {
      ok: false,
      error: { code: "compile_timeout", message: `dotnet build exceeded ${compileTimeoutMs} ms and was killed.` },
      workDir,
      deployDir,
      stdout: build.stdout,
      stderr: build.stderr
    };
  }
  if (build.code !== 0 || !fs.existsSync(builtDllPath)) {
    return {
      ok: false,
      error: { code: "compile_failed", message: `dotnet build exited ${build.code}` },
      workDir,
      deployDir,
      stdout: build.stdout,
      stderr: build.stderr
    };
  }
  fs.copyFileSync(builtDllPath, dllPath);
  const builtPdbPath = path.join(outputDir, "LiveProbe.pdb");
  if (fs.existsSync(builtPdbPath)) {
    try {
      fs.copyFileSync(builtPdbPath, path.join(deployDir, "LiveProbe.pdb"));
    } catch {
    }
  }

  const timeoutMs = Math.max(1000, Math.min(Number(input.timeoutMs || DEFAULT_TIMEOUT_MS), 120000));
  const response = await callBridge("volatile_load_probe_assembly", {
    assemblyPath: dllPath,
    typeName,
    methodName,
    reason,
    userPayload: input.payload === undefined ? "" : String(input.payload)
  }, timeoutMs);
  return {
    ...response,
    probe: {
      workDir,
      deployDir,
      assemblyPath: dllPath,
      typeName,
      methodName,
      referenceCount: references.length,
      buildStdout: build.stdout.slice(-4000),
      buildStderr: build.stderr.slice(-4000)
    }
  };
}

function toolSchemas() {
  return [
    {
      name: "bridge_info",
      description: "Inspect where the MCP adapter is looking for the live game bridge and whether it is available.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "status",
      description: "Read live workbench status from the game bridge.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "reload_recipes",
      description: "Ask the live game bridge to reload homm3_live_probe_recipes.json.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "list_recipes",
      description: "Return the live bridge's recipe validation summary.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "list_triggers",
      description: "List curated trigger and action names known to the live bridge.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "mutation_capabilities",
      description: "List guarded and volatile live-writing capabilities with risk definitions.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }
    },
    {
      name: "query_types",
      description: "Search loaded managed/interop type names in the live game process.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string" },
          limit: { type: "integer", minimum: 1, maximum: 200 }
        }
      }
    },
    {
      name: "method_signatures",
      description: "List declared method signatures for an exact live type name without invoking them.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["typeName"],
        properties: {
          typeName: { type: "string" },
          limit: { type: "integer", minimum: 1, maximum: 200 }
        }
      }
    },
    {
      name: "field_signatures",
      description: "List declared field names and field types for an exact live type name without reading field values.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["typeName"],
        properties: {
          typeName: { type: "string" },
          limit: { type: "integer", minimum: 1, maximum: 200 }
        }
      }
    },
    {
      name: "unity_renderers",
      description: "Return bounded read-only Unity GameObject and Renderer summaries for live objects whose name or transform path contains a filter string.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["nameContains"],
        properties: {
          nameContains: { type: "string" },
          limit: { type: "integer", minimum: 1, maximum: 120 }
        }
      }
    },
    {
      name: "unity_ui_surfaces",
      description: "Return bounded read-only Unity UI surface summaries for live GameObjects whose name or transform path contains a filter string.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["nameContains"],
        properties: {
          nameContains: { type: "string" },
          limit: { type: "integer", minimum: 1, maximum: 120 }
        }
      }
    },
    {
      name: "unity_objects_exact",
      description: "Read-only lightweight exact GameObject lookup by name or transform path. Useful for non-UI-heavy root existence checks.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {
          name: { type: "string" },
          exactName: { type: "string" },
          path: { type: "string" },
          exactPath: { type: "string" },
          requireActiveHierarchy: { type: "boolean" },
          limit: { type: "integer", minimum: 1, maximum: 120 }
        }
      }
    },
    {
      name: "unity_components_by_type",
      description: "Read-only bounded lookup for live Unity components by exact component type. Returns GameObject objectIds usable with component_member_path.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["componentType"],
        properties: {
          componentType: { type: "string" },
          typeName: { type: "string" },
          scene: { type: "string" },
          nameContains: { type: "string" },
          pathContains: { type: "string" },
          requireActiveHierarchy: { type: "boolean" },
          fieldLimit: { type: "integer", minimum: 0, maximum: 40 },
          limit: { type: "integer", minimum: 1, maximum: 120 }
        }
      }
    },
    {
      name: "component_member_path",
      description: "Read-only exact field/member path inspection on a captured GameObject or named component. Supports [index] access; properties are disabled unless allowProperties=true.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["memberPath"],
        properties: {
          objectId: { type: "integer" },
          name: { type: "string" },
          path: { type: "string" },
          componentType: { type: "string" },
          memberPath: { type: "string" },
          allowProperties: { type: "boolean" },
          requireActiveHierarchy: { type: "boolean" },
          fieldLimit: { type: "integer", minimum: 0, maximum: 80 },
          maxSegments: { type: "integer", minimum: 1, maximum: 32 }
        }
      }
    },
    {
      name: "town_ui_state",
      description: "Read cached town UI wrapper/faction/city state plus OfflineUnlockStrongholdTownLayers root counters.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {}
      }
    },
    {
      name: "set_unity_ui_property",
      description: "Guarded live write for curated Unity UI properties on a captured objectId. Prefer expectedOldValue.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["objectId", "componentType", "property", "value"],
        properties: {
          objectId: { type: "integer" },
          componentType: { type: "string" },
          property: { type: "string" },
          value: { type: "string" },
          expectedOldValue: { type: "string" }
        }
      }
    },
    {
      name: "set_nearest_canvas_property",
      description: "Guarded Canvas-only write: resolve nearest parent Canvas from a captured descendant objectId, scoped to active scene or additive CityUI while cityHuman/cityHuman2 is active.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["objectId", "property", "value"],
        properties: {
          objectId: { type: "integer" },
          property: { type: "string", enum: ["enabled", "overrideSorting", "sortingOrder", "sortingLayerID", "sortingLayerName", "planeDistance"] },
          value: { type: "string" },
          expectedOldValue: { type: "string" }
        }
      }
    },
    {
      name: "set_canvas_by_name",
      description: "Guarded Canvas-only write by exact Canvas GameObject name, scoped to active scene or additive CityUI while cityHuman/cityHuman2 is active. Fails on ambiguous names.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["canvasName", "property", "value"],
        properties: {
          canvasName: { type: "string" },
          property: { type: "string", enum: ["enabled", "overrideSorting", "sortingOrder", "sortingLayerID", "sortingLayerName", "planeDistance"] },
          value: { type: "string" },
          expectedOldValue: { type: "string" }
        }
      }
    },
    {
      name: "volatile_set_canvas_property",
      description: "VOLATILE real Canvas mutation by captured objectId, exact canvasName/name, or exact path. Bounded to active scene/additive CityUI town scope and Canvas ordering properties.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["property", "value", "reason"],
        properties: {
          objectId: { type: "integer" },
          canvasName: { type: "string" },
          name: { type: "string" },
          path: { type: "string" },
          property: { type: "string", enum: ["enabled", "overrideSorting", "sortingOrder", "sortingLayerID", "sortingLayerName", "planeDistance"] },
          value: { type: "string" },
          expectedOldValue: { type: "string" },
          reason: { type: "string" }
        }
      }
    },
    {
      name: "volatile_set_ui_sibling",
      description: "VOLATILE real UI Transform sibling-order mutation by captured objectId, exact name, or exact path. Supports setFirst, setLast, setIndex.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["operation", "reason"],
        properties: {
          objectId: { type: "integer" },
          name: { type: "string" },
          path: { type: "string" },
          operation: { type: "string", enum: ["setFirst", "setLast", "setIndex"] },
          index: { type: "integer", minimum: 0 },
          expectedOldSiblingIndex: { type: "string" },
          expectedOldValue: { type: "string" },
          reason: { type: "string" }
        }
      }
    },
    {
      name: "volatile_invoke_exact_noarg_getter",
      description: "VOLATILE semantic getter probe. Invokes only an exact no-arg getter present in the built-in allowlist or live volatile_exact_getter_allowlist.json.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["methodName", "expectedReturnTypeFullName", "reason"],
        properties: {
          target: { type: "string", enum: ["cachedTownWrapper"] },
          cachedTownWrapper: { type: "boolean" },
          objectId: { type: "integer" },
          name: { type: "string" },
          path: { type: "string" },
          componentType: { type: "string" },
          methodName: { type: "string" },
          expectedReturnTypeFullName: { type: "string" },
          reason: { type: "string" }
        }
      }
    },
    {
      name: "volatile_invoke_allowlisted_method",
      description: "VOLATILE exact method invocation. Requires a matching entry in live volatile_operation_allowlist.json and supports only primitive/string/enum arguments.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["methodName", "reason"],
        properties: {
          target: { type: "string", enum: ["cachedTownWrapper"] },
          cachedTownWrapper: { type: "boolean" },
          objectId: { type: "integer" },
          name: { type: "string" },
          path: { type: "string" },
          componentType: { type: "string" },
          methodName: { type: "string" },
          expectedReturnTypeFullName: { type: "string", default: "System.Void" },
          argCount: { type: "integer", minimum: 0, maximum: 4 },
          arg0TypeFullName: { type: "string" },
          arg0Value: { type: "string" },
          arg1TypeFullName: { type: "string" },
          arg1Value: { type: "string" },
          arg2TypeFullName: { type: "string" },
          arg2Value: { type: "string" },
          arg3TypeFullName: { type: "string" },
          arg3Value: { type: "string" },
          reason: { type: "string" }
        }
      }
    },
    {
      name: "volatile_set_allowlisted_member",
      description: "VOLATILE exact primitive/string/enum field or property write. Requires a matching entry in live volatile_operation_allowlist.json, supports memberName or nested memberPath, expectedOldValue, and retention checks.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["value", "reason"],
        properties: {
          target: { type: "string", enum: ["cachedTownWrapper"] },
          cachedTownWrapper: { type: "boolean" },
          objectId: { type: "integer" },
          name: { type: "string" },
          path: { type: "string" },
          componentType: { type: "string" },
          memberKind: { type: "string", enum: ["field", "property"] },
          memberName: { type: "string" },
          memberPath: { type: "string" },
          maxSegments: { type: "integer" },
          allowProperties: { type: "boolean" },
          expectedMemberTypeFullName: { type: "string" },
          value: { type: "string" },
          expectedOldValue: { type: "string" },
          reason: { type: "string" }
        }
      }
    },
    {
      name: "volatile_refresh_town_layers_from_cached_wrapper",
      description: "VOLATILE one-shot semantic action: recapture ObjCity/ObjCityConfig from cached town wrapper via exact allowlisted getters, then run existing backdrop/layer sync once.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["reason"],
        properties: {
          reason: { type: "string" }
        }
      }
    },
    {
      name: "set_primitive_component_field",
      description: "Guarded live write for primitive/string/enum fields on a named component attached to a captured objectId.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["objectId", "componentType", "fieldName", "value"],
        properties: {
          objectId: { type: "integer" },
          componentType: { type: "string" },
          fieldName: { type: "string" },
          value: { type: "string" },
          expectedOldValue: { type: "string" }
        }
      }
    },
    {
      name: "invoke_allowlisted_method",
      description: "Invoke exact allowlisted methods only: GameObject.SetActive, Transform.SetAsFirstSibling, Transform.SetAsLastSibling.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["objectId", "methodName"],
        properties: {
          objectId: { type: "integer" },
          methodName: { type: "string" },
          value: { type: "boolean" }
        }
      }
    },
    {
      name: "create_ui_diagnostic_overlay",
      description: "Create a non-raycast diagnostic Image child under a RectTransform target to prove UI bounds/draw order.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["objectId"],
        properties: {
          objectId: { type: "integer" },
          color: { type: "string" },
          alpha: { type: "number", minimum: 0, maximum: 1 }
        }
      }
    },
    {
      name: "remove_ui_diagnostic_overlays",
      description: "Remove diagnostic overlays created by create_ui_diagnostic_overlay, optionally under one objectId.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        properties: {
          objectId: { type: "integer" }
        }
      }
    },
    {
      name: "enable_precompiled_patch",
      description: "Reserved guarded command for toggling dormant precompiled patches. This build reports no registered patches.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["patchId", "enabled"],
        properties: {
          patchId: { type: "string" },
          enabled: { type: "boolean" }
        }
      }
    },
    {
      name: "volatile_compile_and_run_csharp",
      description: "VOLATILE unsafe probe runner. Compiles arbitrary C# into live_probe_bridge/probes, loads it into the game process, and invokes a static zero-arg or single-string method on Unity's main thread. Crashes and state mutation are possible.",
      inputSchema: {
        type: "object",
        additionalProperties: false,
        required: ["source", "typeName", "reason"],
        properties: {
          source: { type: "string" },
          typeName: { type: "string" },
          methodName: { type: "string" },
          reason: { type: "string" },
          payload: { type: "string" },
          compileTimeoutMs: { type: "integer", minimum: 1000, maximum: 120000 },
          timeoutMs: { type: "integer", minimum: 1000, maximum: 120000 }
        }
      }
    },
    ...[
      ["volatile_reflection_invoke", "VOLATILE last-resort arbitrary reflection invocation. This build fails closed."],
      ["volatile_generated_getter_sweep", "VOLATILE last-resort generated getter exploration. This build fails closed."],
      ["volatile_write_object_reference", "VOLATILE last-resort object reference writes. This build fails closed."],
      ["volatile_autopatch_same_shape_methods", "VOLATILE last-resort same-shape Harmony patching. This build fails closed."],
      ["volatile_global_ui_setter_patch", "VOLATILE last-resort global UI setter patching. This build fails closed."]
    ].map(([name, description]) => ({
      name,
      description,
      inputSchema: {
        type: "object",
        additionalProperties: true,
        properties: {
          reason: { type: "string" }
        }
      }
    }))
  ];
}

async function callTool(name, input = {}) {
  switch (name) {
    case "bridge_info":
      return bridgeInfo();
    case "status": {
      return callBridge("status", {});
    }
    case "reload_recipes":
      return callBridge("reload_recipes", {});
    case "list_recipes":
      return callBridge("list_recipes", {});
    case "list_triggers":
      return callBridge("list_triggers", {});
    case "mutation_capabilities":
      return callBridge("mutation_capabilities", {});
    case "query_types":
      return callBridge("query_types", { query: String(input.query || ""), limit: input.limit ?? 40 });
    case "method_signatures":
      return callBridge("method_signatures", { typeName: String(input.typeName || ""), limit: input.limit ?? 80 });
    case "field_signatures":
      return callBridge("field_signatures", { typeName: String(input.typeName || ""), limit: input.limit ?? 120 });
    case "unity_renderers":
      return callBridge("unity_renderers", { nameContains: String(input.nameContains || ""), limit: input.limit ?? 40 });
    case "unity_ui_surfaces":
      return callBridge("unity_ui_surfaces", { nameContains: String(input.nameContains || ""), limit: input.limit ?? 40 });
    case "unity_objects_exact":
      return callBridge("unity_objects_exact", {
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.exactName === undefined ? {} : { exactName: String(input.exactName) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        ...(input.exactPath === undefined ? {} : { exactPath: String(input.exactPath) }),
        ...(input.requireActiveHierarchy === undefined ? {} : { requireActiveHierarchy: Boolean(input.requireActiveHierarchy) }),
        limit: input.limit ?? 40
      });
    case "unity_components_by_type":
      return callBridge("unity_components_by_type", {
        componentType: String(input.componentType || input.typeName || ""),
        ...(input.typeName === undefined ? {} : { typeName: String(input.typeName) }),
        ...(input.scene === undefined ? {} : { scene: String(input.scene) }),
        ...(input.nameContains === undefined ? {} : { nameContains: String(input.nameContains) }),
        ...(input.pathContains === undefined ? {} : { pathContains: String(input.pathContains) }),
        ...(input.requireActiveHierarchy === undefined ? {} : { requireActiveHierarchy: Boolean(input.requireActiveHierarchy) }),
        ...(input.fieldLimit === undefined ? {} : { fieldLimit: input.fieldLimit }),
        limit: input.limit ?? 40
      });
    case "component_member_path":
      return callBridge("component_member_path", {
        ...(input.objectId === undefined ? {} : { objectId: input.objectId }),
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        ...(input.componentType === undefined ? {} : { componentType: String(input.componentType) }),
        memberPath: String(input.memberPath || ""),
        ...(input.allowProperties === undefined ? {} : { allowProperties: Boolean(input.allowProperties) }),
        ...(input.requireActiveHierarchy === undefined ? {} : { requireActiveHierarchy: Boolean(input.requireActiveHierarchy) }),
        ...(input.fieldLimit === undefined ? {} : { fieldLimit: input.fieldLimit }),
        ...(input.maxSegments === undefined ? {} : { maxSegments: input.maxSegments })
      });
    case "town_ui_state":
      return callBridge("town_ui_state", {});
    case "set_unity_ui_property":
      return callBridge("set_unity_ui_property", {
        objectId: input.objectId ?? 0,
        componentType: String(input.componentType || ""),
        property: String(input.property || ""),
        value: String(input.value ?? ""),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "set_nearest_canvas_property":
      return callBridge("set_nearest_canvas_property", {
        objectId: input.objectId ?? 0,
        property: String(input.property || ""),
        value: String(input.value ?? ""),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "set_canvas_by_name":
      return callBridge("set_canvas_by_name", {
        canvasName: String(input.canvasName || ""),
        property: String(input.property || ""),
        value: String(input.value ?? ""),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "volatile_set_canvas_property":
      return callBridge("volatile_set_canvas_property", {
        ...(input.objectId === undefined ? {} : { objectId: input.objectId }),
        ...(input.canvasName === undefined ? {} : { canvasName: String(input.canvasName) }),
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        property: String(input.property || ""),
        value: String(input.value ?? ""),
        reason: String(input.reason || ""),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "volatile_set_ui_sibling":
      return callBridge("volatile_set_ui_sibling", {
        ...(input.objectId === undefined ? {} : { objectId: input.objectId }),
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        operation: String(input.operation || ""),
        reason: String(input.reason || ""),
        ...(input.index === undefined ? {} : { index: input.index }),
        ...(input.expectedOldSiblingIndex === undefined ? {} : { expectedOldSiblingIndex: String(input.expectedOldSiblingIndex) }),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "volatile_invoke_exact_noarg_getter":
      return callBridge("volatile_invoke_exact_noarg_getter", {
        ...(input.target === undefined ? {} : { target: String(input.target) }),
        ...(input.cachedTownWrapper === undefined ? {} : { cachedTownWrapper: Boolean(input.cachedTownWrapper) }),
        ...(input.objectId === undefined ? {} : { objectId: input.objectId }),
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        ...(input.componentType === undefined ? {} : { componentType: String(input.componentType) }),
        methodName: String(input.methodName || ""),
        expectedReturnTypeFullName: String(input.expectedReturnTypeFullName || ""),
        reason: String(input.reason || "")
      });
    case "volatile_invoke_allowlisted_method":
      return callBridge("volatile_invoke_allowlisted_method", {
        ...(input.target === undefined ? {} : { target: String(input.target) }),
        ...(input.cachedTownWrapper === undefined ? {} : { cachedTownWrapper: Boolean(input.cachedTownWrapper) }),
        ...(input.objectId === undefined ? {} : { objectId: input.objectId }),
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        ...(input.componentType === undefined ? {} : { componentType: String(input.componentType) }),
        methodName: String(input.methodName || ""),
        expectedReturnTypeFullName: String(input.expectedReturnTypeFullName || "System.Void"),
        argCount: input.argCount ?? 0,
        ...(input.arg0TypeFullName === undefined ? {} : { arg0TypeFullName: String(input.arg0TypeFullName) }),
        ...(input.arg0Value === undefined ? {} : { arg0Value: String(input.arg0Value) }),
        ...(input.arg1TypeFullName === undefined ? {} : { arg1TypeFullName: String(input.arg1TypeFullName) }),
        ...(input.arg1Value === undefined ? {} : { arg1Value: String(input.arg1Value) }),
        ...(input.arg2TypeFullName === undefined ? {} : { arg2TypeFullName: String(input.arg2TypeFullName) }),
        ...(input.arg2Value === undefined ? {} : { arg2Value: String(input.arg2Value) }),
        ...(input.arg3TypeFullName === undefined ? {} : { arg3TypeFullName: String(input.arg3TypeFullName) }),
        ...(input.arg3Value === undefined ? {} : { arg3Value: String(input.arg3Value) }),
        reason: String(input.reason || "")
      });
    case "volatile_set_allowlisted_member":
      return callBridge("volatile_set_allowlisted_member", {
        ...(input.target === undefined ? {} : { target: String(input.target) }),
        ...(input.cachedTownWrapper === undefined ? {} : { cachedTownWrapper: Boolean(input.cachedTownWrapper) }),
        ...(input.objectId === undefined ? {} : { objectId: input.objectId }),
        ...(input.name === undefined ? {} : { name: String(input.name) }),
        ...(input.path === undefined ? {} : { path: String(input.path) }),
        ...(input.componentType === undefined ? {} : { componentType: String(input.componentType) }),
        ...(input.memberKind === undefined ? {} : { memberKind: String(input.memberKind) }),
        ...(input.memberName === undefined ? {} : { memberName: String(input.memberName) }),
        ...(input.memberPath === undefined ? {} : { memberPath: String(input.memberPath) }),
        ...(input.maxSegments === undefined ? {} : { maxSegments: input.maxSegments }),
        ...(input.allowProperties === undefined ? {} : { allowProperties: Boolean(input.allowProperties) }),
        ...(input.expectedMemberTypeFullName === undefined ? {} : { expectedMemberTypeFullName: String(input.expectedMemberTypeFullName) }),
        value: String(input.value ?? ""),
        reason: String(input.reason || ""),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "volatile_refresh_town_layers_from_cached_wrapper":
      return callBridge("volatile_refresh_town_layers_from_cached_wrapper", {
        reason: String(input.reason || "")
      });
    case "set_primitive_component_field":
      return callBridge("set_primitive_component_field", {
        objectId: input.objectId ?? 0,
        componentType: String(input.componentType || ""),
        fieldName: String(input.fieldName || ""),
        value: String(input.value ?? ""),
        ...(input.expectedOldValue === undefined ? {} : { expectedOldValue: String(input.expectedOldValue) })
      });
    case "invoke_allowlisted_method":
      return callBridge("invoke_allowlisted_method", {
        objectId: input.objectId ?? 0,
        methodName: String(input.methodName || ""),
        ...(input.value === undefined ? {} : { value: Boolean(input.value) })
      });
    case "create_ui_diagnostic_overlay":
      return callBridge("create_ui_diagnostic_overlay", {
        objectId: input.objectId ?? 0,
        ...(input.color === undefined ? {} : { color: String(input.color) }),
        ...(input.alpha === undefined ? {} : { alpha: Number(input.alpha) })
      });
    case "remove_ui_diagnostic_overlays":
      return callBridge("remove_ui_diagnostic_overlays", {
        ...(input.objectId === undefined ? {} : { objectId: input.objectId })
      });
    case "enable_precompiled_patch":
      return callBridge("enable_precompiled_patch", { patchId: String(input.patchId || ""), enabled: Boolean(input.enabled) });
    case "volatile_compile_and_run_csharp":
      return compileAndRunCSharpProbe(input);
    case "volatile_reflection_invoke":
    case "volatile_generated_getter_sweep":
    case "volatile_write_object_reference":
    case "volatile_autopatch_same_shape_methods":
    case "volatile_global_ui_setter_patch":
      return callBridge(name, input);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function resourceList() {
  const info = bridgeInfo();
  return [
    {
      uri: "olden-live-probe://status",
      name: "Live probe bridge status",
      mimeType: "application/json",
      description: "Current status.json from the game bridge, if available."
    },
    {
      uri: "olden-live-probe://bridge-info",
      name: "MCP adapter bridge configuration",
      mimeType: "application/json",
      description: `Adapter bridge lookup state. Current bridgeDir: ${info.bridgeDir}`
    }
  ];
}

function readResource(uri) {
  if (uri === "olden-live-probe://bridge-info") {
    return JSON.stringify(bridgeInfo(), null, 2);
  }
  if (uri === "olden-live-probe://status") {
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
          content: [{ type: "text", text: String(error?.stack || error) }],
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
