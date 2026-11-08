#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const repoRoot = process.cwd();
const defaultSourceRoot = path.join(repoRoot, "Heroes of Might & Magic Olden Era Playtest", "OfflineUnlockMod");
const defaultOutDir = path.join(repoRoot, "artifacts", "direct_interop_audit_20260603");

const args = process.argv.slice(2);
let sourceRoot = defaultSourceRoot;
let outDir = defaultOutDir;
let failOnFindings = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--source" && i + 1 < args.length) sourceRoot = path.resolve(args[++i]);
  else if (args[i] === "--out" && i + 1 < args.length) outDir = path.resolve(args[++i]);
  else if (args[i] === "--fail-on-findings") failOnFindings = true;
}

const excludedDirs = new Set([
  "bin",
  "obj",
  "tools",
  "publish_plugin",
  "_decompiled_shipped",
  "_decompiled_filtered",
  "_decompiled_release_hex",
]);

const namedFragileMembers = new Set([
  "quickStartButton",
  "skirmishButton",
  "startNewSkirmishButton",
  "loadSkirmishButton",
]);

const findings = [];

const primitiveAndKeywords = new Set([
  "as",
  "bool",
  "byte",
  "case",
  "char",
  "decimal",
  "double",
  "else",
  "enum",
  "false",
  "float",
  "for",
  "get",
  "if",
  "in",
  "int",
  "is",
  "long",
  "new",
  "not",
  "null",
  "object",
  "out",
  "ref",
  "short",
  "set",
  "string",
  "switch",
  "this",
  "true",
  "uint",
  "ulong",
  "ushort",
  "var",
  "when",
  "void",
]);

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!excludedDirs.has(entry.name)) walk(full);
      continue;
    }
    if (!entry.isFile() || !entry.name.endsWith(".cs")) continue;
    if (entry.name === "GameSymbols.cs") continue;
    scanFile(full);
  }
}

function maskLine(line, state) {
  let output = "";
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    const n = line[i + 1];
    if (state.blockComment) {
      if (c === "*" && n === "/") {
        state.blockComment = false;
        output += "  ";
        i++;
      } else {
        output += " ";
      }
      continue;
    }
    if (c === "/" && n === "*") {
      state.blockComment = true;
      output += "  ";
      i++;
      continue;
    }
    if (c === "/" && n === "/") {
      output += " ".repeat(line.length - i);
      break;
    }
    if (c === "\"" || c === "'") {
      const quote = c;
      output += " ";
      i++;
      while (i < line.length) {
        output += " ";
        if (line[i] === "\\" && i + 1 < line.length) {
          output += " ";
          i += 2;
          continue;
        }
        if (line[i] === quote) break;
        i++;
      }
      continue;
    }
    output += c;
  }
  return output;
}

function addFinding(file, lineNumber, kind, symbol, line) {
  findings.push({
    file: path.relative(repoRoot, file).replace(/\\/g, "/"),
    line: lineNumber,
    kind,
    symbol,
    text: line.trim(),
  });
}

