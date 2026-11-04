import assert from "node:assert/strict";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {atPointer, canonicalJson, copyJson, entityId, origin, pageContext, pointerToken, sha256} from "../common/book_schema.mjs";
import {createInventoryApi} from "../runtime/inventory_runtime.mjs";
import {auditRequiredReferences, serializeLoaderData} from "./assembly_schema.mjs";

export class AssemblyError extends Error {
  constructor(code, message, context = {}) {
    super(message);
    this.name = "AssemblyError";
    this.issue = {severity: "ERROR", code, message, ...context};
  }
}

export async function createAssemblyApi(upstream) {
  const api = createInventoryApi();
  const {DataLoaderDereferencerFacade} = await import(pathToFileURL(path.join(upstream, "js/utils-dataloader/utils-dataloader-dereferencing.js")).href);
  return {
    ...api,
    preload: data => Renderer.utils.preload.pGetPreloaded(data),
    required: target => DataLoader.pCacheAndGet(target.lookup_page, target.source, target.hash, {isCopy: true, isRequired: true}),
    async dereference(entity, prop, field) {
      const input = copyJson(entity);
      function preservePrerequisites(node) {
        if (!node || typeof node !== "object") return;
        if (["refOptionalfeature", "refFeat"].includes(node.type)) node.preserve = {...node.preserve, prerequisite: true};
        for (const [key, child] of Object.entries(node)) if (!["_versions", "entriesTemplate", "_mod"].includes(key)) preservePrerequisites(child);
      }
      // The native generic-feature dereferencer otherwise removes prerequisites.
      preservePrerequisites(input[field]);
      const result = await DataLoaderDereferencerFacade.pGetDereferenced([input], prop, {propEntries: field});
      if (result[prop]?.length !== 1) throw new Error(`Dereferencer returned no unique ${prop}`);
      return result[prop][0];
    },
  };
}

function errorContext(selection, pointer, reference = null, lookup = null) {
  return {book: selection.bookId, chapter: selection.chapterIndex, file: selection.file, occurrence_path: pointer, reference, lookup};
}

/** A bounded fallback for required references left after upstream's main preload. */
export async function resolveRemaining(entity, prop, api) {
  let current = entity;
  function checked(value) {
    const unknown = api.auditEntryTypes?.(value) || [];
    if (unknown.length) throw new Error(`Unclassified resolved entity entry types: ${JSON.stringify(unknown)}`);
    return value;
  }
  for (let attempt = 0; attempt < 2; attempt++) {
    const audit = auditRequiredReferences(current);
    if (!audit.unresolved.length) return checked(current);
    const previous = canonicalJson(serializeLoaderData(current));
    if (audit.unresolved.some(ref => ref.type === "_copy")) throw new Error("Unapplied active _copy remains after native loading");
    if (audit.unresolved.some(ref => ref.type === "statblock" || ref.type === "statblockInline")) current = await api.preload(current);
    const fields = new Set(audit.unresolved.filter(ref => /^ref[A-Z]/.test(ref.type) || ref.type === "structural_string_reference")
      .map(ref => ref.path.split("/")[1]?.replace(/~1/g, "/").replace(/~0/g, "~")));
    for (const field of fields) {
      if (!field) throw new Error("Required reference at entity root cannot be dereferenced");
      current = await api.dereference(current, prop, field);
    }
    if (canonicalJson(serializeLoaderData(current)) === previous) break;
  }
  const unresolved = auditRequiredReferences(current).unresolved;
  if (unresolved.length) throw new Error(`Unresolved active entity references: ${JSON.stringify(unresolved)}`);
  return checked(current);
}

function lookupOrigin(entity, lookup, commit, lookupSource) {
  return {
    file: null, json_pointer: null, source: entity.source, upstream_commit: commit,
    printed_page: entity.page ?? null, page_attribution: entity.page == null ? "unknown" : "explicit",
    page_origin_pointer: null, page_evidence: entity.page == null ? null : "loader_entity",
    lookup_source: lookupSource, lookup: copyJson(lookup),
  };
}

export async function locateEntity(entity, lookup, inventory, api, commit) {
  const candidates = inventory.byEntity.get(entityId(lookup)) || [];
  const evidence = [];
  for (const record of candidates) {
    const raw = atPointer(await inventory.readSource(record.origin.file), record.origin.json_pointer);
    if (sha256(canonicalJson(raw)) !== record.raw_sha256 || canonicalJson(Object.keys(raw).sort()) !== canonicalJson(record.fields)) throw new Error("Physical record differs from inventory metadata");
    if (api.lookup(record.prop, raw).entity_id !== entityId(lookup)) throw new Error("Physical record identity disagrees with lookup");
    const source = raw.source ?? raw.inherits?.source;
    if (source?.toLowerCase() !== entity.source.toLowerCase()) throw new Error("Physical source disagrees with resolved entity");
    evidence.push({record, raw});
  }
  if (evidence.length === 1) {
    const {record, raw} = evidence[0];
    const position = record.origin.json_pointer;
    let pagePointer = null;
    if (raw.page != null && raw.page === entity.page) pagePointer = position;
    else if (raw.inherits?.page != null && raw.inherits.page === entity.page) pagePointer = `${position}/inherits`;
    const entityOrigin = {
      file: record.origin.file, json_pointer: position, source: entity.source, upstream_commit: commit,
      printed_page: entity.page ?? null,
      page_attribution: entity.page == null ? "unknown" : "explicit",
      page_origin_pointer: pagePointer,
      page_evidence: pagePointer ? pagePointer === position ? "source_record" : "template_inherits" : entity.page == null ? null : "loader_entity",
      lookup_source: "physical_record", record_id: record.record_id,
    };
    return {entityOrigin, sourceRecords: candidates, derivation: null};
  }
  if (evidence.length > 1) {
    return {entityOrigin: {...lookupOrigin(entity, lookup, commit, "ambiguous_physical_candidates"), candidates: candidates.map(record => record.origin)}, sourceRecords: candidates, derivation: null};
  }
  // No fictitious physical record is assigned to a native generated item.
  if (lookup.prop !== "item" || !entity.baseItem || !entity.genericVariant) throw new Error("Inventory has no physical source or verified generated-item derivation for this required entity");
  const baseTarget = api.uidLookup("item", entity.baseItem);
  const templateTarget = api.lookup("magicvariant", entity.genericVariant);
  const bases = inventory.byEntity.get(baseTarget.entity_id) || [];
  const templates = inventory.byEntity.get(templateTarget.entity_id) || [];
  if (!bases.length || !templates.length || !templates.every(record => record.prop === "magicvariant")) throw new Error("Generated item has no physical base/template evidence");
  for (const record of [...bases, ...templates]) await inventory.readSource(record.origin.file);
  return {
    entityOrigin: lookupOrigin(entity, lookup, commit, "generated_item"), sourceRecords: [],
    derivation: {method: "native_item_variant", base_item: {uid: entity.baseItem, target: baseTarget, origins: bases.map(record => record.origin)}, template: {target: templateTarget, origins: templates.map(record => record.origin)}},
  };
}

