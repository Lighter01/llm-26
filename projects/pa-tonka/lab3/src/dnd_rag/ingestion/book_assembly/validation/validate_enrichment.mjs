import assert from "node:assert/strict";
import {atPointer, canonicalJson, copyJson, occurrenceId, origin, pageContext, restoreReferences, sha256} from "../common/book_schema.mjs";
import {BOOK_IDS, walkJson} from "../common/source_scan.mjs";
import {collectEmbedded} from "../common/tree.mjs";
import {auditRequiredReferences, ASSEMBLY_SCHEMA_VERSION} from "../assembly/assembly_schema.mjs";
import {validateAssemblyBook} from "./validate_assembly.mjs";
import {ENRICHMENT_SCHEMA_VERSION} from "../enrichment/enrichment_content.mjs";

function dataFor(entity, wrappers) {
  return entity.representation === "book_insertion" ? wrappers.get(entity.occurrence_id)?.data : entity.data;
}

// generate-variantrules-data.js removes source entry IDs when extracting a rule.
function generatedRuleEntries(value) {
  if (Array.isArray(value)) return value.map(generatedRuleEntries);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => key !== "id").map(([key, child]) => [key, generatedRuleEntries(child)]));
}

// The pinned upstream generator copies complete tables, changes navigation metadata,
// removes data.genTables controls, and optionally promotes their reprintedAs value.
// See js/generate-tables-data/generate-tables-data-{utils,models}.js:
// _doSearch, _getStacks_mutCleanTableOrGroup, _getStacks_mutPostProcessTables,
// _getStacks_mutCleanGenTablesData, and _getStacks_mutDataAddReprintedAs.
// All other fields (including caption, footnotes, colLabelRows, styles, and unknown
// future content) must match; rows/colLabels alone do not prove equivalence.
function generatedTableContent(table) {
  const result = copyJson(table);
  if (!result.reprintedAs && result.data?.genTables?.reprintedAs) result.reprintedAs = copyJson(result.data.genTables.reprintedAs);
  function cleanControls(value) {
    if (!value || typeof value !== "object") return;
    if (value.data && typeof value.data === "object" && !Array.isArray(value.data)) {
      delete value.data.genTables;
      if (!Object.keys(value.data).length) delete value.data;
    }
    for (const child of Object.values(value)) cleanControls(child);
  }
  cleanControls(result);
  for (const field of ["type", "name", "source", "page", "chapter", "parentEntity", "path", "section", "sectionIndex", "srd", "srd52", "basicRules", "basicRules2024"]) delete result[field];
  if (Array.isArray(result.tables)) result.tables = result.tables.map(generatedTableContent);
  return result;
}

