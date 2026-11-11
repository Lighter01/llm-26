import {readFile} from "node:fs/promises";
import path from "node:path";
import {BOOK_IDS, walkJson} from "../common/source_scan.mjs";
import {canonicalJson, copyJson, origin, pageContext, pointerToken, sha256} from "../common/book_schema.mjs";

const AUXILIARY_PROPS = new Set(["individual", "hoard", "gems", "artObjects", "magicItems", "languageScript", "itemType"]);

export function fileRole(file) {
  if (/(?:^|\/)foundry(?:[-./])/.test(file)) return "foundry_overlay";
  if (file.startsWith("data/generated/")) return "generated_projection";
  if (file.startsWith("data/book/")) return "book_tree";
  if (file === "data/books.json") return "book_catalog";
  if (file.startsWith("data/adventure/")) return "adventure_tree";
  return "canonical_source";
}

export async function inventorySources(root, commit, fileNames, api, issues) {
  const files = [];
  const records = [];
  const variants = [];
  const all = new Map();
  const byEntity = new Map();
  for (const file of fileNames) {
    const bytes = await readFile(path.join(root, file));
    const data = JSON.parse(bytes.toString("utf8").replace(/^\uFEFF/, ""));
    const role = fileRole(file);
    const summary = {file, role, file_sha256: sha256(bytes), bytes: bytes.length, root_array_props: [], source_record_counts: {}};
    files.push(summary);
    if (!data || typeof data !== "object" || Array.isArray(data)) continue;
    for (const [prop, array] of Object.entries(data)) {
      if (!Array.isArray(array)) continue;
      summary.root_array_props.push(prop);
      for (const [index, raw] of array.entries()) {
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
        const source = typeof raw.source === "string" ? raw.source : prop === "magicvariant" ? raw.inherits?.source : null;
        if (typeof source !== "string") continue;
        const pointer = `/${pointerToken(prop)}/${index}`;
        let target = null;
        let identityError = null;
        try { target = api.lookup(prop, raw); }
        catch (error) { identityError = error.message; }
        const record = {
          record_id: `record:${encodeURIComponent(file)}:${encodeURIComponent(pointer)}`,
          prop, source, name: raw.name ?? raw.abbreviation ?? null, role,
          source_location: `${pointer}${typeof raw.source === "string" ? "/source" : "/inherits/source"}`,
          identity: target, identity_error: identityError,
          origin: origin({file, pointer, source, commit, page: pageContext(raw, pointer)}),
          fields: Object.keys(raw).sort(), raw_sha256: sha256(canonicalJson(raw)),
          structure: {
            has_copy: !!raw._copy, class_table_groups: raw.classTableGroups?.length ?? 0,
            class_feature_refs: raw.classFeatures?.length ?? 0, subclass_feature_refs: raw.subclassFeatures?.length ?? 0,
            has_prerequisite: raw.prerequisite != null,
            prerequisite_sha256: raw.prerequisite == null ? null : sha256(canonicalJson(raw.prerequisite)),
            has_fluff: raw.hasFluff ?? false, has_fluff_images: raw.hasFluffImages ?? false,
            summoned_by_spell: raw.summonedBySpell ?? null, summoned_by_class: raw.summonedByClass ?? null,
          },
          classification: null, classification_reason: null,
          book_reference_ids: [], component_edges: [],
        };
        all.set(record.record_id, {record, raw});
        if (target && !["foundry_overlay", "adventure_tree", "book_tree", "book_catalog"].includes(role)) {
          if (!byEntity.has(target.entity_id)) byEntity.set(target.entity_id, []);
          byEntity.get(target.entity_id).push(record);
        }
        if (role === "canonical_source") walkJson(raw, (node, relative) => {
          if (!node || typeof node !== "object" || !Array.isArray(node._versions)) return;
          for (const [i, variant] of node._versions.entries()) {
            if (!BOOK_IDS.includes((variant.source ?? source).toUpperCase())) continue;
            const position = `${pointer}${relative}/_versions/${i}`;
            variants.push({
              definition_id: `variant:${encodeURIComponent(file)}:${encodeURIComponent(position)}`,
              parent_record_id: record.record_id, file, json_pointer: position,
              name: variant.name ?? null, source: variant.source ?? source,
              source_attribution: variant.source ? "explicit" : "parent_record",
              kind: variant._abstract || variant.abstract ? "abstract_recipe" : "version_definition",
              fields: Object.keys(variant).sort(), raw: copyJson(variant),
              policy: "Inventory definition only; do not generate all combinations or add as book placement.",
            });
          }
        });
        if (!BOOK_IDS.includes(source.toUpperCase())) continue;
        records.push(record);
        summary.source_record_counts[source] = (summary.source_record_counts[source] || 0) + 1;
        if (role === "canonical_source" && !target && !AUXILIARY_PROPS.has(prop)) issues.push({severity: "ERROR", code: "UNKNOWN_SOURCE_IDENTITY", message: identityError, record_id: record.record_id, prop, origin: record.origin});
      }
    }
  }
  return {files, records, variants, all, byEntity};
}

