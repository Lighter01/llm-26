import assert from "node:assert/strict";
import test from "node:test";
import {canonicalJson, copyJson, entityId, occurrenceId, origin, pageContext, restoreReferences, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {assembleChapter, AssemblyError, resolveRemaining} from "../../../../src/dnd_rag/ingestion/book_assembly/assembly/assembly_content.mjs";
import {auditRequiredReferences, serializeLoaderData} from "../../../../src/dnd_rag/ingestion/book_assembly/assembly/assembly_schema.mjs";

test("serialization omits only verified native item caches/undefined flags and preserves rule fields", () => {
  const item = {name: "Fixture", source: "XDMG", __prop: "magicvariant", _category: "Generic Variant", entries: ["Rule"], _fullEntries: [{type: "table", rows: [[1, 2]]}], variants: [{base: {name: "Base"}, specificVariant: {name: "Derived"}}]};
  const omissions = [];
  const result = serializeLoaderData(item, {sourceRecords: [{fields: ["name", "inherits"]}], onOmission: omission => omissions.push(omission)});
  assert.equal(Object.hasOwn(result, "variants"), false);
  assert.deepEqual(result.entries, item.entries);
  assert.deepEqual(result._fullEntries, item._fullEntries);
  assert.equal(item.variants.length, 1);
  assert.equal(omissions[0].kind, "native_generated_variant_cache");
  assert.equal(omissions[0].combinations, 1);
  assert.throws(() => serializeLoaderData(item, {sourceRecords: [{fields: ["variants"]}]}), /source-defined variants/);
  assert.throws(() => serializeLoaderData({...item, __prop: "item"}), /Unrecognized/);
  const specific = {__prop: "item", _category: "Specific Variant", _baseSrd: undefined, _baseSrd52: true, entries: ["Rule"], prerequisite: [{level: 2}]};
  const copied = serializeLoaderData(specific);
  assert.equal(Object.hasOwn(copied, "_baseSrd"), false);
  assert.equal(copied._baseSrd52, true);
  assert.deepEqual(copied.prerequisite, specific.prerequisite);
  for (const unknown of [{prerequisite: undefined}, {_baseSrd: undefined}, {value: new Map()}, {callback() {}}]) assert.throws(() => serializeLoaderData(unknown), /Non-JSON/);
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => serializeLoaderData(cyclic), /Cyclic/);
});

test("required-reference audit distinguishes active material from retained version recipes", async () => {
  const payload = {name: "Fixture", source: "XPHB", entries: [{type: "refOptionalfeature", optionalfeature: "Example|XPHB"}], _versions: [{_copy: {name: "Base", source: "XPHB"}, entries: ["{#itemEntry Template|XDMG}"]}]};
  const audit = auditRequiredReferences(payload);
  assert.equal(audit.unresolved.length, 1);
  assert.equal(audit.templates.length, 2);
  let calls = 0;
  const resolved = await resolveRemaining(payload, "classFeature", {
    dereference(entity, prop, field) {
      assert.equal(prop, "classFeature"); assert.equal(field, "entries"); calls++;
      return {...entity, entries: [{name: "Example", entries: ["Resolved rule"], prerequisite: [{level: 2}]}]};
    },
  });
  assert.equal(calls, 1);
  assert.equal(auditRequiredReferences(resolved).unresolved.length, 0);
  assert.deepEqual(resolved._versions, payload._versions);
  await assert.rejects(resolveRemaining(payload, "classFeature", {dereference: data => data}), /Unresolved active/);
  await assert.rejects(resolveRemaining({_copy: {name: "Base"}}, "spell", {}), /Unapplied active/);
});

test("resolved entity descriptions cannot bypass unknown entry-type checks after native dereferencing", async () => {
  const unknown = {path: "/entries/0", type: "unsupportedEntry"};
  const api = {auditEntryTypes: () => [unknown]};
  await assert.rejects(resolveRemaining({entries: [{type: unknown.type}]}, "spell", api), /Unclassified resolved entity entry types.*unsupportedEntry/);
  let passes = 0;
  const reference = {entries: [{type: "refFeat", feat: "Fixture|XPHB"}]};
  await assert.rejects(resolveRemaining(reference, "spell", {...api, dereference: () => ++passes === 1 ? {entries: [{type: "refFeat", feat: "Other|XPHB"}]} : {entries: [{type: unknown.type}]}}), /Unclassified resolved entity entry types/);
  assert.equal(passes, 2);
});

