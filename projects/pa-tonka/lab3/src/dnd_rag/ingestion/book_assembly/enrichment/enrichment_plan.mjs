import {canonicalJson, copyJson, occurrenceId, origin, pageContext, pointerToken} from "../common/book_schema.mjs";
import {collectEmbedded} from "../common/tree.mjs";
import {AssemblyError} from "../assembly/assembly_content.mjs";

const ITEM_PROPS = new Set(["item", "baseitem", "itemGroup", "magicvariant"]);
const TABLE_PROPS = new Set(["item", "skill", "language", "deity", "itemProperty", "itemMastery"]);
const NAMED_PROPS = new Set(["item", "baseitem", "itemGroup", "itemProperty", "itemMastery", "skill", "language", "hazard", "gems", "artObjects", "magicItems"]);
const COMPONENT_RELATIONS = new Set(["subclassFeatures", "cards", "structural_reference", "structural_string_reference", "companion_fluff", "legendary_group"]);

/** Source positions only; no path or printed page is inferred from an entity name. */
export function sourceAnchors(document, stripTags) {
  const anchors = [];
  function visit(node, pointer, chapter, inherited, ancestors) {
    const page = pageContext(node, pointer, inherited);
    const here = {book_id: document.book.id, chapter_index: chapter.chapter_index, occurrence_id: occurrenceId(document.book.id, chapter.chapter_index, pointer), origin: origin({file: document.book.source_file, pointer, source: document.book.id, commit: document.upstream.checkout_sha, page})};
    const label = typeof node === "string" ? node : node?.name || node?.caption;
    if (label) anchors.push({...here, label: stripTags(label).toLowerCase().replace(/\s+/g, " ").trim(), raw_label: label,
      defining: typeof node === "object" || /\/rows\/\d+\/(?:row\/)?0$/.test(pointer), ancestors});
    if (node && typeof node === "object") for (const [key, child] of Object.entries(node)) visit(child, `${pointer}/${pointerToken(key)}`, chapter, page, [...ancestors, ...(node.name || node.caption ? [stripTags(node.name || node.caption)] : [])]);
  }
  for (const chapter of document.chapters) {
    // Restore only explicit insertions. Their processed payload has its own origin.
    function restore(node) {
      if (node?.kind === "embedded_entity") return node.original_reference;
      if (Array.isArray(node)) return node.map(restore);
      if (node && typeof node === "object") return Object.fromEntries(Object.entries(node).map(([key, child]) => [key, restore(child)]));
      return node;
    }
    visit(restore(chapter.content), chapter.origin.json_pointer, chapter, null, []);
  }
  return anchors;
}

