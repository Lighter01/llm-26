import {canonicalJson, copyJson} from "../common/book_schema.mjs";
import {AssemblyError, createAssemblyApi, locateEntity, resolveRemaining} from "../assembly/assembly_content.mjs";
import {auditRequiredReferences, serializeLoaderData} from "../assembly/assembly_schema.mjs";
import {planEnrichment} from "./enrichment_plan.mjs";

export const ENRICHMENT_VERSION = "0.5.0";
export const ENRICHMENT_SCHEMA_VERSION = "0.3.0";
const METADATA_PROPS = new Set(["individual", "hoard", "gems", "artObjects", "magicItems", "languageScript"]);

export async function createEnrichmentApi(upstream) {
  const api = await createAssemblyApi(upstream);
  return {...api, stripTags: text => Renderer.stripTags(text),
    async loadRecord(record, raw) {
      if (METADATA_PROPS.has(record.prop)) return {data: copyJson(raw), method: "verified_source_metadata"};
      if (record.prop === "itemType") {
        // Registered by the item loader but not cached as independent hover entities.
        await Renderer.item.pBuildList();
        const data = Renderer.item.getType(DataUtil.itemType.getUid(raw, {isRetainDefault: true}), {isIgnoreMissing: true});
        if (!data || data.source !== raw.source || data.abbreviation !== raw.abbreviation) throw new Error("Native item type registry returned no exact source/abbreviation");
        return {data: copyJson(data), method: "native_item_type_registry"};
      }
      return {data: await api.required(record.identity), method: "native_data_loader"};
    },
  };
}

