import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {promisify} from "node:util";
import Ajv2020 from "../../../../tools/ingestion/node_modules/ajv/dist/2020.js";

const exec = promisify(execFile);
const CORE = ["XPHB", "XDMG", "XMM"];
const token = key => String(key).replace(/~/g, "~0").replace(/\//g, "~1");
function at(value, pointer) {
  for (const key of pointer.split("/").slice(1).map(key => key.replace(/~1/g, "/").replace(/~0/g, "~"))) {
    assert.ok(value && Object.hasOwn(value, key), `Missing source position: ${pointer}`);
    value = value[key];
  }
  return value;
}
function walk(node, action, pointer = "") {
  action(node, pointer);
  if (node && typeof node === "object") for (const [key, value] of Object.entries(node)) walk(value, action, `${pointer}/${token(key)}`);
}
function insertions(node, result = []) {
  if (node?.kind === "embedded_entity") { result.push(node); return result; }
  if (node && typeof node === "object") for (const child of Object.values(node)) insertions(child, result);
  return result;
}
function restore(node) {
  if (node?.kind === "embedded_entity") return node.original_reference;
  if (Array.isArray(node)) return node.map(restore);
  if (node && typeof node === "object") return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, restore(value)]));
  return node;
}
function noRequired(node, recipe = false) {
  if (typeof node === "string") { if (!recipe) assert.ok(!node.includes("{#"), "Active structural string reference"); return; }
  if (!node || typeof node !== "object") return;
  if (!recipe) {
    assert.notEqual(node.type, "statblock");
    assert.ok(!/^ref[A-Z]/.test(node.type || ""));
    assert.ok(!Object.hasOwn(node, "_copy"));
    if (node.type === "statblockInline") assert.ok(node.statblockData);
  }
  for (const [key, value] of Object.entries(node)) noRequired(value, recipe || ["_versions", "entriesTemplate", "_mod"].includes(key));
}

