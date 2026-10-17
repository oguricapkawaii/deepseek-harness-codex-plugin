import { readFile, readdir, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { zstdDecompressSync } from "node:zlib";

const [mode, value, optional, dataHome, installHome] = process.argv.slice(2);
const sessionRoot = join(dataHome, "sessions");
const sessionModule = join(
  installHome, ...(installHome.endsWith(".app")
    ? ["Contents", "Resources", "app.asar", "dsh"] : ["resources", "runtime"]), "node_modules", "@deepseek-ai", "dsh-session", "lib", "index.js",
);
const sessionApi = await import(pathToFileURL(sessionModule).href);
const decodeStorageRecord = sessionApi.decodeStorageRecord ?? ((row) => {
  if (typeof row?.type === "string" && row.type !== "session") return [row];
  throw new Error("Unsupported Harness history record format");
});
const ZSTD_MAGIC = 0xfd2fb528;

function scanFrames(buffer) {
  const frames = [];
  let offset = 0;
  while (offset < buffer.length) {
    const start = offset;
    if (buffer.length - offset < 5 || buffer.readUInt32LE(offset) !== ZSTD_MAGIC) {
      throw new Error(`invalid Zstandard session frame at byte ${offset}`);
    }
    offset += 4;
    const descriptor = buffer.readUInt8(offset++);
    if ((descriptor & 24) !== 0) throw new Error("reserved Zstandard frame-header bit");
    const contentSizeFlag = descriptor >>> 6;
    const singleSegment = (descriptor & 32) !== 0;
    const checksum = (descriptor & 4) !== 0;
    const dictionaryFlag = descriptor & 3;
    const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
    const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
    const remainingHeaderBytes = (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
    if (buffer.length - offset < remainingHeaderBytes) break;
    offset += remainingHeaderBytes;
    let complete = false;
    while (buffer.length - offset >= 3) {
      const blockHeader = buffer.readUIntLE(offset, 3);
      offset += 3;
      const lastBlock = (blockHeader & 1) !== 0;
      const blockType = (blockHeader >>> 1) & 3;
      const blockSize = blockHeader >>> 3;
      if (blockType === 3) throw new Error("reserved Zstandard block type");
      const payloadBytes = blockType === 1 ? 1 : blockSize;
      if (buffer.length - offset < payloadBytes) break;
      offset += payloadBytes;
      if (lastBlock) {
        if (checksum) {
          if (buffer.length - offset < 4) break;
          offset += 4;
        }
        complete = true;
        break;
      }
    }
    if (!complete) break;
    frames.push({ start, end: offset });
  }
  return frames;
}

async function findLogs() {
  const logs = [];
  let projects = [];
  try {
    projects = await readdir(sessionRoot, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") return logs;
    throw error;
  }
  for (const project of projects) {
    if (!project.isDirectory()) continue;
    const projectPath = join(sessionRoot, project.name);
    for (const session of await readdir(projectPath, { withFileTypes: true })) {
      if (!session.isDirectory()) continue;
      // Prefer the current generation, without showing migrated backups twice.
      for (const filename of ["session.v4.jsonl.zstd", "session.v4.jsonl", "session.v3.jsonl.zstd", "session.v3.jsonl", "session.jsonl.zstd", "session.jsonl"]) {
        const path = join(projectPath, session.name, filename);
        try {
          const info = await stat(path);
          if (info.isFile()) { logs.push({ path, info }); break; }
        } catch (error) {
          if (error?.code !== "ENOENT") throw error;
        }
      }
    }
  }
  return logs;
}

async function readSession(path) {
  const buffer = await readFile(path);
  const text = path.endsWith(".zstd")
    ? Buffer.concat(scanFrames(buffer).map(({ start, end }) => zstdDecompressSync(buffer.subarray(start, end)))).toString("utf8")
    : buffer.toString("utf8");
  const rows = text.split("\n").filter(Boolean).map((line) => JSON.parse(line));
  const header = rows.shift();
  if (!header || header.type !== "session") throw new Error(`invalid session header: ${path}`);
  return { header, events: rows.flatMap((row) => decodeStorageRecord(row)) };
}

function metadata(session, info) {
  const title = session.events.findLast((event) => event?.type === "session/title")?.data?.title ?? "Untitled Harness task";
  const lastBoundary = session.events.findLast((event) => event?.type === "turn/start" || event?.type === "turn/end");
  const end = session.events.findLast((event) => event?.type === "turn/end");
  const selection = session.events.findLast((event) => event?.type === "request/header")?.data?.header?.config;
  return {
    id: session.header.id,
    title,
    workspace: session.header.cwd ?? null,
    created_at: new Date(session.header.createdAt).toISOString(),
    modified_at: info.mtime.toISOString(),
    status: lastBoundary?.type === "turn/start" ? "interrupted" : "complete",
    end_reason: end?.data?.reason ?? null,
    messages: session.events.filter((event) => event?.type === "user/message" || event?.type === "assistant/message").length,
    runtime_selection: selection ? {
      provider: selection.provider ?? null, model: selection.model ?? null,
      reasoning_effort: selection.reasoningEffort ?? null,
      max_tokens: selection.maxTokens ?? null,
    } : null,
  };
}

function blockText(block) {
  if (!block || typeof block !== "object") return "";
  if (block.type === "text" && typeof block.text === "string") return block.text;
  if (block.type === "tool-result" && Array.isArray(block.content)) return block.content.map(blockText).filter(Boolean).join("\n");
  return "";
}

function contentText(content) {
  return Array.isArray(content) ? content.map(blockText).filter(Boolean).join("\n") : "";
}

function exportMarkdown(session, maxChars) {
  const title = session.events.findLast((event) => event?.type === "session/title")?.data?.title ?? "Harness session";
  const lines = [
    `# ${title}`, "", `- Session: \`${session.header.id}\``,
    `- Workspace: \`${session.header.cwd ?? "unknown"}\``,
    `- Created: ${new Date(session.header.createdAt).toISOString()}`, "",
  ];
  for (const event of session.events) {
    if (event?.type === "user/message") {
      if (event.data?.source?.kind && event.data.source.kind !== "user") continue;
      const text = contentText(event.data?.content);
      if (text) lines.push("## User", "", text, "");
    } else if (event?.type === "assistant/message") {
      const text = contentText(event.data?.message?.content);
      if (text) lines.push("## Assistant", "", text, "");
    } else if (event?.type === "tool/call") {
      const args = typeof event.data?.arguments === "string" ? event.data.arguments : JSON.stringify(event.data?.arguments ?? {});
      lines.push(`### Tool call: ${event.data?.name ?? "unknown"}`, "", "```json", args.slice(0, 10000), "```", "");
    } else if (event?.type === "tool/result") {
      const text = contentText(event.data?.message?.content);
      if (text) lines.push("### Tool result", "", "```text", text.slice(0, 10000), "```", "");
    }
  }
  const markdown = lines.join("\n");
  return markdown.length <= maxChars ? markdown : `${markdown.slice(0, maxChars)}\n\n...[history export clipped]...`;
}

const normalizeWorkspace = (value) => process.platform === "win32" ? resolve(value).toLowerCase() : resolve(value);
const logs = await findLogs();
if (mode === "list") {
  const limit = Number.parseInt(value, 10);
  const workspace = optional ? normalizeWorkspace(optional) : "";
  const items = [];
  for (const log of logs.sort((a, b) => b.info.mtimeMs - a.info.mtimeMs)) {
    const session = await readSession(log.path);
    if (workspace && normalizeWorkspace(session.header.cwd ?? "") !== workspace) continue;
    items.push(metadata(session, log.info));
    if (items.length >= limit) break;
  }
  process.stdout.write(JSON.stringify({ data_home: dataHome, sessions: items }));
} else if (mode === "export" || mode === "inspect") {
  let found;
  let foundInfo;
  for (const log of logs) {
    const session = await readSession(log.path);
    if (session.header.id === value) { found = session; foundInfo = log.info; break; }
  }
  if (!found) throw new Error(`session not found: ${value}`);
  if (mode === "inspect") {
    process.stdout.write(JSON.stringify(metadata(found, foundInfo)));
  } else {
    const maxChars = Number.parseInt(optional, 10);
    process.stdout.write(JSON.stringify({ session_id: value, markdown: exportMarkdown(found, maxChars) }));
  }
} else {
  throw new Error(`unknown history mode: ${mode}`);
}