/** Finish the domain graph without recursively promoting prose references. */
export function completeDomainPlan(plan, inventory, inputs, api) {
  const own = plan.records;
  function atLabel(record, label, relation = "documented_label_alias") {
    const anchors = plan.anchors.filter(anchor => anchor.defining && anchor.label === label.toLowerCase());
    if (!anchors.length) throw new Error(`No source anchor for ${record.prop} ${record.name}: ${label}`);
    const anchor = anchors.toSorted((a, b) => Math.abs((a.origin.printed_page ?? -10000) - (record.origin.printed_page ?? 0)) - Math.abs((b.origin.printed_page ?? -10000) - (record.origin.printed_page ?? 0)))[0];
    plan.include(record, anchor, relation, null, {label: anchor.raw_label, source_origin: record.origin});
  }
  for (const record of own) {
    if (plan.selected.has(record.identity?.entity_id || record.record_id)) continue;
    const aliases = {
      "XPHB:itemGroup:Gaming Set": "Gaming Set (Varies)",
      "XPHB:item:Stabling (per day)": "Stabling per day",
      "XPHB:item:Trinket": "Trinkets",
      "XPHB:language:Primordial": "Primordial*",
      "XPHB:itemType:Treasure (Coinage)": "Coins",
      "XDMG:hazard:Improvised Damage": "Improvising Damage",
    };
    const alias = aliases[`${record.source}:${record.prop}:${record.name}`];
    if (alias) atLabel(record, alias);
    if (record.prop === "individual") atLabel(record, "Random Individual Treasure", "loot_table_representation");
    if (record.prop === "hoard") atLabel(record, "Random Treasure Hoard", "loot_table_representation");
    if (record.prop === "magicItems" && record.name.startsWith("By Level - ")) atLabel(record, "Magic Item Rarities", "loot_rarity_distribution");
    if (record.prop === "action") {
      const rule = {"Don or Doff a Shield": ["item", "Shield|XPHB"], "End Concentration": ["status", "Concentration|XPHB"], "Escape a Grapple": ["variantrule", "Grappling|XPHB"], "Two-Weapon Fighting": ["itemProperty", "L|XPHB"]}[record.name];
      if (rule) {
        const parent = plan.selected.get(api.uidLookup(...rule).entity_id);
        if (!parent) throw new Error(`Missing containing rule for action: ${record.name}`);
        plan.include(record, parent.anchor, "action_rule_representation", parent.entity_id, {origin: record.origin, rule: {prop: rule[0], uid: rule[1]}});
      } else if (record.name === "Improvising an Action") {
        const entries = inputs.rawRecords.get(record.record_id).entries;
        const sentence = entries[0].slice(entries[0].indexOf("Many class features"));
        const anchor = plan.anchors.find(anchor => typeof anchor.raw_label === "string" && anchor.raw_label.includes(sentence));
        if (!anchor) throw new Error("Improvising action has no matching source paragraph");
        plan.include(record, anchor, "equivalent_source_paragraph", null, {matched_text: sentence});
      }
    }
  }
  plan.drain();
  // Some rules provide alternate structured views (e.g. weapon from a class ability).
  for (let pass = 0; pass <= own.length; pass++) {
    const before = plan.selected.size;
    for (const node of [...plan.selected.values()]) for (const record of node.records) {
      const raw = inputs.rawRecords.get(record.record_id);
      for (const edge of inputs.dependencies.filter(edge => edge.from_record_id === record.record_id && edge.relation === "text_reference" && edge.target?.source.toUpperCase() === plan.bookId)) {
        const isRequiredCreature = edge.target.prop === "monster" && ["item", "itemGroup", "card", "monsterFluff", "monster"].includes(record.prop);
        const isFeatureItem = edge.target.prop === "item" && ["classFeature", "subclassFeature"].includes(record.prop);
        if ((isRequiredCreature || isFeatureItem) && inventory.byEntity.has(edge.target.entity_id)) plan.target(edge.target, node.anchor, isRequiredCreature ? "local_rule_statblock" : "feature_item", node.entity_id, {file: edge.file, json_pointer: edge.json_pointer, raw: edge.raw, span: edge.span});
      }
      if (record.prop === "monsterFluff") {
        function named(node) {
          if (!node || typeof node !== "object") return;
          if (node.name) for (const item of own.filter(row => row.prop === "item" && row.name === node.name)) plan.include(item, plan.selected.get(record.identity.entity_id).anchor, "named_monster_equipment", record.identity.entity_id, {origin: record.origin, name: node.name});
          for (const child of Object.values(node)) named(child);
        }
        named(raw.entries);
      }
    }
    for (const record of own) {
      if (plan.selected.has(record.identity?.entity_id || record.record_id)) continue;
      const raw = inputs.rawRecords.get(record.record_id);
      if (record.prop === "language") for (const text of raw.typicalSpeakers || []) for (const tag of api.tags(text)) {
        const speaker = tag.target && plan.selected.get(tag.target.entity_id);
        if (speaker) plan.include(record, speaker.anchor, "monster_language_metadata", speaker.entity_id, {origin: record.origin, field: "typicalSpeakers", tag: tag.raw});
      }
      if (["item", "baseitem"].includes(record.prop) && raw.packContents?.length && !raw._copy) {
        const members = raw.packContents.filter(entry => entry.item).map(entry => api.uidLookup("item", entry.item));
        const parent = members.length && members.every(member => plan.selected.has(member.entity_id)) && plan.selected.get(members[0].entity_id);
        if (parent) plan.include(record, parent.anchor, "explicit_packaging_variant", parent.entity_id, {origin: record.origin, field: "packContents", members});
      }
      if (record.prop === "itemGroup" && raw.items?.length) {
        const members = raw.items.map(uid => api.uidLookup("item", uid));
        const parent = members.every(member => plan.selected.has(member.entity_id)) && plan.selected.get(members[0].entity_id);
        if (parent) plan.include(record, parent.anchor, "group_of_placed_items", parent.entity_id, {origin: record.origin, field: "items", members});
      }
      if (record.prop === "deck" && raw.cards?.length) {
        const cardUid = card => typeof card === "string" ? card : card.uid;
        const copiedParent = raw._copy && api.lookup("deck", raw._copy).entity_id;
        const placed = [...plan.selected.values()].find(node => node.records.some(row => row.prop === "deck" && row.source === record.source && (copiedParent === node.entity_id || row.origin.printed_page === record.origin.printed_page) && raw.cards.every(card => inputs.rawRecords.get(row.record_id).cards.map(cardUid).includes(cardUid(card)))));
        if (placed) plan.include(record, placed.anchor, "explicit_deck_subset", placed.entity_id, {origin: record.origin, field: "cards", cards: raw.cards});
      }
      if (record.prop === "monster") {
        const fluffTarget = api.lookup("monsterFluff", raw);
        const fluffRecord = inventory.byEntity.get(fluffTarget.entity_id)?.find(row => row.role === "canonical_source");
        const fluff = fluffRecord && inputs.rawRecords.get(fluffRecord.record_id);
        const parent = fluff?._copy && plan.selected.get(api.lookup("monsterFluff", fluff._copy).entity_id);
        if (parent && parent.anchor.origin.printed_page === raw.page) plan.include(record, parent.anchor, "monster_in_materialized_fluff_group", parent.entity_id, {origin: record.origin, fluff_origin: fluffRecord.origin, copy: fluff._copy});
      }
      if (record.prop === "item" && record.source === "XMM") {
        const parent = [...plan.selected.values()].find(node => node.records.some(row => ["monster", "monsterFluff"].includes(row.prop) && (row.origin.printed_page === raw.page || node.anchor.origin.printed_page === raw.page) && JSON.stringify(inputs.rawRecords.get(row.record_id)).toLowerCase().includes(raw.name.toLowerCase())));
        if (parent) plan.include(record, parent.anchor, "monster_bound_equipment", parent.entity_id, {origin: record.origin, matched_name: raw.name});
      }
    }
    plan.drain();
    if (plan.selected.size === before) break;
  }
  return plan;
}

