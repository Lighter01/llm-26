import assert from "node:assert/strict";
import test from "node:test";
import {occurrenceId, origin} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {sourceAnchors, planEnrichment} from "../../../../src/dnd_rag/ingestion/book_assembly/enrichment/enrichment_plan.mjs";
import {annotateSharedFluff} from "../../../../src/dnd_rag/ingestion/book_assembly/enrichment/enrichment_content.mjs";
import {auditPlacement} from "../../../../src/dnd_rag/ingestion/book_assembly/validation/validate_enrichment.mjs";

const file = "data/book/book-xphb.json";
const commit = "fixture";
const position = "/bookData/0/data/0";
const placement = pointer => ({book_id: "XPHB", chapter_index: 0, origin: origin({file, pointer, source: "XPHB", commit, page: {printed_page: 10, json_pointer: position}})});
const id = (prop, name, source = "XPHB") => `entity:${prop}:${name}:${source}`;
const api = {stripTags: text => text,
  lookup: (prop, raw) => ({prop, source: raw.source, entity_id: id(prop, raw.name, raw.source)}),
  uidLookup: (prop, uid) => { const [name, source = "XPHB"] = uid.split("|"); return {prop, source, entity_id: id(prop, name, source)}; },
};
function record(prop, name, source = "XPHB") {
  return {record_id: `${prop}:${name}:${source}`, prop, name, source, role: "canonical_source", identity: api.lookup(prop, {name, source}), origin: origin({file: `data/${prop}.json`, pointer: `/${prop}/0`, source, commit}), raw_sha256: "fixture", classification: "fixture"};
}
function document(content) {
  return {book: {id: "XPHB", source_file: file}, upstream: {checkout_sha: commit}, chapters: [{chapter_index: 0, origin: {json_pointer: position}, content}]};
}

test("domain anchors use source references and section pages, never processed entity pages", () => {
  const doc = document({name: "Chapter", page: 10, entries: [{kind: "embedded_entity", original_reference: {type: "statblock", name: "Ape", source: "XMM"}, data: {name: "Wrong anchor", page: 999}}, {type: "table", rows: [["Literal", "Value"]]}]});
  const anchors = sourceAnchors(doc, text => text);
  const ape = anchors.find(anchor => anchor.label === "ape");
  assert.equal(ape.origin.printed_page, 10);
  assert.equal(ape.origin.source, "XPHB");
  assert.equal(ape.origin.page_attribution, "inherited_section_start");
  assert.equal(ape.occurrence_id, occurrenceId("XPHB", 0, `${position}/entries/0`));
  assert.ok(!anchors.some(anchor => anchor.label === "wrong anchor"));
  assert.ok(anchors.some(anchor => anchor.label === "literal" && anchor.defining));
  assert.ok(anchors.some(anchor => anchor.label === "value" && !anchor.defining));
});

test("domain graph includes subclasses and group members but leaves ordinary prose and item availability external", () => {
  const cls = record("class", "Fighter");
  const sub = record("subclass", "Champion");
  const item = record("itemGroup", "Ring");
  const variant = record("item", "Copper Ring");
  const foreign = record("classFeature", "External Artificer", "EFA");
  const spell = record("spell", "Prose Spell", "OTHER");
  const raws = new Map([[cls.record_id, {name: cls.name, source: cls.source}], [sub.record_id, {name: sub.name, source: sub.source}], [item.record_id, {name: item.name, source: item.source, items: ["Copper Ring|XPHB"]}], [variant.record_id, {name: variant.name, source: variant.source}], [foreign.record_id, {}], [spell.record_id, {}]]);
  const wrapper = rec => ({kind: "embedded_entity", entity_id: rec.identity.entity_id, occurrence_id: rec.record_id, placement: placement(`${position}/entries/0`), lookup: rec.identity});
  const doc = document({name: "Chapter", page: 10, entries: [wrapper(cls), wrapper(item), "An ordinary link"]});
  const inventory = {byRecord: new Map([cls, sub, item, variant, foreign, spell].map(row => [row.record_id, row])), references: [{book_id: "XPHB", required: false, target: spell.identity, origin: {json_pointer: `${position}/entries/2`}}]};
  const deps = [{from_record_id: sub.record_id, relation: "parent_class", target: cls.identity, file: "data/subclass.json", json_pointer: "/subclass/0", raw: {}}, {from_record_id: item.record_id, relation: "classFeatures", target: foreign.identity, file: "data/item.json", json_pointer: "/item/0/classFeatures/0", raw: "External"}];
  const plan = planEnrichment(doc, inventory, {rawRecords: raws, dependencies: deps}, api);
  assert.ok(plan.selected.has(sub.identity.entity_id));
  assert.ok(plan.selected.has(variant.identity.entity_id));
  assert.ok(!plan.selected.has(foreign.identity.entity_id));
  assert.ok(!plan.selected.has(spell.identity.entity_id));
  assert.equal(new Set(plan.selected.keys()).size, plan.selected.size);
  assert.throws(() => plan.target({entity_id: "missing"}, placement(position), "legendary_group", cls.identity.entity_id, {file: "data/monster.json", json_pointer: "/monster/0/legendaryGroup"}), error => error.issue.code === "DOMAIN_DEPENDENCY_MISSING" && error.issue.reference.json_pointer === "/monster/0/legendaryGroup");
});