function fixture() {
  const reference = {type: "statblock", tag: "spell", name: "Fixture", source: "XPHB"};
  const data = {name: "Fixture", source: "XPHB", page: 239, __prop: "spell", entries: ["{@spell Ordinary Reference|OTHER}"]};
  const pointer = "/bookData/0/data/7";
  const selection = {bookId: "XPHB", chapterIndex: 7, file: "data/book/book-xphb.json", pointer, chapter: {name: "Fixture chapter", page: 235, entries: [reference, {type: "table", rows: [[1]]}, {type: "image", href: {path: "missing.webp"}}]}};
  const target = {prop: "spell", source: "XPHB", hash: "fixture_xphb", lookup_page: "spells.html", entity_id: entityId({prop: "spell", source: "XPHB", hash: "fixture_xphb"}), uid: "Fixture|XPHB"};
  const record = {record_id: "record-fixture", prop: "spell", fields: Object.keys(data).sort(), raw_sha256: sha256(canonicalJson(data)), origin: {file: "data/spells/fixture.json", json_pointer: "/spell/0", source: "XPHB"}};
  const originValue = origin({file: selection.file, pointer: `${pointer}/entries/0`, source: "XPHB", commit: "fixture", page: pageContext(selection.chapter, pointer)});
  const inventory = {references: [{reference_id: "reference-fixture", occurrence_id: occurrenceId("XPHB", 7, `${pointer}/entries/0`), book_id: "XPHB", chapter_index: 7, kind: "embedded_reference", required: true, origin: originValue, target, raw: reference}], byEntity: new Map([[target.entity_id, [record]]]), readSource: async () => ({spell: [data]})};
  let requested = 0;
  const api = {
    lookup: () => target,
    required: async () => { requested++; return copyJson(data); },
    preload: async value => value.type === "statblockInline" ? copyJson(value) : copyJson(value),
  };
  return {selection, inventory, api, data, target, record, requested: () => requested};
}

test("chapter assembly recovers silent misses through required lookup and keeps complete source layout", async () => {
  const f = fixture();
  const result = await assembleChapter(f.selection, {checkout_sha: "fixture"}, f.inventory, f.api);
  assert.equal(f.requested(), 1);
  assert.deepEqual(result.recovered, ["reference-fixture"]);
  assert.deepEqual(restoreReferences(result.chapter.content), f.selection.chapter);
  const wrapper = result.chapter.content.entries[0];
  assert.equal(wrapper.entity_origin.printed_page, 239);
  assert.equal(wrapper.placement.origin.printed_page, 235);
  assert.equal(wrapper.entity_origin.page_evidence, "source_record");
  assert.deepEqual(wrapper.data.entries, f.data.entries);
});

test("production chapter assembly preserves repeated occurrences and independent placement pages", async () => {
  const f = fixture();
  const ref = f.inventory.references[0];
  f.selection.chapter.entries.splice(1, 0, {name: "Later section", page: 236, entries: [copyJson(ref.raw)]});
  const pointer = `${f.selection.pointer}/entries/1/entries/0`;
  f.inventory.references.push({...ref, reference_id: "reference-second", occurrence_id: occurrenceId("XPHB", 7, pointer), origin: origin({file: f.selection.file, pointer, source: "XPHB", commit: "fixture", page: {printed_page: 236, json_pointer: `${f.selection.pointer}/entries/1`}})});
  const result = await assembleChapter(f.selection, {checkout_sha: "fixture"}, f.inventory, f.api);
  const first = result.chapter.content.entries[0];
  const second = result.chapter.content.entries[1].entries[0];
  assert.equal(first.entity_id, second.entity_id);
  assert.notEqual(first.occurrence_id, second.occurrence_id);
  assert.equal(first.placement.origin.printed_page, 235);
  assert.equal(second.placement.origin.printed_page, 236);
  assert.equal(first.entity_origin.printed_page, 239);
  assert.deepEqual(restoreReferences(result.chapter.content), f.selection.chapter);
});

test("production placement stays unknown when only the entity has a printed page", async () => {
  const f = fixture();
  delete f.selection.chapter.page;
  f.inventory.references[0].origin = origin({file: f.selection.file, pointer: `${f.selection.pointer}/entries/0`, source: "XPHB", commit: "fixture"});
  const {chapter} = await assembleChapter(f.selection, {checkout_sha: "fixture"}, f.inventory, f.api);
  assert.equal(chapter.content.entries[0].placement.origin.printed_page, null);
  assert.equal(chapter.content.entries[0].placement.origin.page_attribution, "unknown");
  assert.equal(chapter.content.entries[0].entity_origin.printed_page, 239);
});

test("missing required targets and inventory identity mismatches fail with exact source context", async () => {
  const f = fixture();
  f.api.required = async () => null;
  await assert.rejects(assembleChapter(f.selection, {checkout_sha: "fixture"}, f.inventory, f.api), error => {
    assert.ok(error instanceof AssemblyError);
    assert.equal(error.issue.code, "INSERTION_RESOLUTION_FAILED");
    assert.equal(error.issue.book, "XPHB");
    assert.equal(error.issue.chapter, 7);
    assert.equal(error.issue.occurrence_path, "/bookData/0/data/7/entries/0");
    assert.deepEqual(error.issue.reference, f.inventory.references[0].raw);
    assert.deepEqual(error.issue.lookup, f.target);
    return true;
  });
  const wrong = fixture();
  wrong.api.lookup = () => ({entity_id: "another-edition"});
  await assert.rejects(assembleChapter(wrong.selection, {checkout_sha: "fixture"}, wrong.inventory, wrong.api), /identity disagrees/);
});