function scanFile(file) {
  const lines = fs.readFileSync(file, "utf8").split(/\r?\n/);
  const state = { blockComment: false };
  const obfuscatedVariables = new Map();
  const maskedLines = [];

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = maskLine(raw, state);
    maskedLines.push(line);
    const lineNumber = i + 1;

    matchAll(line, /\btypeof\(\s*(?:global::)?([a-z]{2,4})\s*\)/g, (m) => {
      if (!isLikelyTypeToken(m[1])) return;
      addFinding(file, lineNumber, "type.typeof", m[1], raw);
    });
    matchAll(line, /\bIl2CppClassPointerStore<\s*(?:global::)?([a-z]{2,4})\s*>/g, (m) =>
      addFinding(file, lineNumber, "type.classPointerStore", m[1], raw));
    matchAll(line, /\bnew\s+(?:global::)?([a-z]{2,4})\s*\(/g, (m) =>
      addFinding(file, lineNumber, "type.constructor", m[1], raw));
    matchAll(line, /\b(?:Il2CppReferenceArray|Il2CppSystem\.Collections\.Generic\.List|List)<\s*(?:global::)?([a-z]{2,4})\s*>/g, (m) => {
      if (!isLikelyTypeToken(m[1])) return;
      addFinding(file, lineNumber, "type.genericArgument", m[1], raw);
    });
    matchAll(line, /(?:^|[,(<\s])(?:ref\s+|out\s+|in\s+)?(?:global::)?([a-z]{2,4})\s+([A-Za-z_][A-Za-z0-9_]*)\b/g, (m) => {
      if (!isLikelyTypeToken(m[1])) return;
      if (primitiveAndKeywords.has(m[2])) return;
      obfuscatedVariables.set(m[2], m[1]);
      addFinding(file, lineNumber, "type.obfuscatedDeclaration", `${m[1]} ${m[2]}`, raw);
    });
    matchAll(line, /\bnameof\(\s*(?:global::)?([a-z]{2,4})\.([a-z]{2,5})\s*\)/g, (m) =>
      addFinding(file, lineNumber, "member.nameof", `${m[1]}.${m[2]}`, raw));
    for (const member of namedFragileMembers) {
      if (line.includes(`.${member}`)) {
        addFinding(file, lineNumber, "member.namedInteropAccess", member, raw);
      }
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = maskedLines[i];
    const lineNumber = i + 1;
    for (const [variable, typeName] of obfuscatedVariables) {
      const escaped = variable.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      matchAll(line, new RegExp(`\\b${escaped}\\.([a-z]{2,5})\\b`, "g"), (m) => {
        if (isCommonLowercaseMember(m[1])) return;
        addFinding(file, lineNumber, "member.obfuscatedAccess", `${typeName}.${m[1]}`, raw);
      });
    }
  }
}

function matchAll(text, regex, callback) {
  let match;
  while ((match = regex.exec(text)) !== null) callback(match);
}

function isLikelyTypeToken(token) {
  return /^[a-z]{2,4}$/.test(token)
    && !primitiveAndKeywords.has(token);
}

function isCommonLowercaseMember(name) {
  return new Set([
    "name",
    "text",
    "gameObject",
    "transform",
    "enabled",
    "activeSelf",
    "activeInHierarchy",
    "material",
    "sprite",
    "color",
    "parent",
    "Count",
    "Length",
  ]).has(name);
}

function groupBy(items, keyFn) {
  const map = new Map();
  for (const item of items) {
    const key = keyFn(item);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(item);
  }
  return map;
}

function renderMarkdown() {
  const byKind = [...groupBy(findings, (f) => f.kind).entries()]
    .sort((a, b) => b[1].length - a[1].length);
  const byFile = [...groupBy(findings, (f) => f.file).entries()]
    .sort((a, b) => b[1].length - a[1].length);

  const lines = [];
  lines.push("# Direct Interop Reference Audit");
  lines.push("");
  lines.push(`Source root: \`${path.relative(repoRoot, sourceRoot).replace(/\\/g, "/")}\``);
  lines.push("");
  lines.push(`Total findings: ${findings.length}`);
  lines.push("");
  lines.push("## By Kind");
  lines.push("");
  for (const [kind, rows] of byKind) lines.push(`- ${kind}: ${rows.length}`);
  lines.push("");
  lines.push("## Top Files");
  lines.push("");
  for (const [file, rows] of byFile.slice(0, 30)) lines.push(`- \`${file}\`: ${rows.length}`);
  lines.push("");
  lines.push("## Sample Findings");
  lines.push("");
  for (const row of findings.slice(0, 250)) {
    lines.push(`- \`${row.file}:${row.line}\` ${row.kind} \`${row.symbol}\`: ${row.text}`);
  }
  lines.push("");
  lines.push("## Interpretation");
  lines.push("");
  lines.push("Each finding is a direct source dependency on an interop type/member name outside `GameSymbols.cs`.");
  lines.push("Some rows may be benign false positives, but any row that names an obfuscated game type/member is a candidate for migration behind `GameSymbols` or a narrow semantic helper.");
  return lines.join("\n");
}

if (!fs.existsSync(sourceRoot)) {
  console.error(`Missing source root: ${sourceRoot}`);
  process.exit(1);
}

walk(sourceRoot);
fs.mkdirSync(outDir, { recursive: true });
const jsonPath = path.join(outDir, "direct_interop_refs.json");
const mdPath = path.join(outDir, "direct_interop_refs.md");
fs.writeFileSync(jsonPath, JSON.stringify({ sourceRoot, findings }, null, 2));
fs.writeFileSync(mdPath, renderMarkdown());
console.log(`Findings: ${findings.length}`);
console.log(`JSON: ${jsonPath}`);
console.log(`Markdown: ${mdPath}`);
if (failOnFindings && findings.length > 0) process.exit(1);
