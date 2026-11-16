import assert from "node:assert";
import { CORE_BET_SUBCATEGORIES } from "../src/worker.js";
for (const c of ["epl", "lal", "bun", "sea", "fl1", "ucl", "por", "ere", "tur", "bel1", "scop", "gre1"]) assert.ok(CORE_BET_SUBCATEGORIES.has(c), c);
for (const c of ["el1", "pol", "arg", "mls", "uel", "fac", "bl3", ""]) assert.ok(!CORE_BET_SUBCATEGORIES.has(c), c);
console.log("core leagues: ok");
