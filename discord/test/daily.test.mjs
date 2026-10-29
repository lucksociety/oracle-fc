// Offline test of the scheduled post: DST gating, dedupe and payload shape; Discord is mocked.
import { etHour, dailyPost } from "../src/worker.js";
const assert = (c, m) => { if (!c) { console.error("FAIL", m); process.exit(1); } };
// EDT (Oct) -> 13:00Z is 09 ET; EST (Dec) -> 14:00Z is 09 ET
assert(etHour(new Date("2026-10-29T13:00:00Z")) === 9 && etHour(new Date("2026-10-29T14:00:00Z")) === 10, "EDT");
assert(etHour(new Date("2026-12-10T14:00:00Z")) === 9 && etHour(new Date("2026-12-10T13:00:00Z")) === 8, "EST");
const realFetch = globalThis.fetch, posts = [];
let existing = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url.startsWith("https://discord.com")) {
    if ((init.method || "GET") === "GET") return new Response(JSON.stringify(existing), { status: 200 });
    posts.push(JSON.parse(init.body)); assert(init.headers.authorization === "Bot test-token", "bot auth");
    return new Response("{}", { status: 200 });
  }
  return realFetch(url, init);
};
const env = { DISCORD_BOT_TOKEN: "test-token", SOCCER_CHANNEL_ID: "123", DISCORD_APPLICATION_ID: "1565128574128754708" };
let r = await dailyPost(env, new Date("2026-10-29T14:00:00Z"));
assert(!r.posted && posts.length === 0, "10 ET must not post");
r = await dailyPost(env, new Date("2026-10-29T13:00:00Z"));
assert(r.posted && posts.length === r.messages && posts[0].embeds[0].title === "⚽ Best Bets · 2026-10-29", "9 ET posts");
assert(posts.at(-1).components?.[0]?.components?.[0]?.style === 5, "link button on last message");
assert(posts.every((p) => p.embeds.length <= 10), "≤10 embeds");
const n = posts.length;
existing = [{ author: { id: env.DISCORD_APPLICATION_ID }, embeds: [{ title: "⚽ Best Bets · 2026-10-29" }] }];
r = await dailyPost(env, new Date("2026-10-29T13:00:30Z"));
assert(!r.posted && posts.length === n, "dedupe");
console.log("daily post OK:", n, "messages;", posts[0].embeds[0].description.split("\n").slice(0, 3).join(" | "));