/** Domain edges are planning evidence, never instructions to expand ordinary links. */
export function inventoryDependencies(catalog, api, issues) {
  const edges = [];
  function add(record, relation, pointer, target, raw, required = false, span = null) {
    edges.push({edge_id: `edge:${encodeURIComponent(record.record_id)}:${encodeURIComponent(pointer)}:${relation}${span ? `:${span.start}:${span.end}` : ""}`, from_record_id: record.record_id, relation, file: record.origin.file, json_pointer: pointer, span, required, target, raw: copyJson(raw)});
  }
  function uid(record, relation, pointer, prop, value, required = true) {
    try { add(record, relation, pointer, api.uidLookup(prop, value), value, required); }
    catch (error) { issues.push({severity: required ? "ERROR" : "WARNING", code: "DEPENDENCY_UID_ERROR", message: error.message, record_id: record.record_id, file: record.origin.file, json_pointer: pointer, raw: copyJson(value)}); }
  }
  for (const record of catalog.records) {
    if (record.role !== "canonical_source") continue;
    const raw = catalog.all.get(record.record_id).raw;
    const base = record.origin.json_pointer;
    for (const unknown of api.auditEntryTypes(raw)) issues.push({severity: "ERROR", code: "UNKNOWN_SOURCE_ENTRY_TYPE", record_id: record.record_id, prop: record.prop, file: record.origin.file, json_pointer: base + unknown.path, type: unknown.type, message: `Unclassified entity entry type ${unknown.type}`});
    walkJson(raw, (node, relative) => {
      const pointer = base + relative;
      if (/^ref[A-Z]/.test(node?.type || "")) {
        try { add(record, "structural_reference", pointer, api.structural(node), node, true); }
        catch (error) { issues.push({severity: "ERROR", code: "UNKNOWN_STRUCTURAL_REFERENCE", message: error.message, record_id: record.record_id, file: record.origin.file, json_pointer: pointer, raw: node}); }
      }
      if (node && typeof node === "object" && !Array.isArray(node) && node._copy) {
        try { add(record, "copy_dependency", `${pointer}/_copy`, api.lookup(record.prop, node._copy), node._copy, true); }
        catch (error) { issues.push({severity: "ERROR", code: "COPY_IDENTITY_ERROR", message: error.message, record_id: record.record_id, file: record.origin.file, json_pointer: `${pointer}/_copy`}); }
      }
      if (typeof node !== "string") return;
      for (const ref of api.stringRefs(node)) {
        if (ref.error) issues.push({severity: "ERROR", code: "STRUCTURAL_UID_ERROR", message: ref.error, record_id: record.record_id, file: record.origin.file, json_pointer: pointer, raw: ref.raw});
        else add(record, "structural_string_reference", pointer, ref.target, ref.raw, true, ref.span);
      }
      for (const ref of api.tags(node)) {
        if (ref.target) add(record, "text_reference", pointer, ref.target, ref.raw, false, ref.span);
        else if (ref.kind === "query_reference") edges.push({edge_id: `query:${encodeURIComponent(record.record_id)}:${encodeURIComponent(pointer)}:${ref.span.start}`, from_record_id: record.record_id, relation: "query_reference", file: record.origin.file, json_pointer: pointer, span: ref.span, required: false, target: null, raw: ref.raw, query: ref.query});
        else if (["unknown_tag", "malformed_tag", "unparsed_entity_reference"].includes(ref.kind)) issues.push({severity: "WARNING", code: "SOURCE_TEXT_TAG_REVIEW", message: ref.error || ref.kind, record_id: record.record_id, file: record.origin.file, json_pointer: pointer, raw: ref.raw});
      }
    });
    for (const [field, prop] of [["classFeatures", "classFeature"], ["subclassFeatures", "subclassFeature"], ["cards", "card"]]) {
      if (!Array.isArray(raw[field])) continue;
      raw[field].forEach((value, i) => {
        const reference = typeof value === "string" ? value : value[prop] || value.uid;
        if (typeof reference === "string") uid(record, field, `${base}/${field}/${i}`, prop, reference);
        else issues.push({severity: "ERROR", code: "UNKNOWN_COMPONENT_REFERENCE", record_id: record.record_id, field, index: i, raw: value});
      });
    }
    if (raw.summonedBySpell) uid(record, "summoned_by_spell", `${base}/summonedBySpell`, "spell", raw.summonedBySpell, false);
    if (raw.summonedByClass) uid(record, "summoned_by_class", `${base}/summonedByClass`, "class", raw.summonedByClass, false);
    if (raw.legendaryGroup) {
      try { add(record, "legendary_group", `${base}/legendaryGroup`, api.lookup("legendaryGroup", raw.legendaryGroup), raw.legendaryGroup, true); }
      catch (error) { issues.push({severity: "ERROR", code: "LEGENDARY_GROUP_ERROR", message: error.message, record_id: record.record_id}); }
    }
    if (record.prop === "subclass") {
      add(record, "parent_class", base, api.lookup("class", {name: raw.className, source: raw.classSource}), {className: raw.className, classSource: raw.classSource});
    }
    if (!record.prop.endsWith("Fluff") && record.identity) {
      const fluffProp = ["baseitem", "itemGroup", "magicvariant"].includes(record.prop) ? "itemFluff" : `${record.prop}Fluff`;
      if (api.loaderProps.has(fluffProp)) {
        try {
          const target = api.lookup(fluffProp, {...raw, source: record.source});
          if (catalog.byEntity.has(target.entity_id)) add(record, "companion_fluff", base, target, {hasFluff: raw.hasFluff ?? null, hasFluffImages: raw.hasFluffImages ?? null});
        } catch (error) { issues.push({severity: "WARNING", code: "FLUFF_IDENTITY_REVIEW", message: error.message, record_id: record.record_id}); }
      }
    }
  }
  for (const edge of edges) edge.target_record_ids = edge.target ? (catalog.byEntity.get(edge.target.entity_id) || []).map(record => record.record_id) : [];
  return edges;
}