export async function enrichBook(assembled, inventory, inputs, api) {
  const document = copyJson(assembled);
  const plan = completeDomainPlan(planEnrichment(document, inventory, inputs, api), inventory, inputs, api);
  const entities = [];
  const omissions = [];
  for (const node of plan.selected.values()) {
    const record = node.records[0];
    const sourceRecords = node.records.map(record => ({record_id: record.record_id, prop: record.prop, origin: copyJson(record.origin), representation: "source_recipe", raw: copyJson(inputs.rawRecords.get(record.record_id))}));
    const common = {entity_id: node.entity_id, prop: record?.prop || node.existing.lookup.prop,
      canonical_placement: {anchor: copyJson(node.anchor), relation: node.relation, parent_entity_id: node.from_entity_id}, source_records: sourceRecords};
    try {
      if (node.existing) {
        entities.push({...common, representation: "book_insertion", occurrence_id: node.existing.occurrence_id, data_origin: copyJson(node.existing.entity_origin)});
        continue;
      }
      if (node.records.length !== 1) throw new Error("Ambiguous domain source records");
      const raw = inputs.rawRecords.get(record.record_id);
      const loaded = await api.loadRecord(record, raw);
      if (!loaded.data) throw new Error("Native loader returned no required domain component");
      let data = serializeLoaderData(loaded.data, {sourceRecords: node.records, onOmission: omission => omissions.push({book: document.book.id, entity_id: node.entity_id, ...omission})});
      data = serializeLoaderData(await resolveRemaining(data, record.prop, api), {sourceRecords: node.records});
      if (record.identity && api.lookup(record.prop, data).entity_id !== record.identity.entity_id) throw new Error("Domain loader identity/source mismatch");
      if (auditRequiredReferences(data).unresolved.length) throw new Error("Unresolved domain references");
      const located = loaded.method === "verified_source_metadata" || loaded.method === "native_item_type_registry"
        ? {entityOrigin: copyJson(record.origin), derivation: null}
        : await locateEntity(data, record.identity, inventory, api, document.upstream.checkout_sha);
      entities.push({...common, representation: "domain_component", loading_method: loaded.method, data_origin: located.entityOrigin, data, derivation: located.derivation});
    } catch (error) {
      throw new AssemblyError("DOMAIN_RESOLUTION_FAILED", error.message, {book: document.book.id, chapter: node.anchor.chapter_index, occurrence_path: node.anchor.origin.json_pointer, entity_id: node.entity_id, relation: node.relation, origin: record?.origin || null});
    }
  }
  document.artifact_kind = "enriched_book";
  document.stage = 5;
  document.schema_version = ENRICHMENT_SCHEMA_VERSION;
  document.scope.domain_enrichment = true;
  document.scope.book_complete = false; // Final schema/manifest acceptance belongs to stage 6.
  document.domain = {entities, relationships: plan.links};
  return {document, plan, omissions};
}

/** A resolved fluff retains the native copy/mod result; export can suppress shared blocks. */
export function annotateSharedFluff(document) {
  const byId = new Map(document.domain.entities.map(entity => [entity.entity_id, entity]));
  const insertionData = new Map();
  function visit(node) {
    if (!node || typeof node !== "object") return;
    if (node.kind === "embedded_entity") { insertionData.set(node.occurrence_id, node.data); return; }
    for (const child of Object.values(node)) visit(child);
  }
  for (const chapter of document.chapters) visit(chapter.content);
  const data = entity => entity.data || insertionData.get(entity.occurrence_id);
  const annotated = new Set();
  for (const edge of document.domain.relationships.filter(edge => edge.relation === "shared_fluff_parent")) {
    const child = byId.get(edge.from_entity_id);
    const parent = byId.get(edge.to_entity_id);
    if (!child || !parent) throw new Error("Shared fluff link has no materialized endpoints");
    if (!annotated.has(child.entity_id)) { child.shared_content = []; annotated.add(child.entity_id); }
    for (const field of ["entries", "images"]) for (const [i, block] of (data(child)[field] || []).entries()) {
      const shared = (data(parent)[field] || []).findIndex(value => canonicalJson(value) === canonicalJson(block));
      if (shared >= 0) child.shared_content.push({path: `/${field}/${i}`, parent_entity_id: parent.entity_id, parent_path: `/${field}/${shared}`});
    }
  }
}
