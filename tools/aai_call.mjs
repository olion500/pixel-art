// Drive the aseprite-ai-artist MCP server (https://github.com/with-pebbly/aseprite-ai-artist) headlessly.
//
//   node tools/aai_call.mjs <calls.json> [--out DIR]
//   node tools/aai_call.mjs --list
//
// calls.json: [{ "tool": "preflight", "args": {} }, ...] run in order on ONE server session (documents
// stay open between calls). Text results are printed; image results (look) are saved as PNGs in --out.
// Env: AAI_HOME (built repo with dist/cli.js), ASEPRITE_PATH (aseprite binary).
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const home = process.env.AAI_HOME;
const aseprite = process.env.ASEPRITE_PATH;
const args = process.argv.slice(2);
const outDir = args.includes("--out") ? args[args.indexOf("--out") + 1] : "out/aai";

const transport = new StdioClientTransport({
  command: "node",
  args: [path.join(home, "dist/cli.js"), "serve", "--headless", "--aseprite", aseprite],
  env: { ...process.env },
  stderr: "pipe",
});
const client = new Client({ name: "pixel-art-driver", version: "0.1.0" });
await client.connect(transport);

if (args[0] === "--list") {
  const { tools } = await client.listTools();
  for (const t of tools) console.log(`${t.name}: ${(t.description ?? "").split("\n")[0].slice(0, 160)}`);
} else {
  const calls = JSON.parse(readFileSync(args[0], "utf8"));
  mkdirSync(outDir, { recursive: true });
  let n = 0;
  for (const c of calls) {
    const res = await client.callTool({ name: c.tool, arguments: c.args ?? {} }, undefined, { timeout: 120000 });
    console.log(`\n### ${c.tool} ${c.label ?? ""}${res.isError ? "  [ERROR]" : ""}`);
    for (const part of res.content ?? []) {
      if (part.type === "text") console.log(part.text.length > 4000 ? part.text.slice(0, 4000) + " …" : part.text);
      else if (part.type === "image") {
        const file = path.join(outDir, `${String(++n).padStart(2, "0")}_${c.label ?? c.tool}.png`);
        writeFileSync(file, Buffer.from(part.data, "base64"));
        console.log(`[image] ${file}`);
      }
    }
    if (res.isError && c.stopOnError !== false) break;
  }
}
await client.close();
