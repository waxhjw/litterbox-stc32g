import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const [sourceDir, hexPath] = process.argv.slice(2);
if (!sourceDir || !hexPath) throw new Error("Usage: node tools/stcide_compile.mjs SOURCE_DIR OUTPUT.hex");

const cache = fileURLToPath(new URL("../.tools/stc-ide/", import.meta.url));
const manifest = JSON.parse(await readFile(resolve(cache, "manifest.json"), "utf8"));
for (const [name, expected] of Object.entries(manifest.files)) {
    const bytes = await readFile(resolve(cache, name));
    if (createHash("sha256").update(bytes).digest("hex") !== expected) {
        throw new Error(`STC IDE cache hash mismatch: ${name}`);
    }
}

const files = await Promise.all((await readdir(sourceDir)).sort()
    .filter((name) => /\.[ch]$/.test(name))
    .map(async (name) => ({ name, code: await readFile(resolve(sourceDir, name), "utf8") })));

// The official browser worker uses the same compiler without its optional macro worker pool.
globalThis.self = globalThis;
await import(pathToFileURL(resolve(cache, "ide.worker.js")));
const message = await new Promise((accept) => {
    self.postMessage = accept;
    self.onmessage({ data: { id: 1, mode: "full", target: "STC32G8K64", files } });
});
const result = message.result;
if (!message.ok || !result?.success || typeof result.hex !== "string") {
    throw new Error(message.error || result?.error || `Missing HEX (${Object.keys(result ?? {}).join(", ")})`);
}
await writeFile(hexPath, result.hex, "ascii");
const m = result.memReport;
console.log(JSON.stringify({ compiler: message.buildVer, target: m?.targetName,
    code: m?.code, rom: m?.rom, edata: m?.edata, xdata: m?.xdata,
    stack: m?.stack?.need, stackAvailable: m?.stack?.avail, notes: result.notes ?? [] }));
if (typeof result.asm === "string") await writeFile(`${hexPath}.asm`, result.asm, "utf8");