export function classifySourceRecords(catalog, references, edges) {
  const bookRefs = new Map();
  for (const ref of references) {
    if (!ref.target) continue;
    if (!bookRefs.has(ref.target.entity_id)) bookRefs.set(ref.target.entity_id, []);
    bookRefs.get(ref.target.entity_id).push(ref);
  }
  const incoming = new Map();
  for (const edge of edges) for (const id of edge.target_record_ids) {
    if (!incoming.has(id)) incoming.set(id, []);
    incoming.get(id).push(edge);
  }
  const childRelations = new Set(["classFeatures", "subclassFeatures", "cards", "structural_reference", "structural_string_reference", "companion_fluff", "legendary_group", "copy_dependency"]);
  for (const record of catalog.records) {
    const refs = record.identity ? bookRefs.get(record.identity.entity_id) || [] : [];
    const componentEdges = (incoming.get(record.record_id) || []).filter(edge => childRelations.has(edge.relation));
    const outgoing = edges.filter(edge => edge.from_record_id === record.record_id);
    record.book_reference_ids = refs.map(ref => ref.reference_id);
    record.component_edges = componentEdges.map(edge => edge.edge_id);
    let classification;
    let reason;
    if (record.role !== "canonical_source") {
      classification = record.role;
      reason = "Separate source representation; do not append a second book corpus from this record.";
    } else if (refs.some(ref => ref.required)) {
      classification = "expected_book_insertion"; reason = "Explicit required insertion at the recorded source positions; not assembled yet.";
    } else if (record.prop === "magicvariant") {
      classification = "variant_template"; reason = "Item template; let the native item loader select required book variants.";
    } else if (record.prop === "subclass" && outgoing.some(edge => edge.relation === "parent_class" && bookRefs.has(edge.target.entity_id))) {
      classification = "required_domain_component"; reason = "Subclass of a class explicitly embedded in a selected book.";
    } else if (outgoing.some(edge => ["summoned_by_spell", "summoned_by_class"].includes(edge.relation) && bookRefs.has(edge.target.entity_id))) {
      classification = "required_domain_component"; reason = "Creature associated with a spell/class explicitly embedded in a selected book; placement is deferred.";
    } else if (componentEdges.length) {
      classification = "domain_dependency_candidate"; reason = "Referenced by a structural/companion dependency; verify the parent placement and materialize in later stages.";
    } else if (refs.length || (incoming.get(record.record_id) || []).some(edge => edge.relation === "text_reference")) {
      classification = "text_reference_only"; reason = "An ordinary link is evidence of reference, not permission to expand the record.";
    } else if (AUXILIARY_PROPS.has(record.prop)) {
      classification = "auxiliary_rules_data"; reason = "Auxiliary rules/loot/type metadata; match existing book content before deciding whether to enrich.";
    } else {
      classification = "requires_placement_review"; reason = "Source-defined record without a detected direct placement or domain dependency; no automatic exclusion or append.";
    }
    record.classification = classification;
    record.classification_reason = reason;
  }
}
