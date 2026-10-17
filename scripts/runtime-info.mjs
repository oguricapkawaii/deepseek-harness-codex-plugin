// Read only public runtime metadata and model capabilities, never credentials.
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [installHome, dataHome] = process.argv.slice(2);
const root = installHome.endsWith(".app")
  ? join(installHome, "Contents", "Resources", "app.asar", "dsh")
  : join(installHome, "resources", "runtime");
const require = createRequire(join(root, "package.json"));
const { parseDocument } = require("yaml");
async function yaml(path) {
  try {
    // Do not execute !!js while inspecting a user profile.
    const doc = parseDocument(await readFile(path, "utf8"), { logLevel: "silent" });
    if (doc.errors.length) throw new Error(`Cannot parse Harness configuration: ${path}`);
    return doc.toJS() ?? {};
  } catch (error) {
    if (error.code === "ENOENT") return {};
    throw error;
  }
}
const pkg = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
const adapter = await import(pathToFileURL(join(root, "node_modules", "@deepseek-ai", "dsh-llm-deepseek", "lib", "index.js")).href);
const defaults = adapter.resolveAdapterOptions({});
const effortSchema = JSON.parse(JSON.stringify(adapter.deepSeekConfigFields.reasoningEffort));
const effortRoot = effortSchema.refs[effortSchema.uid];
const efforts = effortRoot.list.map((id) => effortSchema.refs[id].value);
// The full runtime remains authoritative for effective profile configuration.
// This catalog is advisory; explicit model ids are validated by the runtime.
const legacy = await yaml(join(dataHome, "settings.yaml"));
const rows = await yaml(join(dataHome, "profiles", "headless", "cordis.patch.yml"));
let configured = legacy["llm-deepseek"]?.models;
for (const row of Array.isArray(rows) ? rows : []) {
  if (row.id === "llm-deepseek" && Array.isArray(row.config?.models)) configured = row.config.models;
}
const entries = configured ?? defaults.models;
if (!Array.isArray(entries)) throw new Error("Harness model catalog is not an array");
const models = entries.map((entry) => {
  return {
    id: entry.id, name: entry.name ?? entry.id,
    input_modalities: entry.inputModalities ?? ["text"],
    context_window: entry.contextWindow ?? defaults.defaultContextWindow,
    reasoning_efforts: efforts,
  };
});
process.stdout.write(JSON.stringify({
  runtime_version: pkg.version, provider: "deepseek-official", models,
  catalog_source: configured ? "profile" : "installed-runtime",
  catalog_is_advisory: true,
}));