/** Resolve every original insertion of one chapter, preserving the source layout. */
export async function assembleChapter(selection, snapshot, inventory, api) {
  const {bookId, chapterIndex, chapter, file, pointer} = selection;
  const expected = inventory.references.filter(ref => ref.book_id === bookId && ref.chapter_index === chapterIndex && ref.required);
  if (expected.some(ref => ref.kind !== "embedded_reference")) throw new AssemblyError("UNSUPPORTED_BOOK_REFERENCE", "This stage supports source statblocks; inspect newly encountered required book reference types", errorContext(selection, pointer));
  const original = copyJson(chapter);
  let expanded;
  try { expanded = await api.preload(chapter); }
  catch (error) {
    // Retry individual original references only on failure, to identify the exact insertion.
    for (const ref of expected) {
      try { await api.preload(ref.raw); }
      catch (inner) { throw new AssemblyError("PRELOAD_FAILED", inner.message, errorContext(selection, ref.origin.json_pointer, ref.raw, ref.target)); }
    }
    throw new AssemblyError("PRELOAD_FAILED", error.message, errorContext(selection, pointer));
  }
  assert.deepEqual(chapter, original, "Preload mutated the original chapter");
  const wrappers = new Map();
  const omissions = [];
  const templateReferences = [];
  const recovered = [];
  for (const ref of expected) {
    const location = ref.origin.json_pointer;
    const context = errorContext(selection, location, ref.raw, ref.target);
    try {
      const actual = atPointer(original, location.slice(pointer.length));
      assert.deepEqual(actual, ref.raw, "Inventory reference differs from the source chapter");
      let loaded = atPointer(expanded, location.slice(pointer.length));
      if (loaded.type !== "statblockInline" || !loaded.statblockData) {
        const data = await api.required(ref.target);
        if (!data) throw new Error("Required loader returned no entity");
        loaded = await api.preload({...copyJson(ref.raw), type: "statblockInline", statblockType: data.__prop || ref.target.prop, statblockData: data});
        recovered.push(ref.reference_id);
      }
      if (loaded.type !== "statblockInline" || !loaded.statblockData) throw new Error("Required insertion remains unresolved after fallback");
      let data = loaded.statblockData;
      if (api.lookup(loaded.statblockType, data).entity_id !== ref.target.entity_id) throw new Error("Resolved entity identity disagrees with inventory");
      const located = await locateEntity(data, ref.target, inventory, api, snapshot.checkout_sha);
      const normalize = value => serializeLoaderData(value, {sourceRecords: located.sourceRecords, pointer: `${location}/statblockData`, onOmission: omission => omissions.push({book: bookId, chapter: chapterIndex, occurrence_id: ref.occurrence_id, ...omission})});
      data = normalize(data);
      data = normalize(await resolveRemaining(data, loaded.statblockType, api));
      const audit = auditRequiredReferences(data, `${location}/statblockData`);
      if (audit.unresolved.length) throw new Error(`Unresolved required references: ${JSON.stringify(audit.unresolved)}`);
      templateReferences.push(...audit.templates.map(value => ({occurrence_id: ref.occurrence_id, ...value})));
      wrappers.set(location, {
        kind: "embedded_entity", occurrence_id: ref.occurrence_id, entity_id: ref.target.entity_id,
        original_reference: copyJson(ref.raw), lookup: copyJson(ref.target), entity_origin: located.entityOrigin,
        data, derivation: located.derivation,
        placement: {book_id: bookId, chapter_index: chapterIndex, origin: copyJson(ref.origin)},
      });
    } catch (error) { throw new AssemblyError("INSERTION_RESOLUTION_FAILED", error.message, context); }
  }
  function adapt(node, position) {
    if (wrappers.has(position)) return wrappers.get(position);
    if (Array.isArray(node)) return node.map((value, i) => adapt(value, `${position}/${i}`));
    if (!node || typeof node !== "object") return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, adapt(value, `${position}/${pointerToken(key)}`)]));
  }
  return {
    chapter: {chapter_index: chapterIndex, title: original.name, original_id: original.id ?? null,
      origin: origin({file, pointer, source: bookId, commit: snapshot.checkout_sha, page: pageContext(original, pointer)}), content: adapt(original, pointer)},
    recovered, omissions, templateReferences,
  };
}