test("placement audit rejects unknown canonical records and content-bearing font/type records", () => {
  const rows = [record("unexpectedRules", "Missing"), record("languageScript", "Font"), record("itemType", "Unused")];
  const inventory = {byRecord: new Map(rows.map(row => [row.record_id, row]))};
  const inputs = {rawRecords: new Map([[rows[0].record_id, {entries: ["Rule"]}], [rows[1].record_id, {name: "Font", source: "XPHB", fonts: ["asset"], entries: ["Do not discard"]}], [rows[2].record_id, {name: "Unused", abbreviation: "T", source: "XPHB"}]])};
  const doc = {...document({}), domain: {entities: []}};
  const audit = auditPlacement(doc, inventory, inputs);
  assert.equal(audit[0].status, "unreviewed_critical");
  assert.equal(audit[1].status, "unreviewed_critical");
  assert.equal(audit[2].status, "excluded_renderer_taxonomy");
  assert.deepEqual(audit[2].evidence.raw, inputs.rawRecords.get(rows[2].record_id));
});

test("generated table equivalence retains footnotes, multi-row labels and all content fields", () => {
  const source = {type: "table", caption: "Travel Pace", colLabelRows: [["Pace", "Distance"], ["", "Per hour"]], colStyles: ["col-6", "col-6"], rows: [["Fast", 4]], footnotes: ["Apply the travel rule."], data: {genTables: {tableInclude: true, reprintedAs: ["Travel|XPHB"]}, rule: {penalty: -5}}};
  const generated = {caption: source.caption, colLabelRows: source.colLabelRows, colStyles: source.colStyles, rows: source.rows, footnotes: source.footnotes, data: {rule: {penalty: -5}}, reprintedAs: ["Travel|XPHB"], name: "Travel; Travel Pace", source: "XPHB", page: 10, chapter: {name: "Chapter", index: 0}, basicRules2024: true};
  const row = {...record("table", "Travel; Travel Pace"), role: "generated_projection"};
  const audit = raw => auditPlacement({...document(source), domain: {entities: []}}, {byRecord: new Map([[row.record_id, row]])}, {rawRecords: new Map([[row.record_id, raw]])})[0];
  assert.equal(audit(generated).status, "represented_generated_projection");
  for (const change of [
    value => { value.caption = "A different rule"; },
    value => { value.footnotes = ["A changed penalty."]; },
    value => { delete value.footnotes; },
    value => { value.colLabelRows[1][1] = "Per day"; },
    value => { value.colStyles[0] = "text-center"; },
    value => { value.data.rule.penalty = -10; },
    value => { value.futureRule = "Do not silently discard new fields."; },
    value => { value.reprintedAs = ["Wrong|XPHB"]; },
  ]) {
    const changed = structuredClone(generated);
    change(changed);
    assert.equal(audit(changed).status, "unreviewed_critical");
  }
});

test("generated table groups preserve group content and every complete component", () => {
  const first = {type: "table", caption: "Arcana - Common", rows: [[1, "Item"]], footnotes: ["First rule."]};
  const second = {type: "table", caption: "Arcana - Rare", rows: [[2, "Other Item"]], colLabelRows: [["Roll", "Treasure"]]};
  const row = {...record("tableGroup", "Random Magic Items - Arcana"), role: "generated_projection"};
  const audit = (source, raw) => auditPlacement({...document(source), domain: {entities: []}}, {byRecord: new Map([[row.record_id, row]])}, {rawRecords: new Map([[row.record_id, raw]])})[0];
  // Faux groups aggregate separately located tables; their child path metadata
  // is added by _doSearch and is retained by upstream's faux group generator.
  const fauxSource = {entries: [first, second].map(table => ({...table, data: {genTables: {fauxGroupSource: "XPHB", fauxGroupName: row.name}}}))};
  const faux = {type: "tableGroup", name: row.name, source: "XPHB", page: 10, tables: [{...first, path: [{name: "Chapter", page: 10}], section: "Arcana", sectionIndex: 1}, second]};
  assert.equal(audit(fauxSource, faux).status, "represented_generated_projection");
  const changed = structuredClone(faux);
  changed.tables[1].colLabelRows[0][1] = "Changed rule";
  assert.equal(audit(fauxSource, changed).status, "unreviewed_critical");
  assert.equal(audit(fauxSource, {...faux, footnotes: ["Extra group rule."]}).status, "unreviewed_critical");
  assert.equal(audit(fauxSource, {...faux, tables: [first]}).status, "unreviewed_critical");
  assert.equal(audit(fauxSource, {...faux, tables: [second, first]}).status, "unreviewed_critical");
  assert.equal(audit(fauxSource, {...faux, name: "Unproven group"}).status, "unreviewed_critical");
  assert.equal(audit({entries: [first, second]}, faux).status, "unreviewed_critical");
  const actualGroup = {type: "tableGroup", tables: [first, second], footnotes: ["Group rule."]};
  assert.equal(audit(actualGroup, {...faux, footnotes: actualGroup.footnotes}).status, "represented_generated_projection");
  assert.equal(audit(actualGroup, faux).status, "unreviewed_critical");
});

test("shared fluff annotations retain the complete native result and identify reusable blocks", () => {
  const common = {type: "section", entries: ["Common lore"]};
  const individual = {type: "section", entries: ["Individual lore"]};
  const doc = {chapters: [], domain: {entities: [{entity_id: "group", data: {entries: [common]}}, {entity_id: "individual", data: {entries: [individual, common]}}], relationships: [{from_entity_id: "individual", to_entity_id: "group", relation: "shared_fluff_parent"}]}};
  annotateSharedFluff(doc);
  annotateSharedFluff(doc);
  assert.deepEqual(doc.domain.entities[1].data.entries, [individual, common]);
  assert.deepEqual(doc.domain.entities[1].shared_content, [{path: "/entries/1", parent_entity_id: "group", parent_path: "/entries/0"}]);
});