/** A finite, evidence-led graph. Ordinary prose tags are never recursive edges. */
export function planEnrichment(document, inventory, inputs, api) {
  const bookId = document.book.id;
  const wrappers = document.chapters.flatMap(chapter => collectEmbedded(chapter.content));
  const anchors = sourceAnchors(document, api.stripTags);
  const records = [...inventory.byRecord.values()].filter(record => record.role === "canonical_source");
  const byEntity = new Map();
  for (const record of records) if (record.identity) {
    if (!byEntity.has(record.identity.entity_id)) byEntity.set(record.identity.entity_id, []);
    byEntity.get(record.identity.entity_id).push(record);
  }
  const selected = new Map();
  const links = [];
  const linkKeys = new Set();
  const queue = [];
  function link(from, to, relation, evidence, anchor) {
    const value = {from_entity_id: from, to_entity_id: to, relation, evidence: copyJson(evidence), anchor: copyJson(anchor)};
    const key = canonicalJson(value);
    if (!linkKeys.has(key)) { linkKeys.add(key); links.push(value); }
  }
  function include(record, anchor, relation, from = null, evidence = null) {
    const id = record.identity?.entity_id || record.record_id;
    link(from, id, relation, evidence || {origin: record.origin}, anchor);
    if (selected.has(id)) return;
    selected.set(id, {entity_id: id, records: record.identity ? byEntity.get(id) : [record], anchor: copyJson(anchor), relation, from_entity_id: from, existing: null});
    queue.push(id);
  }
  function target(target, anchor, relation, from, evidence) {
    const candidates = byEntity.get(target.entity_id);
    if (!candidates?.length) throw new AssemblyError("DOMAIN_DEPENDENCY_MISSING", `Missing physical domain dependency: ${relation}: ${target.entity_id}`, {book: bookId, chapter: anchor.chapter_index, occurrence_path: anchor.origin.json_pointer, relation, parent_entity_id: from, reference: copyJson(evidence), lookup: copyJson(target)});
    include(candidates[0], anchor, relation, from, evidence);
  }
  for (const wrapper of wrappers) {
    if (selected.has(wrapper.entity_id)) continue;
    const anchor = {...copyJson(wrapper.placement), occurrence_id: wrapper.occurrence_id};
    selected.set(wrapper.entity_id, {entity_id: wrapper.entity_id, records: byEntity.get(wrapper.entity_id) || [], anchor, relation: "explicit_insertion", from_entity_id: null, existing: wrapper});
    queue.push(wrapper.entity_id);
  }
  const own = records.filter(record => record.source.toUpperCase() === bookId);
  // A named table row defines a listed entity. An incidental prose reference does not.
  for (const ref of inventory.references) {
    if (ref.book_id !== bookId || ref.required || !ref.target || ref.target.source.toUpperCase() !== bookId || !TABLE_PROPS.has(ref.target.prop) || !/\/rows\//.test(ref.origin.json_pointer)) continue;
    if (!byEntity.has(ref.target.entity_id)) continue; // ordinary catalog misses stay ordinary references
    target(ref.target, {book_id: bookId, chapter_index: ref.chapter_index, occurrence_id: ref.occurrence_id, origin: ref.origin}, "defining_table_reference", null, {reference_id: ref.reference_id, raw: ref.raw, span: ref.span});
  }
  // Some source sections/rows use literal labels, including tool prices.
  for (const record of own) {
    if (!NAMED_PROPS.has(record.prop) || selected.has(record.identity?.entity_id || record.record_id) || !record.name) continue;
    const label = api.stripTags(record.name).toLowerCase();
    const matches = anchors.filter(anchor => anchor.defining && (anchor.label === label || anchor.label.replace(/ \([\d,.]+ [csegp]p\)$/, "") === label));
    if (!matches.length) continue;
    const ranked = matches.toSorted((a, b) => Math.abs((a.origin.printed_page ?? -10000) - (record.origin.printed_page ?? 0)) - Math.abs((b.origin.printed_page ?? -10000) - (record.origin.printed_page ?? 0)));
    include(record, ranked[0], "named_source_section_or_row", null, {label: ranked[0].raw_label});
  }
  const outgoing = new Map();
  const reverse = new Map();
  for (const edge of inputs.dependencies) {
    if (!outgoing.has(edge.from_record_id)) outgoing.set(edge.from_record_id, []);
    outgoing.get(edge.from_record_id).push(edge);
    if (["parent_class", "summoned_by_spell", "summoned_by_class"].includes(edge.relation) && edge.target) {
      if (!reverse.has(edge.target.entity_id)) reverse.set(edge.target.entity_id, []);
      reverse.get(edge.target.entity_id).push(edge);
    }
  }
  function drain() {
    while (queue.length) {
      const id = queue.shift();
      const node = selected.get(id);
      for (const edge of reverse.get(id) || []) {
        const record = inventory.byRecord.get(edge.from_record_id);
        if (record.source.toUpperCase() !== bookId) continue;
        include(record, node.anchor, edge.relation === "parent_class" ? "subclass" : edge.relation, id, {file: edge.file, json_pointer: edge.json_pointer, raw: edge.raw});
      }
      for (const record of node.records) {
        const raw = inputs.rawRecords.get(record.record_id);
        for (const edge of outgoing.get(record.record_id) || []) {
          if (!edge.target) continue;
          if (COMPONENT_RELATIONS.has(edge.relation) || edge.relation === "classFeatures" && record.prop === "class") {
            // Deferred recipes are not live dependencies.
            const relative = edge.json_pointer.slice(record.origin.json_pointer.length);
            if (/\/(?:_versions|entriesTemplate|_mod)(?:\/|$)/.test(relative)) continue;
            target(edge.target, node.anchor, edge.relation, id, {file: edge.file, json_pointer: edge.json_pointer, raw: edge.raw, span: edge.span});
          }
          if (edge.relation === "copy_dependency") link(id, edge.target.entity_id, "inheritance_provenance", {file: edge.file, json_pointer: edge.json_pointer, raw: edge.raw, origins: edge.target_record_ids.map(id => inventory.byRecord.get(id)?.origin).filter(Boolean)}, node.anchor);
        }
        if (record.prop.endsWith("Fluff") && raw._copy) {
          const parent = api.lookup(record.prop, raw._copy);
          if (byEntity.has(parent.entity_id)) target(parent, node.anchor, "shared_fluff_parent", id, {origin: record.origin, copy: raw._copy});
        }
        if (record.prop === "itemGroup") for (const uid of raw.items || []) target(api.uidLookup("item", uid), node.anchor, "item_group_member", id, {origin: record.origin, field: "items", uid});
        if (ITEM_PROPS.has(record.prop)) {
          if (raw.ammoType) target(api.uidLookup("item", raw.ammoType), node.anchor, "ammunition_type", id, {origin: record.origin, field: "ammoType", uid: raw.ammoType});
          for (const entry of raw.packContents || []) {
            if (entry.item) target(api.uidLookup("item", entry.item), node.anchor, "pack_content", id, {origin: record.origin, field: "packContents", entry});
          }
          for (const [field, prop] of [["type", "itemType"], ["typeAlt", "itemType"], ["property", "itemProperty"], ["mastery", "itemMastery"]]) {
            for (const value of [raw[field]].flat().filter(Boolean)) {
              const uid = typeof value === "string" ? value : value.uid;
              if (typeof uid !== "string") throw new Error(`Unknown ${field} item metadata UID: ${canonicalJson(value)}`);
              const lookup = api.uidLookup(prop, uid);
              if (byEntity.has(lookup.entity_id)) target(lookup, node.anchor, `item_${field}`, id, {origin: record.origin, field, uid});
            }
          }
          // These are alternative structured representations of the very same item.
          for (const companion of own.filter(row => ["deck", "vehicle"].includes(row.prop) && row.name === record.name)) include(companion, node.anchor, "item_companion_representation", id, {origin: record.origin});
        }
        if (record.prop === "facility") for (const reward of own.filter(row => row.prop === "reward")) {
          const rewardRaw = inputs.rawRecords.get(reward.record_id);
          if ((rewardRaw.seeAlsoFacility || []).some(uid => api.uidLookup("facility", uid).entity_id === id)) include(reward, node.anchor, "facility_reward", id, {origin: reward.origin, field: "seeAlsoFacility"});
        }
      }
      if (node.existing?.derivation) for (const [field, part] of Object.entries({base_item: node.existing.derivation.base_item, template: node.existing.derivation.template})) target(part.target, node.anchor, `generated_item_${field}`, id, {origins: part.origins});
    }
  }
  drain();
  return {bookId, selected, links, anchors, records: own, include, target, drain};
}
