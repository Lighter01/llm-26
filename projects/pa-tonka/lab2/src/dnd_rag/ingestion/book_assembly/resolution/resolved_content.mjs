import {canonicalJson, copyJson, sha256} from "../common/book_schema.mjs";

export const CONTENT_HASH_ALGORITHM = "dnd-book-content-v1";

// Only adapter-owned provenance is projected. Upstream data/raw remain untouched,
// including game fields coincidentally named hash, version, origin, or generator.
const citation = value => value == null ? value : {source: value.source, printed_page: value.printed_page, page_attribution: value.page_attribution};
const lookup = value => Object.fromEntries(Object.entries(value).filter(([key]) => key !== "lookup_page"));
const anchor = value => ({book_id: value.book_id, chapter_index: value.chapter_index, occurrence_id: value.occurrence_id, origin: citation(value.origin)});

function derivation(value) {
  if (!value) return value;
  return Object.fromEntries(["base_item", "template"].map(field => [field, {
    ...(value[field].uid == null ? {} : {uid: value[field].uid}),
    target: lookup(value[field].target), origins: value[field].origins.map(citation),
  }]));
}

function chapterContent(node) {
  if (Array.isArray(node)) return node.map(chapterContent);
  if (!node || typeof node !== "object") return node;
  if (node.kind === "embedded_entity") return {
    kind: node.kind, occurrence_id: node.occurrence_id, entity_id: node.entity_id,
    original_reference: copyJson(node.original_reference), lookup: lookup(node.lookup),
    entity_origin: citation(node.entity_origin), data: copyJson(node.data), derivation: derivation(node.derivation),
    placement: {book_id: node.placement.book_id, chapter_index: node.placement.chapter_index, origin: citation(node.placement.origin)},
  };
  return Object.fromEntries(Object.entries(node).map(([key, child]) => [key, chapterContent(child)]));
}

function evidence(value) {
  return Object.fromEntries(Object.entries(value).flatMap(([key, child]) => {
    if (["file", "json_pointer", "reference_id", "span"].includes(key)) return [];
    if (["origin", "source_origin", "fluff_origin"].includes(key)) return [[key, citation(child)]];
    if (key === "origins") return [[key, child.map(citation)]];
    if (key === "members") return [[key, child.map(lookup)]];
    return [[key, copyJson(child)]];
  }));
}

/** Versioned semantic projection: citations/placement matter; build diagnostics do not. */
export function contentProjection(document) {
  const {source_file, catalog_origin, ...book} = document.book;
  return {
    algorithm: CONTENT_HASH_ALGORITHM,
    book: {...copyJson(book), catalog_origin: citation(catalog_origin)},
    chapters: document.chapters.map(chapter => ({chapter_index: chapter.chapter_index, title: chapter.title, original_id: chapter.original_id, origin: citation(chapter.origin), content: chapterContent(chapter.content)})),
    domain: {
      entities: document.domain.entities.map(entity => ({
        entity_id: entity.entity_id, prop: entity.prop, representation: entity.representation,
        canonical_placement: {anchor: anchor(entity.canonical_placement.anchor), relation: entity.canonical_placement.relation, parent_entity_id: entity.canonical_placement.parent_entity_id},
        source_records: entity.source_records.map(record => ({prop: record.prop, representation: record.representation, origin: citation(record.origin), raw: copyJson(record.raw)})),
        data_origin: citation(entity.data_origin),
        ...(entity.occurrence_id == null ? {} : {occurrence_id: entity.occurrence_id}),
        ...(entity.data == null ? {} : {data: copyJson(entity.data), derivation: derivation(entity.derivation)}),
        ...(entity.shared_content == null ? {} : {shared_content: copyJson(entity.shared_content)}),
      })),
      relationships: document.domain.relationships.map(edge => ({from_entity_id: edge.from_entity_id, to_entity_id: edge.to_entity_id, relation: edge.relation, evidence: evidence(edge.evidence), anchor: anchor(edge.anchor)})),
    },
  };
}

export function contentSha256(document) {
  return sha256(canonicalJson(contentProjection(document)));
}
