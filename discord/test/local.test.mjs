// Local smoke test: signature check, PING, and date parsing.
import worker, { parseDate } from "../src/worker.js";

const kp = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
const pubHex = Buffer.from(await crypto.subtle.exportKey("raw", kp.publicKey)).toString("hex");
const env = { DISCORD_PUBLIC_KEY: pubHex, DISCORD_APPLICATION_ID: "1565128574128754708" };
const ctx = { waitUntil: p => p.catch(() => {}) };
globalThis.fetch = async () => new Response('{}', { status: 200 });

async function signed(obj, tamper = false) {
  const body = JSON.stringify(obj), ts = String(Math.floor(Date.now() / 1000));
  const sig = Buffer.from(await crypto.subtle.sign({ name: "Ed25519" }, kp.privateKey, new TextEncoder().encode(ts + body))).toString("hex");
  return new Request("https://x/", { method: "POST", body: tamper ? body + " " : body, headers: { "X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts } });
}
let r = await worker.fetch(await signed({ type: 1 }), env, ctx);
console.log("PING ->", r.status, await r.text());
r = await worker.fetch(await signed({ type: 1 }, true), env, ctx);
console.log("tampered ->", r.status);
r = await worker.fetch(new Request("https://x/", { method: "POST", body: "{}" }), env, ctx);
console.log("unsigned ->", r.status);
r = await worker.fetch(await signed({ type: 2, data: { name: "soccer" }, token: "t" }), env, ctx);
console.log("command ->", r.status, await r.text());

const now = new Date("2026-10-28T22:30:00Z");
for (const s of ["", "today", "tomorrow", "10/31", "2026-10-31", "10-31-26", "2026-02-30", "garbage"]) console.log(JSON.stringify(s), "->", parseDate(s, now));
