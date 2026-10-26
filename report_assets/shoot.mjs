// Headless-Chrome screenshots via the DevTools protocol (no extra packages).
// Usage: node shoot.mjs <token> <shots.json> <outdir>
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [token, shotsFile, outDir] = process.argv.slice(2);
const shots = JSON.parse(readFileSync(shotsFile, "utf8"));
const port = 9333;
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless=new", `--remote-debugging-port=${port}`, "--window-size=1360,860", "--hide-scrollbars",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "cs-chrome-"))}`, "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws, id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((resolve) => {
  const n = ++id; pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params }));
});
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

try {
  let targets;
  for (let i = 0; i < 40; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); }
  }
  const page = targets.find((t) => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)({ result: d.result }); pending.delete(d.id); } };
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1360, height: 860, deviceScaleFactor: 2, mobile: false });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
  await sleep(1500);
  if (token !== "-") await evaluate(`localStorage.setItem('career-scout-token', ${JSON.stringify(token)})`);
  for (const s of shots) {
    if (s.navigate) { await send("Page.navigate", { url: s.navigate }); await sleep(2200); }
    if (s.js) await evaluate(`(async () => { ${s.js} })()`);
    await sleep(s.wait ?? 1200);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(outDir, s.file), Buffer.from(shot.result.data, "base64"));
    console.log("saved", s.file);
  }
} finally {
  ws?.close(); chrome.kill();
}
