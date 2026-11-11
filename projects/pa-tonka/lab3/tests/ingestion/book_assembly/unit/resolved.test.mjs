import assert from "node:assert/strict";
import test from "node:test";
import {copyJson, entityId, occurrenceId, origin, serializeJson, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {contentProjection, contentSha256} from "../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolved_content.mjs";
import {toResolvedBook, validateResolvedBook} from "../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolved_schema.mjs";

const checksum = "a".repeat(64);
const commit = "1".repeat(40);
function fixture() {
  const pointer = "/bookData/0/data/0";
  const file = "data/book/book-xphb.json";
  const sourceOrigin = origin({file, pointer, source: "XPHB", commit, page: {printed_page: 10, json_pointer: pointer}});
  const where = `${pointer}/entries/0`;
  const occurrence = occurrenceId("XPHB", 0, where);
  const lookup = {prop: "monster", source: "XMM", hash: "example_xmm", lookup_page: "bestiary.html"};
  lookup.entity_id = entityId(lookup);
  const ownOrigin = {...origin({file: "data/bestiary/bestiary-xmm.json", pointer: "/monster/0", source: "XMM", commit, page: {printed_page: 50, json_pointer: "/monster/0"}}), lookup_source: "physical_record", record_id: "record:example"};
  const raw = {name: "Example", source: "XMM", page: 50, hp: {average: 12}, entries: ["Keep {@spell Fireball|XPHB}", {type: "table", colLabels: ["A", "B"], rows: [[1, 2]]}], generator: {version: "game", upstream_commit: "game-field"}};
  const anchor = {book_id: "XPHB", chapter_index: 0, occurrence_id: occurrence, origin: {...sourceOrigin, json_pointer: where, page_attribution: "inherited_section_start"}};
  const wrapper = {kind: "embedded_entity", occurrence_id: occurrence, entity_id: lookup.entity_id, original_reference: {type: "statblock", tag: "creature", name: "Example", source: "XMM"}, lookup, entity_origin: ownOrigin, data: raw, derivation: null, placement: {book_id: "XPHB", chapter_index: 0, origin: anchor.origin}};
  const enriched = {stage: 5, scope: {domain_enrichment: true}, book: {id: "XPHB", title: "Fixture", published: "2024-09-17", source_file: file, source_metadata: {id: "XPHB", source: "XPHB"}, catalog_entry: {id: "XPHB", contents: [{name: "Chapter"}]}, catalog_origin: sourceOrigin}, chapters: [{chapter_index: 0, title: "Chapter", original_id: "000", origin: sourceOrigin, content: {type: "section", name: "Chapter", page: 10, entries: [wrapper, {type: "image", href: {type: "internal", path: "book/image.webp"}, credit: "Artist"}]}}], domain: {entities: [{entity_id: lookup.entity_id, prop: "monster", representation: "book_insertion", occurrence_id: occurrence, canonical_placement: {anchor, relation: "explicit_insertion", parent_entity_id: null}, data_origin: ownOrigin, source_records: [{record_id: "record:example", prop: "monster", representation: "source_recipe", origin: ownOrigin, raw}]}], relationships: [{from_entity_id: lookup.entity_id, to_entity_id: "foreign-parent", relation: "inheritance_provenance", evidence: {file: "data/fluff.json", json_pointer: "/fluff/0/_copy", origins: [ownOrigin], raw: {name: "Parent", source: "OTHER"}}, anchor}]}};
  const generator = {name: "dnd_rag.ingestion.5etools_resolver", version: "0.6.0", schema_version: "1.0.0", node_version: process.versions.node, source_sha256: checksum, config_sha256: checksum, config: {books: ["XPHB"]}, signature: checksum};
  return toResolvedBook(enriched, {generator, upstream: {repository: "https://example.test/source", checkout_sha: commit, gitlink_sha: commit, tracked_clean: true, gitlink_matches_checkout: true, package_version: "fixture"}, provenance: Object.fromEntries(["inventory", "assembly", "enrichment"].map(key => [key, {signature: checksum, report_sha256: checksum}]))});
}

test("content hash ignores technical build/physical-locator changes at nested provenance sites", () => {
  const a = fixture();
  const b = copyJson(a);
  b.generator.version = "changed";
  b.generator.signature = "b".repeat(64);
  b.provenance.enrichment.report_sha256 = "b".repeat(64);
  b.upstream.checkout_sha = b.upstream.gitlink_sha = "2".repeat(40);
  b.upstream.package_version = "changed";
  const wrapper = b.chapters[0].content.entries[0];
  const entity = b.domain.entities[0];
  for (const origin of [b.book.catalog_origin, b.chapters[0].origin, wrapper.entity_origin, wrapper.placement.origin, entity.data_origin, entity.source_records[0].origin, entity.canonical_placement.anchor.origin, b.domain.relationships[0].anchor.origin, ...b.domain.relationships[0].evidence.origins]) {
    origin.upstream_commit = b.upstream.checkout_sha;
    origin.file = "data/relocated.json";
    origin.page_origin_pointer = "/changed/42";
  }
  b.book.source_file = "data/relocated-book.json";
  wrapper.entity_origin.json_pointer = "/monster/999";
  entity.source_records[0].record_id = "new-physical-record-id";
  entity.source_records[0].origin.json_pointer = "/monster/999";
  b.domain.relationships[0].evidence.file = "data/relocated-fluff.json";
  b.domain.relationships[0].evidence.json_pointer = "/fluff/999/_copy";
  wrapper.lookup.lookup_page = "different-hover-resource";
  assert.notEqual(sha256(serializeJson(a)), sha256(serializeJson(b)));
  assert.equal(contentSha256(a), contentSha256(b));
  assert.equal(contentProjection(a).chapters[0].content.entries[0].data.generator.upstream_commit, "game-field");
});

test("content hash retains text, tags, mechanics, tables, image metadata, citations and placement", () => {
  const original = fixture();
  const mutations = [
    doc => { doc.chapters[0].content.entries[0].data.hp.average++; },
    doc => { doc.chapters[0].content.entries[0].data.entries[0] = "Changed {@spell Fireball|PHB}"; },
    doc => { doc.chapters[0].content.entries[0].data.entries[1].rows[0][0]++; },
    doc => { doc.chapters[0].content.entries[0].data.generator.version = "changed game rule"; },
    doc => { doc.chapters[0].content.entries[1].credit = "Different artist"; },
    doc => { doc.chapters[0].content.entries[0].entity_origin.printed_page++; },
    doc => { doc.chapters[0].content.entries[0].placement.origin.page_attribution = "unknown"; },
    doc => { doc.domain.entities[0].canonical_placement.anchor.occurrence_id = "different placement"; },
    doc => { doc.domain.entities[0].source_records[0].raw.hp.average++; },
    doc => { doc.chapters[0].content.entries.reverse(); },
  ];
  for (const mutate of mutations) {
    const changed = copyJson(original); mutate(changed);
    assert.notEqual(contentSha256(changed), contentSha256(original));
  }
  const reordered = Object.fromEntries(Object.entries(original).reverse());
  assert.equal(contentSha256(reordered), contentSha256(original));
});

test("resolved schema and standalone graph checks reject losses, mixed origins and dangling materialized references", () => {
  const original = fixture();
  assert.deepEqual(validateResolvedBook(original), {status: "PASS", chapters: 1, embedded_occurrences: 1, canonical_entities: 1});
  const mutations = [
    doc => { delete doc.chapters[0].content.entries[0].data; },
    doc => { doc.chapters[0].content.entries[0].derivation = {method: "invented"}; },
    doc => { doc.scope.book_complete = false; },
    doc => { doc.extra_unversioned_field = true; },
    doc => { doc.domain.entities[0].data_origin.upstream_commit = "2".repeat(40); },
    doc => { doc.domain.entities[0].canonical_placement.parent_entity_id = "missing"; },
    doc => { doc.domain.relationships[0].relation = "legendary_group"; },
    doc => { doc.chapters[0].content.entries.push({type: "statblock", tag: "spell", name: "Missing", source: "XPHB"}); },
    doc => { doc.domain.entities = []; },
  ];
  for (const mutate of mutations) { const changed = copyJson(original); mutate(changed); assert.throws(() => validateResolvedBook(changed)); }
});

test("standalone validation rejects contradictory citations, identities and canonical anchor IDs", () => {
  const original = fixture();
  const mutations = [
    doc => { doc.chapters[0].content.entries[0].entity_origin.source = "OTHER"; },
    doc => { doc.chapters[0].content.entries[0].entity_origin.printed_page = 999999; },
    doc => { doc.chapters[0].content.entries[0].entity_origin.page_attribution = "unknown"; },
    doc => { doc.chapters[0].content.entries[0].lookup.entity_id = "invented"; },
    doc => { doc.domain.entities[0].canonical_placement.anchor.occurrence_id = "invented"; },
    doc => { doc.domain.entities[0].prop = "spell"; },
    doc => {
      const entity = doc.domain.entities[0];
      entity.representation = "domain_component";
      entity.data = copyJson(entity.source_records[0].raw);
      entity.loading_method = "native_data_loader";
      entity.derivation = null;
      delete entity.occurrence_id;
      entity.prop = "spell";
    },
  ];
  for (const mutate of mutations) {
    const changed = copyJson(original);
    mutate(changed);
    assert.throws(() => validateResolvedBook(changed));
  }
});

test("standalone identity checks accept native item aliases and source-record metadata IDs", () => {
  for (const prop of ["baseitem", "itemGroup", "magicvariant"]) {
    const book = fixture();
    const wrapper = book.chapters[0].content.entries[0];
    const entity = book.domain.entities[0];
    wrapper.lookup.prop = "item";
    wrapper.lookup.entity_id = wrapper.entity_id = entityId(wrapper.lookup);
    entity.entity_id = wrapper.entity_id;
    entity.prop = entity.source_records[0].prop = prop;
    book.domain.relationships[0].from_entity_id = entity.entity_id;
    assert.equal(validateResolvedBook(book).status, "PASS");
  }
  const book = fixture();
  const metadata = copyJson(book.domain.entities[0]);
  metadata.entity_id = metadata.source_records[0].record_id;
  metadata.prop = metadata.source_records[0].prop = "hoard";
  metadata.representation = "domain_component";
  metadata.data = copyJson(metadata.source_records[0].raw);
  metadata.loading_method = "verified_source_metadata";
  metadata.derivation = null;
  delete metadata.occurrence_id;
  book.domain.entities.push(metadata);
  assert.equal(validateResolvedBook(book).status, "PASS");
  metadata.prop = "spell";
  assert.throws(() => validateResolvedBook(book), /Metadata identity/);
});
