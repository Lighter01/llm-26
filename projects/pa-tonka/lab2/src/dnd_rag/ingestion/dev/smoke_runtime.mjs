import assert from "node:assert/strict";
import {readJson, walkJson} from "../book_assembly/common/source_scan.mjs";

/** Diagnostic probes only. These do not assemble or validate complete books. */
export async function smokeRuntime(root, books, classSources) {
  const checks = [];
  const warnings = [];
  const routeSamples = new Map();
  for (const book of books) {
    for (const [route, sample] of Object.entries(book.route_examples)) {
      if (!routeSamples.has(route)) routeSamples.set(route, sample);
    }
  }
  async function check(name, action) {
    try {
      checks.push({name, status: "PASS", ...await action()});
    } catch (error) {
      checks.push({name, status: "FAIL", error: error.message});
    }
  }
  async function load(prop, entity) {
    const lookup = {
      prop, source: entity.source,
      hash: UrlUtil.getHashBuilder(prop)(entity),
    };
    const result = await DataLoader.pCacheAndGet(prop, entity.source, lookup.hash, {isCopy: true, isRequired: true});
    assert.ok(result, `Missing ${prop}: ${entity.name}`);
    return {result, lookup};
  }
  async function raw(file, prop, name, source) {
    const data = await readJson(root, file);
    const index = data[prop].findIndex(e => e.name === name && e.source === source);
    assert.ok(index >= 0, `${file}: missing ${name}|${source}`);
    return {entity: data[prop][index], origin: {file, json_pointer: `/${prop}/${index}`}};
  }

  for (const [route, sample] of routeSamples) {
    await check(`preload:${route}`, async () => {
      const before = JSON.stringify(sample.reference);
      const lookup = Renderer.utils.getStatblockEntryMeta(sample.reference);
      const expanded = await Renderer.utils.preload.pGetPreloaded(sample.reference);
      assert.equal(expanded.type, "statblockInline");
      assert.ok(expanded.statblockData);
      assert.equal(expanded.statblockData.name, sample.reference.name);
      assert.equal(expanded.statblockData.source, lookup.source);
      assert.equal(JSON.stringify(sample.reference), before, "Preload mutated the original reference");
      assert.deepEqual(JSON.parse(JSON.stringify(expanded)).statblockData.name, expanded.statblockData.name);
      return {
        placement: sample, lookup,
        entity: {name: expanded.statblockData.name, source: expanded.statblockData.source, printed_page: expanded.statblockData.page ?? null, fields: Object.keys(expanded.statblockData).sort()},
      };
    });
  }

  await check("spell:local-source-equality", async () => {
    const {entity, origin} = await raw("data/spells/spells-xphb.json", "spell", "Acid Splash", "XPHB");
    const {result, lookup} = await load("spell", entity);
    for (const field of ["entries", "level", "school", "time", "range", "components", "duration", "page"]) assert.deepEqual(result[field], entity[field], field);
    return {origin, lookup, compared_fields: ["entries", "level", "school", "time", "range", "components", "duration", "page"]};
  });

  await check("classes:barbarian-and-berserker", async () => {
    const {entity, origin} = await raw("data/class/class-barbarian.json", "class", "Barbarian", "XPHB");
    const {result} = await load("class", entity);
    assert.deepEqual(result.classTableGroups, entity.classTableGroups);
    assert.deepEqual(result.startingEquipment, entity.startingEquipment);
    assert.ok(result.classFeatures.flat().every(e => e && typeof e === "object"));
    const allSubclasses = (await DataLoader.pCacheAndGetAllSite("subclass"))
      .filter(e => e.source === "XPHB" && e.classSource === "XPHB");
    assert.equal(allSubclasses.length, classSources.subclasses.length);
    const expected = classSources.subclasses.filter(e => e.class_name === "Barbarian");
    const actual = allSubclasses.filter(e => e.className === "Barbarian");
    assert.deepEqual(actual.map(e => e.name).sort(), expected.map(e => e.name).sort());
    const berserker = actual.find(e => e.name === "Path of the Berserker");
    assert.ok(berserker);
    let frenzy = false;
    walkJson(berserker.subclassFeatures, node => {
      if (node?.name === "Frenzy" && node.entries?.length) frenzy = true;
    });
    assert.ok(frenzy, "Missing resolved Frenzy");
    return {origin, class_count_in_source: classSources.classes.length, subclass_count_in_source: classSources.subclasses.length, barbarian_subclasses: actual.map(e => e.name).sort(), preload_includes_subclasses: Array.isArray(result.subclasses) || Array.isArray(result.subclass)};
  });

  await check("optionalfeature:agonizing-blast", async () => {
    const {entity, origin} = await raw("data/optionalfeatures.json", "optionalfeature", "Agonizing Blast", "XPHB");
    const {result} = await load("optionalfeature", entity);
    assert.ok(entity.prerequisite?.length);
    assert.deepEqual(result.prerequisite, entity.prerequisite);
    return {origin, prerequisite: result.prerequisite};
  });

  await check("summon:aberrant-spirit", async () => {
    const {entity, origin} = await raw("data/bestiary/bestiary-xphb.json", "monster", "Aberrant Spirit", "XPHB");
    const {result} = await load("monster", entity);
    for (const field of ["ac", "hp", "action", "summonedBySpell", "summonedBySpellLevel"]) assert.deepEqual(result[field], entity[field], field);
    const {entity: spell} = await raw("data/spells/spells-xphb.json", "spell", "Summon Aberration", "XPHB");
    assert.ok(JSON.stringify(spell.entries).includes("{@creature Aberrant Spirit|XPHB}"));
    let placedInBook = false;
    const book = await readJson(root, "data/book/book-xphb.json");
    walkJson(book, node => {
      if (node?.type === "statblock" && node.name === entity.name && node.source === entity.source) placedInBook = true;
    });
    return {origin, summoned_by_spell: result.summonedBySpell, ac: result.ac, hp: result.hp, directly_placed_in_book: placedInBook};
  });

  await check("fluff:copy-mod-aeromancer", async () => {
    const {entity, origin} = await raw("data/bestiary/fluff-bestiary-xmm.json", "monsterFluff", "Aarakocra Aeromancer", "XMM");
    assert.ok(entity._copy?._mod);
    const {result} = await load("monsterFluff", entity);
    assert.equal(result._copy, undefined);
    const text = JSON.stringify(result.entries);
    assert.ok(text.includes("control magical winds"));
    assert.ok(text.includes("Aarakocra are birdlike folk"));
    return {origin, copy_resolved: true, individual_and_group_text_present: true, image_count: result.images?.length || 0};
  });

  for (const name of ["Aboleth", "Adult Black Dragon"]) {
    await check(`monster:${name}`, async () => {
      const {entity, origin} = await raw("data/bestiary/bestiary-xmm.json", "monster", name, "XMM");
      const {result} = await load("monster", entity);
      for (const field of ["ac", "hp", "action", "legendary", "legendaryGroup", "page"]) assert.deepEqual(result[field], entity[field], field);
      const {result: group} = await load("legendaryGroup", entity.legendaryGroup);
      const originalGroup = await raw("data/bestiary/legendarygroups.json", "legendaryGroup", entity.legendaryGroup.name, entity.legendaryGroup.source);
      assert.deepEqual(group.regionalEffects, originalGroup.entity.regionalEffects);
      assert.ok(group.regionalEffects?.length);
      return {origin, legendary_group_origin: originalGroup.origin, printed_page: result.page, legendary_actions: result.legendary?.length || 0, regional_effects: group.regionalEffects.length, lair_actions: group.lairActions?.length || 0};
    });
  }

  await check("item:bag-of-holding", async () => {
    const {entity, origin} = await raw("data/items.json", "item", "Bag of Holding", "XDMG");
    const {result} = await load("item", entity);
    for (const field of ["entries", "rarity", "weight", "containerCapacity", "page"]) assert.deepEqual(result[field], entity[field], field);
    return {origin, rarity: result.rarity, printed_page: result.page};
  });

  await check("preload:missing-entity-remains-unresolved", async () => {
    const ref = {type: "statblock", tag: "spell", name: "__dnd_rag_missing_smoke_entity__", source: "XPHB"};
    const expanded = await Renderer.utils.preload.pGetPreloaded(ref);
    assert.equal(expanded.type, "statblock");
    assert.equal(expanded.statblockData, undefined);
    warnings.push({code: "PRELOAD_SILENT_MISS", message: "pGetPreloaded returns an unresolved statblock without throwing. Assembly must audit required insertions."});
    return {silent_miss_confirmed: true};
  });
  return {checks, warnings};
}
