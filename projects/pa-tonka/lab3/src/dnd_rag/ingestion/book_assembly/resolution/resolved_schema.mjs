import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {atPointer, canonicalJson, copyJson, entityId, occurrenceId, restoreReferences} from "../common/book_schema.mjs";
import {auditRequiredReferences} from "../assembly/assembly_schema.mjs";
import {collectEmbedded} from "../common/tree.mjs";

export const RESOLVED_SCHEMA_VERSION = "1.0.0";
export const RESOLVER_VERSION = "0.6.2";
export const RESOLVED_BOOK_SCHEMA = JSON.parse(await readFile(new URL("./resolved-book.schema.json", import.meta.url), "utf8"));
const lookupProp = prop => ["baseitem", "itemGroup", "magicvariant"].includes(prop) ? "item" : prop;

/** Validator for the deliberately small JSON Schema vocabulary used by our contract. */
export function validateContract(value, schema = RESOLVED_BOOK_SCHEMA, rule = schema) {
  function check(value, rule, pointer) {
    const fail = message => { throw new Error(`Resolved schema ${pointer || "/"}: ${message}`); };
    if (rule.$ref) check(value, atPointer(schema, rule.$ref.slice(1)), pointer);
    if (rule.anyOf && !rule.anyOf.some(branch => { try { check(value, branch, pointer); return true; } catch { return false; } })) fail("no matching representation");
    if (Object.hasOwn(rule, "const") && canonicalJson(value) !== canonicalJson(rule.const)) fail("unexpected constant");
    if (rule.enum && !rule.enum.some(item => canonicalJson(value) === canonicalJson(item))) fail("unexpected enum value");
    const is = type => type === "null" ? value === null : type === "array" ? Array.isArray(value) : type === "object" ? value !== null && typeof value === "object" && !Array.isArray(value) : type === "integer" ? Number.isSafeInteger(value) : typeof value === type;
    if (rule.type && ![rule.type].flat().some(is)) fail(`expected ${rule.type}`);
    if (typeof value === "string" && rule.pattern && !new RegExp(rule.pattern).test(value)) fail("invalid string pattern");
    if (typeof value === "number" && rule.minimum != null && value < rule.minimum) fail("value below minimum");
    if (Array.isArray(value)) {
      if (rule.minItems != null && value.length < rule.minItems) fail("too few items");
      if (rule.items) value.forEach((child, i) => check(child, rule.items, `${pointer}/${i}`));
    } else if (value && typeof value === "object") {
      for (const key of rule.required || []) if (!Object.hasOwn(value, key)) fail(`missing ${key}`);
      for (const [key, child] of Object.entries(value)) {
        if (rule.properties?.[key]) check(child, rule.properties[key], `${pointer}/${key}`);
        else if (rule.additionalProperties === false) fail(`unexpected field ${key}`);
        else if (rule.additionalProperties && typeof rule.additionalProperties === "object") check(child, rule.additionalProperties, `${pointer}/${key}`);
      }
    }
  }
  copyJson(value);
  check(value, rule, "");
}

export function toResolvedBook(enriched, {generator, upstream, provenance}) {
  assert.equal(enriched.stage, 5);
  assert.equal(enriched.scope.domain_enrichment, true);
  return {artifact_kind: "resolved_book", stage: 6, schema_version: RESOLVED_SCHEMA_VERSION,
    generator: copyJson(generator), upstream: copyJson(upstream), provenance: copyJson(provenance),
    scope: {all_source_chapters: true, embedded_references_resolved: true, domain_enrichment: true, book_complete: true},
    book: copyJson(enriched.book), chapters: copyJson(enriched.chapters), domain: copyJson(enriched.domain)};
}