/** Every source-defined record receives a decision, with no generic canonical exclusion. */
export function auditPlacement(document, inventory, inputs) {
  const represented = new Map();
  for (const entity of document.domain.entities) for (const record of entity.source_records) represented.set(record.record_id, entity.entity_id);
  const tableShapes = new Set();
  const tableGroupShapes = new Set();
  const fauxGroups = new Map();
  const entryShapes = new Set();
  function index(node) {
    if (!node || typeof node !== "object" || Array.isArray(node)) return;
    if (node.rows) tableShapes.add(sha256(canonicalJson(generatedTableContent(node))));
    if (Array.isArray(node.tables)) tableGroupShapes.add(sha256(canonicalJson(generatedTableContent(node))));
    const group = node.data?.genTables;
    if (node.rows && group?.fauxGroupName && group?.fauxGroupSource) {
      const key = canonicalJson([group.fauxGroupSource, group.fauxGroupName]);
      if (!fauxGroups.has(key)) fauxGroups.set(key, []);
      fauxGroups.get(key).push(generatedTableContent(node));
    }
    if (node.entries) entryShapes.add(sha256(canonicalJson(generatedRuleEntries(node.entries))));
  }
  for (const chapter of document.chapters) {
    walkJson(restoreReferences(chapter.content), index);
    for (const wrapper of collectEmbedded(chapter.content)) walkJson(wrapper.data, index);
  }
  for (const entity of document.domain.entities) if (entity.data) walkJson(entity.data, index);
  const decisions = [];
  for (const record of inventory.byRecord.values()) {
    if (record.source.toUpperCase() !== document.book.id) continue;
    const raw = inputs.rawRecords.get(record.record_id);
    let status;
    let reason;
    let evidence = null;
    if (represented.has(record.record_id)) {
      status = "materialized"; reason = "Full source recipe and resolved payload are present at a canonical book anchor.";
      evidence = {entity_id: represented.get(record.record_id)};
    } else if (record.role === "foundry_overlay") {
      status = "excluded_tool_integration"; reason = "Foundry automation overlay is a separate platform representation; canonical tabletop content is selected independently.";
    } else if (["book_tree", "book_catalog"].includes(record.role)) {
      status = "represented_book_structure"; reason = "Book/catalog metadata and all source chapters are preserved and independently validated.";
    } else if (record.role === "generated_projection") {
      let matches;
      if (record.prop === "book") matches = raw.id === document.book.id;
      else if (record.prop === "table") matches = tableShapes.has(sha256(canonicalJson(generatedTableContent(raw))));
      else if (record.prop === "tableGroup") {
        const content = generatedTableContent(raw);
        matches = tableGroupShapes.has(sha256(canonicalJson(content)));
        // getStacks constructs faux groups only from tables with explicit
        // matching fauxGroupSource/fauxGroupName controls, in source order.
        // Requiring that evidence also rejects dropped/reordered components.
        const faux = fauxGroups.get(canonicalJson([raw.source, raw.name]));
        if (!matches && faux?.length) matches = canonicalJson(content) === canonicalJson({tables: faux});
      }
      else if (record.prop === "variantrule") matches = raw.entries && entryShapes.has(sha256(canonicalJson(raw.entries)));
      if (matches) { status = "represented_generated_projection"; reason = "Generated navigation/rule/table projection matches materialized source structure; no second presentation is added."; }
    } else if (record.prop === "itemType" && record.role === "canonical_source" && !raw.entries && !raw.entriesTemplate && Object.keys(raw).every(key => ["name", "abbreviation", "source", "page", "basicRules2024", "srd52"].includes(key))) {
      status = "excluded_renderer_taxonomy"; reason = "Unused item category label has no description or rules; source metadata is retained in the audit.";
      evidence = {raw: copyJson(raw)};
    } else if (record.prop === "languageScript" && record.role === "canonical_source" && raw.fonts && Object.keys(raw).every(key => ["name", "source", "fonts"].includes(key))) {
      status = "excluded_web_font_asset"; reason = "Website font-resource registry has no book rules or narrative; it is not a book image or text insertion.";
      evidence = {raw: copyJson(raw)};
    }
    decisions.push({record_id: record.record_id, prop: record.prop, name: record.name, source: record.source, role: record.role, inventory_classification: record.classification, origin: copyJson(record.origin), raw_sha256: record.raw_sha256, status: status || "unreviewed_critical", reason: reason || "No demonstrated placement or supported exclusion rule.", evidence});
  }
  return decisions;
}

