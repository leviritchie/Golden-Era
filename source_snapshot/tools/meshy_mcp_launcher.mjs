import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const envPath = resolve(projectRoot, ".env");

function loadDotEnv(path) {
  const values = {};
  for (const rawLine of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith("\"") && value.endsWith("\"")) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

const dotenv = loadDotEnv(envPath);
const apiKey = dotenv.MESHY_API_KEY || process.env.MESHY_API_KEY;
if (!apiKey) {
  console.error(`MESHY_API_KEY is missing from ${envPath}`);
  process.exit(1);
}

const command = process.platform === "win32" ? "npx.cmd" : "npx";
const child = spawn(command, ["--yes", "@meshy-ai/meshy-mcp-server@0.4.0"], {
  cwd: projectRoot,
  env: { ...process.env, MESHY_API_KEY: apiKey },
  shell: process.platform === "win32",
  stdio: "inherit",
});

child.on("error", (error) => {
  console.error(`Failed to start Meshy MCP server: ${error.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});