/** Standalone validation needs only this book; no upstream or other book/registry. */
export function validateResolvedBook(document) {
  validateContract(document);
  assert.equal(document.upstream.checkout_sha, document.upstream.gitlink_sha);
  const wrappers = new Map();
  const sourceChapters = document.chapters.map(chapter => restoreReferences(chapter.content));
  const checkOrigin = origin => assert.equal(origin.upstream_commit, document.upstream.checkout_sha, "Origin snapshot mismatch");
  const checkDerivation = value => {
    if (!value) return;
    for (const field of ["base_item", "template"]) {
      assert.equal(value[field].target.entity_id, entityId(value[field].target));
      value[field].origins.forEach(checkOrigin);
    }
  };
  checkOrigin(document.book.catalog_origin);
  function checkSourceNodes(node) {
    if (typeof node === "string") assert.ok(!node.includes("{#"), "Unresolved structural string reference in book content");
    if (!node || typeof node !== "object") return;
    if (node.kind === "embedded_entity") return;
    assert.ok(node.type !== "statblock" && !(node.type === "statblockInline" && !node.statblockData) && !/^ref[A-Z]/.test(node.type || ""), "Unresolved insertion in book content");
    for (const child of Object.values(node)) checkSourceNodes(child);
  }
  for (const [i, chapter] of document.chapters.entries()) {
    assert.equal(chapter.chapter_index, i);
    checkOrigin(chapter.origin);
    checkSourceNodes(chapter.content);
    for (const wrapper of collectEmbedded(chapter.content)) {
      validateContract(wrapper, RESOLVED_BOOK_SCHEMA, RESOLVED_BOOK_SCHEMA.$defs.wrapper);
      assert.ok(!wrappers.has(wrapper.occurrence_id), "Duplicate insertion occurrence");
      wrappers.set(wrapper.occurrence_id, wrapper);
      assert.equal(wrapper.entity_id, entityId(wrapper.lookup));
      assert.equal(wrapper.lookup.entity_id, wrapper.entity_id, "Lookup identity mismatch");
      assert.equal(wrapper.placement.book_id, document.book.id);
      assert.equal(wrapper.placement.chapter_index, i);
      assert.equal(wrapper.occurrence_id, occurrenceId(document.book.id, i, wrapper.placement.origin.json_pointer));
      assert.equal(wrapper.data.source.toLowerCase(), wrapper.lookup.source.toLowerCase());
      assert.equal(wrapper.entity_origin.source, wrapper.data.source, "Insertion source citation mismatch");
      assert.equal(wrapper.entity_origin.printed_page, wrapper.data.page ?? null, "Insertion page citation mismatch");
      assert.equal(wrapper.entity_origin.page_attribution, wrapper.data.page == null ? "unknown" : "explicit");
      checkOrigin(wrapper.entity_origin);
      checkOrigin(wrapper.placement.origin);
      checkDerivation(wrapper.derivation);
      assert.deepEqual(auditRequiredReferences(wrapper.data).unresolved, []);
    }
  }
  const entities = new Map(document.domain.entities.map(entity => [entity.entity_id, entity]));
  assert.equal(entities.size, document.domain.entities.length, "Duplicate canonical entity");
  const payload = entity => entity.representation === "book_insertion" ? wrappers.get(entity.occurrence_id)?.data : entity.data;
  for (const entity of entities.values()) {
    const data = payload(entity);
    assert.ok(data, "Entity has no materialized payload in this book");
    if (entity.representation === "book_insertion") {
      const wrapper = wrappers.get(entity.occurrence_id);
      assert.equal(wrapper.entity_id, entity.entity_id);
      assert.equal(lookupProp(entity.prop), wrapper.lookup.prop, "Canonical insertion type mismatch");
    }
    if (entity.entity_id.startsWith("entity:")) {
      const parts = entity.entity_id.split(":");
      assert.equal(parts.length, 4, "Invalid canonical entity identity");
      assert.equal(entity.entity_id, entityId({prop: lookupProp(entity.prop), source: data.source, hash: decodeURIComponent(parts[3])}), "Canonical type/source identity mismatch");
    } else {
      assert.ok(entity.source_records.some(record => record.record_id === entity.entity_id && record.prop === entity.prop), "Metadata identity has no matching source record");
    }
    assert.deepEqual(auditRequiredReferences(data).unresolved, []);
    assert.equal(entity.data_origin.source, data.source);
    checkOrigin(entity.data_origin);
    checkOrigin(entity.canonical_placement.anchor.origin);
    entity.source_records.forEach(record => checkOrigin(record.origin));
    checkDerivation(entity.derivation);
    assert.equal(entity.data_origin.printed_page, data.page ?? null);
    const placement = entity.canonical_placement;
    assert.equal(placement.anchor.book_id, document.book.id);
    assert.equal(placement.anchor.occurrence_id, occurrenceId(document.book.id, placement.anchor.chapter_index, placement.anchor.origin.json_pointer), "Canonical anchor identity mismatch");
    const chapter = document.chapters[placement.anchor.chapter_index];
    assert.ok(chapter);
    const relative = placement.anchor.origin.json_pointer.slice(chapter.origin.json_pointer.length);
    assert.ok(placement.anchor.origin.json_pointer === chapter.origin.json_pointer || placement.anchor.origin.json_pointer.startsWith(`${chapter.origin.json_pointer}/`));
    // Resolve an anchor against the restored source rather than processed entity fields.
    atPointer(sourceChapters[placement.anchor.chapter_index], relative);
    const ancestors = new Set([entity.entity_id]);
    let parent = placement.parent_entity_id;
    while (parent) { assert.ok(entities.has(parent), "Missing placement parent"); assert.ok(!ancestors.has(parent), "Placement cycle"); ancestors.add(parent); parent = entities.get(parent).canonical_placement.parent_entity_id; }
    for (const shared of entity.shared_content || []) assert.deepEqual(atPointer(data, shared.path), atPointer(payload(entities.get(shared.parent_entity_id)), shared.parent_path));
  }
  for (const wrapper of wrappers.values()) assert.ok(entities.has(wrapper.entity_id), "Insertion missing from domain graph");
  for (const edge of document.domain.relationships) {
    checkOrigin(edge.anchor.origin);
    for (const key of ["origin", "source_origin", "fluff_origin"]) if (edge.evidence[key]) checkOrigin(edge.evidence[key]);
    if (edge.evidence.origins) edge.evidence.origins.forEach(checkOrigin);
    if (edge.from_entity_id) assert.ok(entities.has(edge.from_entity_id), "Missing relationship source");
    if (edge.relation !== "inheritance_provenance") assert.ok(entities.has(edge.to_entity_id), "Missing relationship target");
  }
  return {status: "PASS", chapters: document.chapters.length, embedded_occurrences: wrappers.size, canonical_entities: entities.size};
}
