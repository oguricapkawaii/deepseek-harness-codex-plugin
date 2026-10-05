import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";

const [source, destination, model, reasoningEffort, installHome] = process.argv.slice(2);
const require = createRequire(join(installHome, "resources", "runtime", "package.json"));
const { parse } = require("yaml");

let settings = {};
try {
  settings = parse(await readFile(source, "utf8")) ?? {};
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}
if (!settings || typeof settings !== "object" || Array.isArray(settings)) {
  throw new Error(`Harness settings must contain a YAML mapping: ${source}`);
}
const existing = settings["agent-default-model"];
settings["agent-default-model"] = {
  ...(existing && typeof existing === "object" && !Array.isArray(existing) ? existing : {}),
  provider: "deepseek-official",
  model,
  reasoningEffort,
};
await writeFile(destination, JSON.stringify(settings, null, 2), { encoding: "utf8", mode: 0o600 });