/** Independent oracle: expected records come from tracked source files, not adapter counters. */
export async function corpusRegressions(t, {directory, upstream, diagnostics}) {
  const jsonCache = new Map();
  async function raw(file) {
    if (!jsonCache.has(file)) jsonCache.set(file, JSON.parse((await readFile(path.join(upstream, file), "utf8")).replace(/^\uFEFF/, "")));
    return jsonCache.get(file);
  }
  const books = new Map();
  const wrappers = new Map();
  const entities = new Map();
  const payload = new Map();
  for (const id of CORE) {
    const book = JSON.parse(await readFile(path.join(directory, `${id.toLowerCase()}.resolved.json`), "utf8"));
    const occurrences = book.chapters.flatMap(chapter => insertions(chapter.content));
    const byOccurrence = new Map(occurrences.map(value => [value.occurrence_id, value]));
    books.set(id, book); wrappers.set(id, occurrences);
    entities.set(id, new Map(book.domain.entities.map(value => [value.entity_id, value])));
    payload.set(id, new Map(book.domain.entities.map(value => [value.entity_id, value.representation === "book_insertion" ? byOccurrence.get(value.occurrence_id)?.data : value.data])));
  }
  function find(book, prop, name, source = book, context = {}) {
    const matches = [...entities.get(book).values()].filter(entity => {
      const data = payload.get(book).get(entity.entity_id);
      return entity.prop === prop && data?.name === name && data.source === source && Object.entries(context).every(([key, value]) => data[key] === value);
    });
    assert.equal(matches.length, 1, `${book}: no unique ${prop} ${name}|${source}`);
    return matches[0];
  }
  const data = (book, entity) => payload.get(book).get(entity.entity_id);
  const physical = async entity => at(await raw(entity.source_records[0].origin.file), entity.source_records[0].origin.json_pointer);
  const classFiles = [...new Set(Object.values(await raw("data/class/index.json")))];
  const classes = (await Promise.all(classFiles.map(file => raw(`data/class/${file}`)))).flatMap(file => file.class || []).filter(value => value.source === "XPHB");
  const subclasses = (await Promise.all(classFiles.map(file => raw(`data/class/${file}`)))).flatMap(file => file.subclass || []).filter(value => value.source === "XPHB");

  await t.test("R01: all source classes/subclasses, tables, equipment and class/level identities", async () => {
    assert.equal([...entities.get("XPHB").values()].filter(entity => entity.prop === "class").length, classes.length);
    for (const cls of classes) {
      const entity = find("XPHB", "class", cls.name);
      for (const field of ["classTableGroups", "hd", "proficiency", "startingProficiencies", "startingEquipment", "multiclassing"]) assert.deepEqual(data("XPHB", entity)[field], cls[field]);
      const expected = subclasses.filter(subclass => subclass.className === cls.name && subclass.classSource === cls.source);
      const edges = books.get("XPHB").domain.relationships.filter(edge => edge.from_entity_id === entity.entity_id && edge.relation === "subclass");
      assert.equal(edges.length, expected.length);
      for (const subclass of expected) {
        const sub = find("XPHB", "subclass", subclass.name, "XPHB", {className: cls.name, classSource: "XPHB"});
        assert.ok(edges.some(edge => edge.to_entity_id === sub.entity_id));
        for (const edge of books.get("XPHB").domain.relationships.filter(edge => edge.from_entity_id === sub.entity_id && edge.relation === "subclassFeatures")) {
          const feature = payload.get("XPHB").get(edge.to_entity_id);
          assert.equal(feature.className, cls.name); assert.equal(feature.classSource, cls.source);
          assert.equal(feature.subclassShortName, subclass.shortName); assert.equal(feature.subclassSource, subclass.source);
          assert.ok(Number.isSafeInteger(feature.level) && feature.entries.length);
        }
      }
    }
  });
  await t.test("R02: Barbarian/Berserker/Frenzy are full features, including level and progression", () => {
    const barbarian = find("XPHB", "class", "Barbarian");
    const berserker = find("XPHB", "subclass", "Path of the Berserker", "XPHB", {className: "Barbarian", classSource: "XPHB"});
    const frenzy = find("XPHB", "subclassFeature", "Frenzy", "XPHB", {className: "Barbarian", subclassShortName: "Berserker", level: 3});
    assert.ok(data("XPHB", barbarian).classTableGroups[0].rows.length);
    assert.ok(data("XPHB", berserker).subclassFeatures.flat().some(feature => JSON.stringify(feature).includes("Frenzy")));
    assert.ok(data("XPHB", frenzy).entries.some(entry => typeof entry === "string" && entry.includes("Reckless Attack")));
  });
  await t.test("R03: complete optionalfeature prerequisites and rule fields survive for every source option", async () => {
    for (const option of (await raw("data/optionalfeatures.json")).optionalfeature.filter(value => value.source === "XPHB")) {
      const entity = find("XPHB", "optionalfeature", option.name);
      for (const field of ["prerequisite", "featureType", "repeatable", "cost", "additionalSpells"]) assert.deepEqual(data("XPHB", entity)[field], option[field]);
    }
    assert.ok(data("XPHB", find("XPHB", "optionalfeature", "Agonizing Blast")).prerequisite[0].level.class.name === "Warlock");
  });
  await t.test("R04: all spell/class summons have one placement, preserved parameters and correct parents", async () => {
    const expected = (await raw("data/bestiary/bestiary-xphb.json")).monster.filter(value => value.summonedBySpell || value.summonedByClass);
    for (const creature of expected) {
      const entity = find("XPHB", "monster", creature.name);
      const edges = books.get("XPHB").domain.relationships.filter(edge => edge.to_entity_id === entity.entity_id && ["summoned_by_spell", "summoned_by_class"].includes(edge.relation));
      assert.equal(edges.length, 1);
      const parent = payload.get("XPHB").get(edges[0].from_entity_id);
      const uid = creature.summonedBySpell || creature.summonedByClass;
      assert.equal(parent.name.toLowerCase(), uid.split("|")[0].toLowerCase());
      assert.equal(parent.source.toLowerCase(), uid.split("|")[1].toLowerCase());
      for (const field of ["ac", "hp", "speed", "action", "trait", "summonedBySpell", "summonedByClass", "summonedBySpellLevel", "pbNote"]) assert.deepEqual(data("XPHB", entity)[field], creature[field]);
    }
    assert.match(JSON.stringify(data("XPHB", find("XPHB", "monster", "Aberrant Spirit")).action), /summonSpellLevel/);
  });
  await t.test("R05: Aeromancer native copy/mod retains individual and group lore with shared block links", async () => {
    const individual = find("XMM", "monsterFluff", "Aarakocra Aeromancer");
    const group = find("XMM", "monsterFluff", "Aarakocra");
    const source = await physical(individual);
    assert.equal(source._copy.name, "Aarakocra");
    assert.match(JSON.stringify(data("XMM", individual).entries), /control magical winds/);
    assert.match(JSON.stringify(data("XMM", individual).entries), /Aarakocra are birdlike folk/);
    for (const shared of individual.shared_content) {
      assert.equal(shared.parent_entity_id, group.entity_id);
      assert.deepEqual(at(data("XMM", individual), shared.path), at(data("XMM", group), shared.parent_path));
    }
    assert.ok(individual.shared_content.length);
    assert.ok(!data("XMM", individual)._copy);
  });
  for (const [code, name] of [["R06", "Aboleth"], ["R07", "Adult Black Dragon"]]) await t.test(`${code}: ${name} full mechanics, legendary/regional data and source pages`, async () => {
    const entity = find("XMM", "monster", name);
    const original = await physical(entity);
    for (const field of ["ac", "hp", "action", "bonus", "reaction", "legendary", "spellcasting", "resist", "immune", "conditionImmune", "source", "page"]) assert.deepEqual(data("XMM", entity)[field], original[field]);
    const edge = books.get("XMM").domain.relationships.find(edge => edge.from_entity_id === entity.entity_id && edge.relation === "legendary_group");
    const group = entities.get("XMM").get(edge.to_entity_id);
    const rawGroup = await physical(group);
    for (const field of ["lairActions", "regionalEffects", "mythicEncounter"]) assert.deepEqual(data("XMM", group)[field], rawGroup[field]);
    assert.equal(entity.data_origin.printed_page, original.page);
    assert.ok(data("XMM", group).regionalEffects.length);
  });
  await t.test("R08: DMG item groups/variants, attunement, charges, descriptions and generated evidence", async () => {
    for (const name of ["Bag of Holding", "Bag of Tricks, Gray", "Enspelled Staff (Level 6)", "+1 Rod of the Pact Keeper", "Black Dragon Scale Mail"]) {
      const entity = find("XDMG", "item", name);
      const original = await physical(entity);
      const resolved = data("XDMG", entity);
      for (const field of ["rarity", "reqAttune", "charges", "recharge", "bonusAc", "bonusWeapon", "baseItem", "resist", "detail1", "ac", "weight", "page", "source"]) assert.deepEqual(resolved[field], original[field]);
      if (!original.entries.some(entry => typeof entry === "string" && entry.includes("{#"))) assert.deepEqual(resolved.entries, original.entries);
      else {
        // This entry is a native template reference: equality with the unresolved
        // recipe would be a regression. Check its source template and parameters.
        const template = (await raw("data/items-base.json")).itemEntry.find(value => value.name === "Dragon Scale Mail" && value.source === "XDMG");
        assert.deepEqual(original.entries, ["{#itemEntry Dragon Scale Mail|XDMG}"]);
        assert.equal(resolved.entries.length, template.entriesTemplate.length);
        assert.equal(resolved.entries[0], template.entriesTemplate[0]);
        assert.ok(resolved.entries.join(" ").toLowerCase().includes(`${original.resist[0]} damage`));
        assert.ok(resolved.entries.join(" ").includes(`${original.detail1} dragon`));
        assert.ok(!JSON.stringify(resolved.entries).includes("{#"));
      }
    }
    for (const wrapper of wrappers.get("XDMG").filter(value => value.entity_origin.lookup_source === "generated_item")) {
      assert.equal(wrapper.entity_origin.file, null);
      assert.equal(wrapper.entity_origin.json_pointer, null);
      assert.ok(!Object.hasOwn(wrapper.data, "variants"));
      for (const field of ["base_item", "template"]) assert.ok(entities.get("XDMG").has(wrapper.derivation[field].target.entity_id));
    }
  });
  await t.test("R09: every chapter, appendix, table and image matches its original source position", async () => {
    const catalog = (await raw("data/books.json")).book;
    for (const id of CORE) {
      const book = books.get(id);
      const original = (await raw(`data/book/book-${id.toLowerCase()}.json`)).bookData.find(value => value.id === id);
      assert.deepEqual(book.chapters.map(chapter => chapter.title), original.data.map(chapter => chapter.name));
      assert.equal(book.chapters.length, catalog.find(value => value.id === id).contents.length);
      for (const [i, chapter] of original.data.entries()) {
        const restored = restore(book.chapters[i].content);
        assert.deepEqual(restored, chapter);
        walk(chapter, (node, pointer) => {
          if (node?.type === "image" || ["table", "tableGroup"].includes(node?.type)) assert.deepEqual(at(restored, pointer), node);
        });
      }
    }
    assert.ok(books.get("XDMG").chapters.some(chapter => chapter.title === "Appendix B: Maps"));
    assert.ok(books.get("XDMG").chapters.some(chapter => chapter.title === "Appendix C: Tracking Sheets"));
  });
  await t.test("R10: no active mandatory references remain; text tags and cross-book attribution survive", () => {
    for (const id of CORE) for (const value of payload.get(id).values()) noRequired(value);
    const ape = wrappers.get("XPHB").find(value => value.data.name === "Ape");
    assert.equal(ape.data.source, "XMM"); assert.equal(ape.placement.book_id, "XPHB");
    assert.notEqual(ape.entity_origin.printed_page, ape.placement.origin.printed_page);
    assert.match(JSON.stringify(books.get("XPHB").chapters), /\{@spell /);
  });
  await t.test("S01: independent Ajv Draft 2020-12 validation of every final book and embedded wrapper", async () => {
    const schema = JSON.parse(await readFile(new URL("../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolved-book.schema.json", import.meta.url), "utf8"));
    // required in an anyOf branch legitimately refers to properties declared on its parent.
    const ajv = new Ajv2020({strict: true, strictRequired: false, allErrors: true});
    const validate = ajv.compile(schema);
    const validateWrapper = ajv.compile({$ref: `${schema.$id}#/$defs/wrapper`});
    for (const id of CORE) {
      assert.ok(validate(books.get(id)), JSON.stringify(validate.errors));
      for (const wrapper of wrappers.get(id)) assert.ok(validateWrapper(wrapper), JSON.stringify(validateWrapper.errors));
    }
    const invalid = structuredClone(books.get("XPHB")); invalid.scope.book_complete = false;
    assert.equal(validate(invalid), false);
    assert.ok(validate.errors.some(error => error.instancePath === "/scope/book_complete"));
  });
  await t.test("S02: every tracked core source record is accounted for, with full raw material or a narrow justified exclusion", async () => {
    const audit = (await readFile(path.join(diagnostics, "placement-audit.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
    const decisions = new Map(audit.map(row => [row.record_id, row]));
    const tracked = (await exec("git", ["-C", upstream, "ls-files", "-z", "--", "data"])).stdout.split("\0").filter(file => file.endsWith(".json"));
    let count = 0;
    for (const file of tracked) for (const [prop, array] of Object.entries(JSON.parse((await readFile(path.join(upstream, file), "utf8")).replace(/^\uFEFF/, "")))) {
      if (!Array.isArray(array)) continue;
      for (const [i, value] of array.entries()) {
        const source = value?.source ?? (prop === "magicvariant" ? value?.inherits?.source : null);
        if (typeof source !== "string" || !CORE.includes(source.toUpperCase())) continue;
        count++;
        const pointer = `/${token(prop)}/${i}`;
        const recordId = `record:${encodeURIComponent(file)}:${encodeURIComponent(pointer)}`;
        const decision = decisions.get(recordId);
        assert.ok(decision, `Unaccounted source record ${file}#${pointer}`);
        assert.notEqual(decision.status, "unreviewed_critical"); assert.ok(decision.reason);
        if (decision.status === "materialized") {
          const entity = entities.get(source.toUpperCase()).get(decision.evidence.entity_id);
          const record = entity.source_records.find(record => record.record_id === recordId);
          assert.deepEqual(record.raw, value);
          assert.equal(record.origin.file, file); assert.equal(record.origin.json_pointer, pointer);
        } else if (!file.startsWith("data/generated/") && !/(?:^|\/)foundry(?:[-./])/.test(file) && !file.startsWith("data/book/") && file !== "data/books.json") {
          assert.ok(["excluded_renderer_taxonomy", "excluded_web_font_asset"].includes(decision.status));
          assert.ok(!value.entries && !value.entriesTemplate);
          assert.deepEqual(decision.evidence.raw, value);
        }
      }
    }
    assert.equal(decisions.size, count); assert.equal(audit.length, count);
  });
}