/** Independent shape, source, component, level, placement and shared-content checks. */
export async function validateEnrichment(document, inventory, inputs, api) {
  assert.equal(document.stage, 5);
  assert.equal(document.artifact_kind, "enriched_book");
  assert.equal(document.schema_version, ENRICHMENT_SCHEMA_VERSION);
  assert.equal(document.scope.domain_enrichment, true);
  assert.equal(document.scope.book_complete, false);
  const source = await inventory.readSource(document.book.source_file);
  const book = source.bookData.find(book => book.id === document.book.id);
  const base = {...document, stage: 4, artifact_kind: "assembled_book", schema_version: ASSEMBLY_SCHEMA_VERSION, scope: {...document.scope, domain_enrichment: false}};
  const assembly = validateAssemblyBook(base, {bookId: document.book.id, book, file: document.book.source_file, bookIndex: source.bookData.indexOf(book)}, inventory);
  const wrappers = new Map(document.chapters.flatMap(chapter => collectEmbedded(chapter.content)).map(wrapper => [wrapper.occurrence_id, wrapper]));
  const byId = new Map(document.domain.entities.map(entity => [entity.entity_id, entity]));
  assert.equal(byId.size, document.domain.entities.length, "Duplicate canonical entity");
  const relations = document.domain.relationships;
  const stats = {assembly, entities: byId.size, domain_components: 0, source_records: 0, relationships: relations.length, unknown_component_pages: 0, props: {}, entity_sources: {}, ordinary_text_reference_scopes: {}, subclass_counts: {}, preserved_source_tables: assembly.preserved_source_tables, preserved_source_images: assembly.preserved_source_images};
  for (const entity of byId.values()) {
    const data = dataFor(entity, wrappers);
    assert.ok(data, `No self-contained payload for ${entity.entity_id}`);
    assert.deepEqual(auditRequiredReferences(data).unresolved, []);
    const anchor = entity.canonical_placement.anchor;
    assert.equal(anchor.book_id, document.book.id);
    assert.equal(anchor.origin.file, document.book.source_file);
    assert.equal(anchor.origin.upstream_commit, document.upstream.checkout_sha);
    const sourceTree = await inventory.readSource(anchor.origin.file);
    let cursor = sourceTree;
    let pointer = "";
    let page = pageContext(cursor, pointer);
    for (const token of anchor.origin.json_pointer.split("/").slice(1)) {
      pointer += `/${token}`;
      cursor = atPointer(sourceTree, pointer);
      assert.notEqual(cursor, undefined, "Canonical anchor is not a real source position");
      page = pageContext(cursor, pointer, page);
    }
    assert.deepEqual(anchor.origin, origin({file: anchor.origin.file, pointer, source: document.book.id, commit: document.upstream.checkout_sha, page}));
    assert.equal(anchor.occurrence_id, occurrenceId(document.book.id, anchor.chapter_index, pointer));
    assert.ok(pointer.startsWith(`${document.chapters[anchor.chapter_index].origin.json_pointer}/`) || pointer === document.chapters[anchor.chapter_index].origin.json_pointer);
    if (entity.canonical_placement.parent_entity_id) assert.ok(byId.has(entity.canonical_placement.parent_entity_id), "Missing canonical placement parent");
    if (entity.representation === "domain_component") {
      stats.domain_components++;
      stats.unknown_component_pages += entity.data_origin.printed_page == null ? 1 : 0;
      assert.equal(entity.data_origin.source, data.source);
      assert.equal(entity.data_origin.printed_page, data.page ?? null);
    }
    stats.props[entity.prop] = (stats.props[entity.prop] || 0) + 1;
    stats.entity_sources[data.source] = (stats.entity_sources[data.source] || 0) + 1;
    for (const sourceRecord of entity.source_records) {
      stats.source_records++;
      const record = inventory.byRecord.get(sourceRecord.record_id);
      assert.ok(record);
      assert.deepEqual(sourceRecord.origin, record.origin);
      assert.equal(sha256(canonicalJson(sourceRecord.raw)), record.raw_sha256, "Source recipe lost fields");
      assert.deepEqual(sourceRecord.raw, atPointer(await inventory.readSource(record.origin.file), record.origin.json_pointer));
      const raw = sourceRecord.raw;
      if (entity.representation === "domain_component") {
        assert.equal(entity.data_origin.file, record.origin.file);
        assert.equal(entity.data_origin.json_pointer, record.origin.json_pointer);
      }
      // Keep complete mechanics, including parameterized summons and monster effects.
      for (const field of ["ac", "hp", "speed", "str", "dex", "con", "int", "wis", "cha", "save", "skill", "senses", "passive", "resist", "immune", "vulnerable", "conditionImmune", "action", "bonus", "reaction", "legendary", "legendaryGroup", "trait", "regionalEffects", "lairActions", "mythicEncounter", "spellcasting", "summonedBySpell", "summonedByClass", "summonedBySpellLevel", "pbNote", "rarity", "reqAttune", "reqAttuneTags", "charges", "recharge", "rechargeAmount", "bonusAc", "bonusWeapon", "weight", "value", "containerCapacity"]) {
        if (raw[field] !== undefined) assert.deepEqual(data[field], raw[field], `Lost mechanic ${record.name}.${field}`);
      }
      if (["feat", "optionalfeature", "class", "subclass", "classFeature", "subclassFeature"].includes(record.prop)) for (const field of ["prerequisite", "repeatable", "cost", "additionalSpells", "classTableGroups", "hd", "proficiency", "startingProficiencies", "startingEquipment", "multiclassing", "featureType", "level", "className", "classSource", "subclassShortName", "subclassSource"]) {
        if (raw[field] !== undefined) assert.deepEqual(data[field], raw[field], `Lost rule field ${record.name}.${field}`);
      }
      for (const [field, prop] of [["classFeatures", "classFeature"], ["subclassFeatures", "subclassFeature"], ["cards", "card"]]) {
        if (field === "classFeatures" && record.prop !== "class") continue; // Item metadata can list external Artificer availability.
        for (const reference of raw[field] || []) {
          const uid = typeof reference === "string" ? reference : reference[prop] || reference.uid;
          const id = api.uidLookup(prop, uid).entity_id;
          assert.ok(byId.has(id), `Missing ${field} component ${uid}`);
          assert.ok(relations.some(edge => edge.from_entity_id === entity.entity_id && edge.to_entity_id === id && edge.relation === field));
          if (prop.endsWith("Feature")) {
            const feature = dataFor(byId.get(id), wrappers);
            assert.equal(feature.className, data.className || data.name);
            assert.equal(feature.classSource, data.classSource || data.source);
            assert.ok(Number.isSafeInteger(feature.level));
          }
        }
      }
      if (record.prop === "class") {
        const subclasses = [...inventory.byRecord.values()].filter(row => row.role === "canonical_source" && row.prop === "subclass" && row.source === document.book.id && inputs.rawRecords.get(row.record_id).className === data.name && inputs.rawRecords.get(row.record_id).classSource === data.source);
        for (const subclass of subclasses) assert.ok(byId.has(subclass.identity.entity_id), `Missing subclass ${subclass.name}`);
        stats.subclass_counts[data.name] = subclasses.length;
      }
      for (const edge of inputs.dependencies.filter(edge => edge.from_record_id === record.record_id)) {
        if (!edge.target || /\/(?:_versions|entriesTemplate|_mod)(?:\/|$)/.test(edge.json_pointer.slice(record.origin.json_pointer.length))) continue;
        if (["structural_reference", "structural_string_reference", "companion_fluff", "legendary_group"].includes(edge.relation)) {
          assert.ok(byId.has(edge.target.entity_id), `Missing required domain dependency: ${edge.relation}`);
          assert.ok(relations.some(link => link.from_entity_id === entity.entity_id && link.to_entity_id === edge.target.entity_id && link.relation === edge.relation));
        }
        if (["summoned_by_spell", "summoned_by_class", "parent_class"].includes(edge.relation) && byId.has(edge.target.entity_id)) {
          assert.ok(relations.some(link => link.from_entity_id === edge.target.entity_id && link.to_entity_id === entity.entity_id && link.relation === (edge.relation === "parent_class" ? "subclass" : edge.relation)));
        }
      }
    }
    const expectedShared = [];
    for (const edge of relations.filter(edge => edge.from_entity_id === entity.entity_id && edge.relation === "shared_fluff_parent")) {
      const parentData = dataFor(byId.get(edge.to_entity_id), wrappers);
      for (const field of ["entries", "images"]) for (const [i, block] of (data[field] || []).entries()) {
        const shared = (parentData[field] || []).findIndex(value => canonicalJson(value) === canonicalJson(block));
        if (shared >= 0) expectedShared.push({path: `/${field}/${i}`, parent_entity_id: edge.to_entity_id, parent_path: `/${field}/${shared}`});
      }
    }
    assert.deepEqual(entity.shared_content || [], expectedShared, "Missing/incorrect shared fluff annotations");
  }
  for (const edge of relations) {
    if (edge.from_entity_id) assert.ok(byId.has(edge.from_entity_id), "Missing relationship source");
    if (edge.relation !== "inheritance_provenance") assert.ok(byId.has(edge.to_entity_id), `Missing relationship target: ${edge.relation}`);
  }
  // Canonical placement edges must form a forest rooted in source book occurrences.
  for (const entity of byId.values()) {
    const ancestors = new Set([entity.entity_id]);
    let parent = entity.canonical_placement.parent_entity_id;
    while (parent) { assert.ok(!ancestors.has(parent), "Canonical placement cycle"); ancestors.add(parent); parent = byId.get(parent).canonical_placement.parent_entity_id; }
  }
  const audit = auditPlacement(document, inventory, inputs);
  const unresolved = audit.filter(decision => decision.status === "unreviewed_critical");
  const statuses = {};
  for (const decision of audit) statuses[decision.status] = (statuses[decision.status] || 0) + 1;
  for (const reference of inventory.references.filter(ref => ref.book_id === document.book.id && ref.kind === "entity_reference" && ref.target)) {
    const source = reference.target.source.toUpperCase();
    const scope = source === document.book.id ? "same_book" : BOOK_IDS.includes(source) ? "other_core" : "outside_core";
    stats.ordinary_text_reference_scopes[scope] = (stats.ordinary_text_reference_scopes[scope] || 0) + 1;
  }
  copyJson(document);
  return {status: unresolved.length ? "FAIL" : "PASS", ...stats, placement_statuses: statuses, unreviewed_critical: unresolved, audit};
}
