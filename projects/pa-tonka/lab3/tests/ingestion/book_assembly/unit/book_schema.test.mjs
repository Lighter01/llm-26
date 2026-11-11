import assert from "node:assert/strict";
import test from "node:test";
import {atPointer, canonicalJson, copyJson, entityId, occurrenceId, origin, pageContext, restoreReferences} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";

test("IDs distinguish placement from entity, source editions, and parameterized hashes", () => {
  const uid = {prop: "spell", source: "XPHB", hash: "same_xphb"};
  assert.equal(entityId(uid), entityId({...uid, source: "xphb"}));
  assert.notEqual(entityId(uid), entityId({...uid, source: "PHB"}));
  assert.notEqual(entityId(uid), entityId({...uid, prop: "monster"}));
  assert.notEqual(entityId(uid), entityId({...uid, hash: "same_xphb,level2"}));
  assert.notEqual(occurrenceId("XPHB", 7, "/bookData/0/data/7/entries/0"), occurrenceId("XPHB", 7, "/bookData/0/data/7/entries/1"));
  assert.notEqual(occurrenceId("XPHB", 7, "/a"), occurrenceId("XMM", 7, "/a"));
  assert.throws(() => entityId({...uid, hash: ""}), /requires prop/);
});

test("canonical JSON sorts object keys but retains meaningful array order", () => {
  assert.equal(canonicalJson({z: [{b: 2, a: 1}], a: 0}), canonicalJson({a: 0, z: [{a: 1, b: 2}]}));
  assert.notEqual(canonicalJson({rows: [1, 2]}), canonicalJson({rows: [2, 1]}));
});

test("strict serialization rejects silent JSON losses and cycles, permits shared plain values", () => {
  for (const value of [undefined, NaN, Infinity, 1n, () => {}, new Map(), new Set(), new Date(), [1, , 3], {a: undefined}]) assert.throws(() => copyJson(value), /Non-JSON/);
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => copyJson(cyclic), /Cyclic/);
  const shared = {entries: ["text"]};
  assert.deepEqual(copyJson([shared, shared]), [shared, shared]);
});

test("pages distinguish explicit, inherited and unknown without inventing exact pages", () => {
  const explicit = pageContext({page: 346}, "/chapter");
  const inherited = pageContext({name: "child"}, "/chapter/child", explicit);
  const base = {file: "data/book/book-xphb.json", source: "XPHB", commit: "fixture"};
  assert.equal(origin({...base, pointer: "/chapter", page: explicit}).page_attribution, "explicit");
  assert.equal(origin({...base, pointer: "/chapter/child", page: inherited}).page_attribution, "inherited_section_start");
  assert.equal(origin({...base, pointer: "/missing"}).printed_page, null);
  assert.equal(origin({...base, pointer: "/missing"}).page_attribution, "unknown");
  assert.equal(pageContext({page: 0}, "/front-matter").printed_page, 0);
  assert.throws(() => pageContext({page: "spells.html"}, "/lookup"), /Invalid printed page/);
});

test("source projection preserves references, nested tables, images and escaped pointer keys", () => {
  const reference = {type: "statblock", tag: "spell", name: "Fixture", source: "XPHB", data: {renderCompact: {flag: true}}};
  const tree = {entries: [{type: "table", rows: [[{kind: "embedded_entity", original_reference: reference, data: {entries: ["resolved"]}}]]}], "a/b~c": {type: "image", href: {path: "missing.webp"}}};
  const restored = restoreReferences(tree);
  assert.deepEqual(restored.entries[0].rows[0][0], reference);
  assert.equal(atPointer(restored, "/a~1b~0c/href/path"), "missing.webp");
  assert.equal(tree.entries[0].rows[0][0].kind, "embedded_entity");
  assert.throws(() => atPointer(tree, "/missing"), /Missing JSON Pointer/);
});
