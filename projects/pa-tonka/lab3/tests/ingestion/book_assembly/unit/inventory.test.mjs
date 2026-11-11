import assert from "node:assert/strict";
import {mkdtemp, mkdir, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {atPointer, canonicalJson, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {openUpstreamRuntime} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/upstream_runtime.mjs";
import {createInventoryApi} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/inventory_runtime.mjs";
import {inventoryBooks} from "../../../../src/dnd_rag/ingestion/book_assembly/inventory/inventory_books.mjs";
import {classifySourceRecords, inventoryDependencies, inventorySources} from "../../../../src/dnd_rag/ingestion/book_assembly/inventory/inventory_sources.mjs";
import {outsideUpstream, publishArtifacts} from "../../../../src/dnd_rag/ingestion/book_assembly/common/artifact_store.mjs";

const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-inventory-unit-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  return root;
}
async function json(root, file, value) {
  await mkdir(path.dirname(path.join(root, file)), {recursive: true});
  await writeFile(path.join(root, file), JSON.stringify(value));
}

test("inventory native metadata and raw source fixtures", async t => {
  const runtime = await openUpstreamRuntime(path.join(projectRoot, "external/5etools-src"));
  t.after(() => runtime.close());
  const api = createInventoryApi();

  await t.test("entity entry grammar is audited separately from mechanics, including inline payloads and native wrappers", () => {
    const payload = {type: "M|XPHB", range: {type: "point"}, duration: [{type: "instant"}], entries: [
      {type: "wrapper", wrapped: {type: "entries", entries: ["Rule"]}},
      {type: "table", rows: [[{type: "bonusSpeed", value: 10}]]},
      {type: "image", href: {type: "internal", path: "missing.webp"}},
      {type: "statblockInline", statblockType: "monster", statblockData: {type: {type: "construct"}, action: [{name: "Action", entries: ["Rule"]}]}},
    ]};
    assert.deepEqual(api.auditEntryTypes(payload), []);
    payload.entries[3].statblockData.action[0].entries.push({type: "unrecognizedInlineEntry"});
    payload.entries.push({type: "unrecognizedEntityEntry", entries: ["Do not silently accept"]});
    assert.deepEqual(api.auditEntryTypes(payload), [
      {path: "/entries/3/statblockData/action/0/entries/1", type: "unrecognizedInlineEntry"},
      {path: "/entries/4", type: "unrecognizedEntityEntry"},
    ]);
  });

  await t.test("unknown types inside source entity descriptions are blocking with exact physical pointers", async t => {
    const root = await fixture(t);
    const raw = {spell: [{name: "Fixture", source: "XPHB", entries: [{type: "unrecognizedSpellEntry", entries: ["Rule"]}]}]};
    const file = "data/spells/spells-xphb.json";
    await json(root, file, raw);
    const issues = [];
    const catalog = await inventorySources(root, "fixture", [file], api, issues);
    inventoryDependencies(catalog, api, issues);
    assert.deepEqual(issues.filter(issue => issue.code === "UNKNOWN_SOURCE_ENTRY_TYPE"), [{
      severity: "ERROR", code: "UNKNOWN_SOURCE_ENTRY_TYPE", record_id: catalog.records[0].record_id, prop: "spell", file,
      json_pointer: "/spell/0/entries/0", type: "unrecognizedSpellEntry", message: "Unclassified entity entry type unrecognizedSpellEntry",
    }]);
  });

  await t.test("nested tags use native UID grammar, defaults, pantheon/class context and exact UTF-16 spans", () => {
    const text = "🙂 {@b Pick {@spell Fireball|XPHB}} {@spell Fireball} {@subclass Berserker|Barbarian|XPHB|XPHB} {@classFeature Rage|Barbarian|XPHB|1} {@deity Lolth|Drow|XDMG} {@filter Options|optionalfeatures|feature type=EI|source=XPHB}";
    const tags = api.tags(text);
    for (const tag of tags) assert.equal(text.slice(tag.span.start, tag.span.end), tag.raw);
    const spells = tags.filter(tag => tag.tag === "spell");
    assert.equal(spells[0].target.source, "XPHB");
    assert.equal(spells[1].target.source, "PHB", "Missing source uses the upstream default, never the containing book");
    assert.equal(spells[0].parent_start, tags.find(tag => tag.tag === "b").span.start);
    const subclass = tags.find(tag => tag.tag === "subclass");
    assert.equal(subclass.target.entity_id, api.lookup("subclass", {name: "Path of the Berserker", shortName: "Berserker", source: "XPHB", className: "Barbarian", classSource: "XPHB"}).entity_id);
    assert.match(tags.find(tag => tag.tag === "classFeature").target.hash, /barbarian_xphb_1_xphb/);
    assert.equal(tags.find(tag => tag.tag === "deity").target.source, "XDMG");
    assert.match(tags.find(tag => tag.tag === "deity").target.hash, /drow/);
    assert.equal(tags.find(tag => tag.tag === "filter").kind, "query_reference");
    assert.equal(tags.find(tag => tag.tag === "b").kind, "formatting_tag");
    assert.equal(api.tags("{@neverKnownTag text}")[0].kind, "unknown_tag");
    assert.equal(api.tags("{@spell broken")[0].kind, "malformed_tag");
    assert.equal(api.stringRefs("{#itemEntry Dragon Scale Mail|XDMG}")[0].target.prop, "itemEntry");
    assert.ok(api.stringRefs("{#itemEntry Dragon Scale Mail|XDMG} {#broken").some(ref => ref.error));
    assert.throws(() => api.structural({type: "refNeverKnown"}), /Unknown required/);
  });

  await t.test("every original value gets a stable position, table/image payloads survive and unknown types are errors", async t => {
    const root = await fixture(t);
    const ids = ["XPHB", "XDMG", "XMM"];
    const chapters = new Map(ids.map(id => [id, {name: id === "XMM" ? "How to Use a Monster" : "Chapter 1: Fixture", page: 10, entries: [
      {type: "statblock", tag: "spell", name: "Fireball", source: "XPHB"},
      {type: "table", rows: [[1, {type: "cell", roll: {exact: 2}}]]},
      {type: "image", href: {type: "internal", path: "missing.webp"}, credit: "Fixture"},
      {"a/b~c": "{@b Choose {@spell Fireball|XPHB}}"},
    ]}]));
    await json(root, "data/books.json", {book: [{id: "OTHER"}, ...ids.map(id => ({id, name: id, contents: [{name: id === "XMM" ? "Introduction" : "Fixture"}]}))]});
    const originals = new Map();
    for (const id of ids) {
      const value = {bookData: [{id: "OTHER"}, {id, source: id, data: [chapters.get(id)]}]};
      const file = `data/book/book-${id.toLowerCase()}.json`;
      originals.set(file, value);
      await json(root, file, value);
    }
    const issues = [];
    const result = await inventoryBooks(root, "fixture", api, issues);
    assert.ok(!issues.some(issue => issue.severity === "ERROR"));
    assert.ok(issues.some(issue => issue.code === "KNOWN_CATALOG_TITLE_ALIAS"));
    for (const row of result.nodes) {
      const raw = atPointer(originals.get(row.origin.file), row.origin.json_pointer);
      assert.equal(sha256(canonicalJson(raw)), row.raw_sha256);
      assert.match(row.origin.json_pointer, /^\/bookData\/1\/data\/0/);
      if (row.payload) assert.deepEqual(row.payload, raw);
    }
    assert.ok(result.nodes.some(row => row.origin.json_pointer.endsWith("a~1b~0c")));
    assert.equal(new Set(result.nodes.map(row => row.occurrence_id)).size, result.nodes.length);
    assert.equal(result.references.filter(ref => ref.kind === "entity_reference").length, 3);
    for (const ref of result.references.filter(ref => ref.kind === "embedded_reference")) assert.equal(ref.origin.page_attribution, "inherited_section_start");

    chapters.get("XPHB").entries.push({type: "newUnsupportedType"}, {type: "refNeverKnown"});
    await json(root, "data/book/book-xphb.json", {bookData: [{id: "XPHB", source: "XPHB", data: [chapters.get("XPHB")]}]});
    const bad = [];
    await inventoryBooks(root, "fixture", api, bad);
    assert.ok(bad.some(issue => issue.code === "UNKNOWN_BOOK_TYPE" && issue.severity === "ERROR"));
    assert.ok(bad.some(issue => issue.code === "INVALID_REQUIRED_REFERENCE"));
  });

  await t.test("source records distinguish overlays/editions/templates and expose subclass/optional/summon dependencies", async t => {
    const root = await fixture(t);
    const data = {
      "data/items.json": {item: [{name: "Fixture", source: "XPHB", _versions: [{name: "Version", source: "XPHB"}]}, {name: "Fixture", source: "PHB"}]},
      "data/foundry-items.json": {item: [{name: "Fixture", source: "XPHB"}]},
      "data/magicvariants.json": {magicvariant: [{name: "Fixture Variant", inherits: {source: "XDMG", page: 50}}]},
      "data/generated/gendata-tables.json": {table: [{name: "Fixture Table", source: "XPHB", rows: [[1]]}]},
      "data/class/class-fixture.json": {
        class: [{name: "Barbarian", source: "XPHB", classFeatures: ["Rage|Barbarian|XPHB|1"]}],
        subclass: [{name: "Path of the Berserker", shortName: "Berserker", className: "Barbarian", classSource: "XPHB", source: "XPHB"}],
        classFeature: [{name: "Rage", source: "XPHB", className: "Barbarian", classSource: "XPHB", level: 1, entries: [{type: "refOptionalfeature", optionalfeature: "Agonizing Blast|XPHB"}]}],
      },
      "data/optionalfeatures.json": {optionalfeature: [{name: "Agonizing Blast", source: "XPHB", prerequisite: [{level: 2}]}]},
      "data/bestiary/bestiary-xphb.json": {monster: [{name: "Spirit", source: "XPHB", summonedByClass: "Barbarian|XPHB"}]},
    };
    for (const [file, value] of Object.entries(data)) await json(root, file, value);
    const issues = [];
    const catalog = await inventorySources(root, "fixture", Object.keys(data).sort(), api, issues);
    assert.deepEqual(issues, []);
    const lookup = api.lookup("item", {name: "Fixture", source: "XPHB"});
    assert.equal(catalog.byEntity.get(lookup.entity_id).length, 1, "Foundry overlays must not masquerade as primary content");
    assert.notEqual(lookup.entity_id, api.lookup("item", {name: "Fixture", source: "PHB"}).entity_id);
    const variant = catalog.records.find(row => row.prop === "magicvariant");
    assert.equal(variant.source, "XDMG");
    assert.match(variant.source_location, /\/inherits\/source$/);
    assert.equal(variant.origin.printed_page, null, "Template page must not be mislabelled as a printed record page");
    assert.equal(catalog.variants.length, 1);
    const edges = inventoryDependencies(catalog, api, issues);
    const classTarget = api.lookup("class", {name: "Barbarian", source: "XPHB"});
    classifySourceRecords(catalog, [{reference_id: "fixture-class", required: true, target: classTarget}], edges);
    assert.equal(catalog.records.find(row => row.prop === "subclass").classification, "required_domain_component");
    assert.equal(catalog.records.find(row => row.prop === "monster").classification, "required_domain_component");
    assert.equal(catalog.records.find(row => row.prop === "optionalfeature").classification, "domain_dependency_candidate");
    assert.equal(catalog.records.find(row => row.role === "foundry_overlay").classification, "foundry_overlay");
    assert.equal(catalog.records.find(row => row.role === "generated_projection").classification, "generated_projection");
    assert.equal(variant.classification, "variant_template");
    assert.ok(edges.some(edge => edge.relation === "classFeatures" && edge.target_record_ids.length === 1));
    assert.ok(edges.some(edge => edge.relation === "structural_reference" && edge.target_record_ids.length === 1));
    assert.deepEqual(issues, []);
    await json(root, "data/mystery.json", {neverKnownProp: [{name: "Unknown", source: "XPHB"}]});
    const bad = [];
    await inventorySources(root, "fixture", ["data/mystery.json"], api, bad);
    assert.ok(bad.some(issue => issue.code === "UNKNOWN_SOURCE_IDENTITY" && issue.severity === "ERROR"));
  });
});

test("inventory storage preserves differing existing artifacts and rejects upstream outputs", async t => {
  const root = await fixture(t);
  const upstream = path.join(root, "upstream");
  await mkdir(upstream);
  await assert.rejects(outsideUpstream(path.join(upstream, "new/subdir"), upstream), /outside upstream/);
  const directory = path.join(root, "output/build");
  assert.equal(await publishArtifacts(directory, {"a.json": "{}\n", "b.jsonl": ""}), "created");
  assert.equal(await publishArtifacts(directory, {"a.json": "{}\n", "b.jsonl": ""}), "unchanged");
  await assert.rejects(publishArtifacts(directory, {"a.json": "changed\n", "b.jsonl": ""}), /refusing to overwrite/);
});
