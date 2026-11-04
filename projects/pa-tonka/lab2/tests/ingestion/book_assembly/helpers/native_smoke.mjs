import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {openUpstreamRuntime} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/upstream_runtime.mjs";

const upstream = process.argv[2];
const runtime = await openUpstreamRuntime(upstream);
const checks = [];
async function check(name, action) {
  try { checks.push({name, status: "PASS", ...await action()}); }
  catch (error) { checks.push({name, status: "FAIL", error: error.message}); }
}
async function source(file, prop, name, book) {
  const json = JSON.parse(await readFile(path.join(upstream, file), "utf8"));
  const index = json[prop].findIndex(value => value.name === name && value.source === book);
  assert.ok(index >= 0);
  return {raw: json[prop][index], origin: {file, json_pointer: `/${prop}/${index}`}};
}
try {
  for (const [tag, prop, name, book, file] of [["spell", "spell", "Acid Splash", "XPHB", "data/spells/spells-xphb.json"], ["creature", "monster", "Ape", "XMM", "data/bestiary/bestiary-xmm.json"]]) await check(`native ${prop}: ${name}`, async () => {
    const {raw, origin} = await source(file, prop, name, book);
    const ref = {type: "statblock", tag, name, source: book};
    const meta = Renderer.utils.getStatblockEntryMeta(ref);
    assert.ok(typeof meta.page === "string" && meta.page.endsWith(".html"));
    const expanded = await Renderer.utils.preload.pGetPreloaded(ref);
    assert.equal(expanded.type, "statblockInline");
    for (const [key, value] of Object.entries(raw)) assert.deepEqual(expanded.statblockData[key], value, key);
    assert.deepEqual(ref, {type: "statblock", tag, name, source: book});
    return {origin, lookup_page: meta.page, source: expanded.statblockData.source, printed_page: expanded.statblockData.page};
  });
  await check("native _copy/_mod: Aarakocra Aeromancer", async () => {
    const {raw, origin} = await source("data/bestiary/fluff-bestiary-xmm.json", "monsterFluff", "Aarakocra Aeromancer", "XMM");
    assert.ok(raw._copy._mod.entries);
    const hash = UrlUtil.getHashBuilder("monsterFluff")(raw);
    const resolved = await DataLoader.pCacheAndGet("monsterFluff", "XMM", hash, {isCopy: true, isRequired: true});
    assert.ok(!resolved._copy);
    assert.match(JSON.stringify(resolved.entries), /control magical winds/);
    assert.match(JSON.stringify(resolved.entries), /Aarakocra are birdlike folk/);
    return {origin, copy_resolved: true};
  });
  await check("native silent miss is not a resolved insertion", async () => {
    const ref = {type: "statblock", tag: "spell", name: "__stage7_missing_spell__", source: "XPHB"};
    assert.equal((await Renderer.utils.preload.pGetPreloaded(ref)).type, "statblock");
    const meta = Renderer.utils.getStatblockEntryMeta(ref);
    await assert.rejects(DataLoader.pCacheAndGet(meta.page, meta.source, meta.hash, {isRequired: true}));
    return {required_lookup_failed: true};
  });
  await check("runtime rejects network JSON before any request", async () => {
    await assert.rejects(DataUtil.loadJSON("https://example.invalid/never-request.json"), /Only local upstream JSON/);
    await assert.rejects(DataUtil.loadRawJSON("https://example.invalid/never-request.json"), /Only local upstream JSON/);
    return {network_blocked: true};
  });
  console.log(JSON.stringify({checks, loaded_files: runtime.loadedFiles}));
} finally { runtime.close(); }
