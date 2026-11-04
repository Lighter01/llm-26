import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {cp, mkdtemp, readFile, readdir, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {atPointer, canonicalJson, restoreReferences, serializeJson, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {collectEmbedded} from "../../../../src/dnd_rag/ingestion/book_assembly/common/tree.mjs";

const exec = promisify(execFile);
const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const upstream = path.join(projectRoot, "external/5etools-src");
const env = {...process.env, INIT_CWD: projectRoot};
delete env.NODE_TEST_CONTEXT;

test("stage 5: source-complete domain graph, native rules/fluff/variants, exhaustive decisions, repeatability and strict failures", {timeout: 180_000}, async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-enrichment-integration-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  async function cli(file, args = []) {
    return (await exec(process.execPath, [path.join(projectRoot, "src/dnd_rag/ingestion", file), "--upstream", upstream, "--output-root", root, ...args], {cwd: projectRoot, env, timeout: 90_000, maxBuffer: 1024 * 1024})).stdout;
  }
  const reportDirectory = output => path.dirname(/report: (.+)/.exec(output)[1]);
  const readJson = async file => JSON.parse(await readFile(file, "utf8"));
  const inventory = reportDirectory(await cli("book_assembly/inventory/inventory.mjs"));
  const assembly = reportDirectory(await cli("book_assembly/assembly/assemble_books.mjs", ["--inventory", inventory]));
  const args = ["--inventory", inventory, "--assembly", assembly];
  const directory = reportDirectory(await cli("book_assembly/enrichment/enrich_books.mjs", args));
  const reportBytes = await readFile(path.join(directory, "report.json"), "utf8");
  const report = JSON.parse(reportBytes);
  assert.equal(report.status, "PASS");
  assert.equal(report.stage, 5);
  assert.equal(report.upstream.checkout_sha, report.upstream.gitlink_sha);
  for (const [file, meta] of Object.entries(report.artifacts)) assert.equal(sha256(await readFile(path.join(directory, file))), meta.file_sha256);
  const rawCache = new Map();
  async function source(record) {
    const f = record.origin.file;
    if (!rawCache.has(f)) rawCache.set(f, await readJson(path.join(upstream, f)));
    return atPointer(rawCache.get(f), record.origin.json_pointer);
  }
  const sourceRecords = (await readFile(path.join(inventory, "source-entities.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
  const audit = (await readFile(path.join(directory, "placement-audit.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
  assert.equal(audit.length, sourceRecords.length);
  assert.equal(new Set(audit.map(row => row.record_id)).size, sourceRecords.length);
  assert.ok(audit.every(row => row.status !== "unreviewed_critical"));
  for (const record of sourceRecords.filter(row => row.classification === "requires_placement_review")) assert.equal(audit.find(row => row.record_id === record.record_id).status, "materialized", record.name);
  const docs = new Map();
  const entityMaps = new Map();
  const payloads = new Map();
  for (const bookId of ["XPHB", "XDMG", "XMM"]) {
    const doc = await readJson(path.join(directory, `${bookId.toLowerCase()}.enriched.json`));
    const before = await readJson(path.join(assembly, `${bookId.toLowerCase()}.assembled.json`));
    assert.deepEqual(doc.chapters, before.chapters, "Domain supplements must not alter source chapter content");
    assert.equal(doc.scope.domain_enrichment, true);
    assert.equal(doc.scope.book_complete, false);
    const original = (await readJson(path.join(upstream, doc.book.source_file))).bookData.find(book => book.id === bookId);
    assert.deepEqual(doc.chapters.map(ch => restoreReferences(ch.content)), original.data);
    const wrappers = new Map(doc.chapters.flatMap(chapter => collectEmbedded(chapter.content)).map(wrapper => [wrapper.occurrence_id, wrapper]));
    const nodes = new Map(doc.domain.entities.map(node => [node.entity_id, node]));
    const data = new Map(doc.domain.entities.map(node => [node.entity_id, node.data || wrappers.get(node.occurrence_id)?.data]));
    assert.equal(nodes.size, doc.domain.entities.length);
    for (const entity of nodes.values()) {
      assert.ok(data.get(entity.entity_id));
      for (const record of entity.source_records) assert.deepEqual(record.raw, await source(record));
    }
    docs.set(bookId, doc); entityMaps.set(bookId, nodes); payloads.set(bookId, data);
  }
  const find = (book, prop, name) => [...entityMaps.get(book).values()].find(entity => entity.prop === prop && payloads.get(book).get(entity.entity_id).name === name);
  const get = (book, entity) => payloads.get(book).get(entity.entity_id);
  const phb = docs.get("XPHB");
  const expectedClasses = sourceRecords.filter(row => row.role === "canonical_source" && row.prop === "class" && row.source === "XPHB");
  assert.equal(phb.domain.entities.filter(row => row.prop === "class").length, expectedClasses.length);
  for (const cls of expectedClasses) {
    const raw = await source(cls);
    const expected = [];
    for (const row of sourceRecords.filter(row => row.role === "canonical_source" && row.prop === "subclass" && row.source === "XPHB")) {
      const sub = await source(row);
      if (sub.className === raw.name && sub.classSource === raw.source) expected.push(row.identity.entity_id);
    }
    const actual = phb.domain.relationships.filter(edge => edge.from_entity_id === cls.identity.entity_id && edge.relation === "subclass").map(edge => edge.to_entity_id);
    assert.deepEqual(actual.toSorted(), expected.toSorted());
    const data = get("XPHB", entityMaps.get("XPHB").get(cls.identity.entity_id));
    assert.deepEqual(data.classTableGroups, raw.classTableGroups);
    assert.deepEqual(data.startingEquipment, raw.startingEquipment);
  }
  const berserker = find("XPHB", "subclass", "Path of the Berserker");
  assert.ok(berserker);
  assert.match(JSON.stringify(get("XPHB", berserker).subclassFeatures), /Frenzy/);
  const frenzy = find("XPHB", "subclassFeature", "Frenzy");
  assert.equal(get("XPHB", frenzy).level, 3);
  assert.equal(get("XPHB", frenzy).subclassShortName, "Berserker");
  const agonizing = find("XPHB", "optionalfeature", "Agonizing Blast");
  const rawAgonizing = agonizing.source_records[0].raw;
  assert.ok(rawAgonizing.prerequisite.length);
  assert.deepEqual(get("XPHB", agonizing).prerequisite, rawAgonizing.prerequisite);
  assert.deepEqual(get("XPHB", agonizing).featureType, rawAgonizing.featureType);
  const summoned = sourceRecords.filter(row => row.role === "canonical_source" && row.source === "XPHB" && row.prop === "monster" && (row.structure.summoned_by_spell || row.structure.summoned_by_class));
  for (const row of summoned) {
    const entity = entityMaps.get("XPHB").get(row.identity.entity_id);
    const raw = await source(row);
    assert.ok(entity);
    for (const field of ["ac", "hp", "action", "summonedBySpell", "summonedByClass", "summonedBySpellLevel"]) assert.deepEqual(get("XPHB", entity)[field], raw[field]);
    assert.equal(phb.domain.relationships.filter(edge => edge.to_entity_id === row.identity.entity_id && ["summoned_by_spell", "summoned_by_class"].includes(edge.relation)).length, 1);
  }
  const spirit = find("XPHB", "monster", "Aberrant Spirit");
  assert.match(JSON.stringify(get("XPHB", spirit)), /summonSpellLevel/);
  assert.equal(get("XPHB", find("XPHB", "spell", "Summon Aberration")).source, "XPHB");
  const mm = docs.get("XMM");
  const aeromancer = find("XMM", "monsterFluff", "Aarakocra Aeromancer");
  assert.match(JSON.stringify(get("XMM", aeromancer).entries), /control magical winds/);
  assert.match(JSON.stringify(get("XMM", aeromancer).entries), /Aarakocra are birdlike folk/);
  assert.ok(!get("XMM", aeromancer)._copy);
  assert.ok(aeromancer.shared_content.some(shared => shared.path.startsWith("/entries/")));
  for (const name of ["Aboleth", "Adult Black Dragon"]) {
    const monster = find("XMM", "monster", name);
    const data = get("XMM", monster);
    assert.ok(data.ac.length && data.hp && data.action.length && data.legendary.length);
    const edge = mm.domain.relationships.find(edge => edge.from_entity_id === monster.entity_id && edge.relation === "legendary_group");
    assert.ok(edge);
    const group = get("XMM", entityMaps.get("XMM").get(edge.to_entity_id));
    assert.ok(group.regionalEffects.length);
    assert.deepEqual(group.regionalEffects, entityMaps.get("XMM").get(edge.to_entity_id).source_records[0].raw.regionalEffects);
  }
  const ooze = find("XMM", "monster", "Psychic Gray Ooze");
  assert.equal(ooze.canonical_placement.relation, "monster_in_materialized_fluff_group");
  assert.ok(get("XMM", ooze).reaction.some(entry => entry.name === "Mind Corrosion"));
  const dmg = docs.get("XDMG");
  for (const name of ["Bag of Tricks, Gray", "+1 Rod of the Pact Keeper", "Enspelled Staff (Level 6)", "Black Dragon Scale Mail"]) {
    const item = find("XDMG", "item", name);
    assert.ok(item);
    assert.ok(dmg.domain.relationships.some(edge => edge.to_entity_id === item.entity_id && edge.relation === "item_group_member"));
    assert.ok(get("XDMG", item).rarity && get("XDMG", item).entries.length);
  }
  const shortDeck = find("XDMG", "deck", "Deck of Many Things (13 Cards)");
  assert.ok(!get("XDMG", shortDeck)._copy);
  assert.equal(get("XDMG", shortDeck).cards.length, shortDeck.source_records[0].raw.cards.length);
  assert.ok(find("XDMG", "monster", "Avatar of Death"));
  assert.ok(find("XDMG", "monster", "Giant Fly"));
  const generated = dmg.chapters.flatMap(chapter => collectEmbedded(chapter.content)).filter(wrapper => wrapper.derivation);
  for (const item of generated) {
    assert.ok(!item.data.variants);
    assert.ok(entityMaps.get("XDMG").has(item.derivation.template.target.entity_id));
    assert.ok(entityMaps.get("XDMG").has(item.derivation.base_item.target.entity_id));
  }
  // No theoretical native specificVariant cache has been promoted to book entities.
  assert.equal(dmg.domain.entities.filter(entity => entity.representation === "book_insertion" && entity.data_origin.lookup_source === "generated_item").length, generated.length);
  assert.ok(find("XDMG", "vehicle", "Apparatus of Kwalish"));
  assert.ok(find("XMM", "item", "Command Amulet"));
  assert.ok(find("XPHB", "item", "Psychic Blade"));
  assert.ok(dmg.chapters.some(chapter => /Appendix B/.test(chapter.title)) && dmg.chapters.some(chapter => /Appendix C/.test(chapter.title)));

  assert.match(await cli("book_assembly/enrichment/enrich_books.mjs", args), /unchanged/);
  assert.equal(await readFile(path.join(directory, "report.json"), "utf8"), reportBytes);
  // Corruption must fail before publication, leaving the successful build unchanged.
  const badAssembly = path.join(root, "bad-assembly");
  await cp(assembly, badAssembly, {recursive: true});
  await writeFile(path.join(badAssembly, "xphb.assembled.json"), "{}\n");
  await assert.rejects(cli("book_assembly/enrichment/enrich_books.mjs", ["--inventory", inventory, "--assembly", badAssembly]), error => /Assembly integrity check failed/.test(error.stderr));

  // Forge the dependency registry coherently to prove missing required domain targets are fatal.
  const badInventory = path.join(root, "bad-inventory");
  await cp(inventory, badInventory, {recursive: true});
  const depPath = path.join(badInventory, "dependencies.jsonl");
  const edges = (await readFile(depPath, "utf8")).trim().split("\n").map(line => JSON.parse(line));
  const edge = edges.find(edge => edge.relation === "legendary_group" && edge.target.source === "XMM");
  edge.target.entity_id = "entity:legendarygroup:xmm:__missing__";
  const edgeBytes = edges.map(edge => canonicalJson(edge)).join("\n") + "\n";
  await writeFile(depPath, edgeBytes);
  const inventoryReport = await readJson(path.join(badInventory, "report.json"));
  inventoryReport.artifacts["dependencies.jsonl"] = {file_sha256: sha256(edgeBytes), bytes: Buffer.byteLength(edgeBytes)};
  await writeFile(path.join(badInventory, "report.json"), serializeJson(inventoryReport));
  const forgedAssembly = path.join(root, "forged-assembly");
  await cp(assembly, forgedAssembly, {recursive: true});
  const assemblyReport = await readJson(path.join(forgedAssembly, "report.json"));
  assemblyReport.inventory.report_sha256 = sha256(await readFile(path.join(badInventory, "report.json")));
  assemblyReport.generator.config.inventory_report_sha256 = assemblyReport.inventory.report_sha256;
  const {signature: previousSignature, ...forgedGenerator} = assemblyReport.generator;
  assemblyReport.generator.signature = sha256(canonicalJson(forgedGenerator));
  for (const file of Object.keys(assemblyReport.artifacts)) {
    const document = await readJson(path.join(forgedAssembly, file));
    document.generator = assemblyReport.generator;
    const bytes = serializeJson(document);
    await writeFile(path.join(forgedAssembly, file), bytes);
    assemblyReport.artifacts[file] = {file_sha256: sha256(bytes), bytes: Buffer.byteLength(bytes)};
  }
  await writeFile(path.join(forgedAssembly, "report.json"), serializeJson(assemblyReport));
  let failure;
  await assert.rejects(cli("book_assembly/enrichment/enrich_books.mjs", ["--inventory", badInventory, "--assembly", forgedAssembly]), error => { failure = error; return /Missing physical domain dependency/.test(error.stderr); });
  const failurePath = /Failure report: (.+)/.exec(failure.stderr)[1];
  const failureReport = await readJson(failurePath);
  assert.equal(failureReport.status, "FAIL");
  assert.equal(failureReport.issues[0].code, "DOMAIN_DEPENDENCY_MISSING");
  assert.ok(failureReport.issues[0].occurrence_path.startsWith("/bookData/"));
  assert.deepEqual(failureReport.published_books, []);
  await assert.rejects(readdir(path.join(path.dirname(path.dirname(failurePath)), failureReport.generator.signature)), {code: "ENOENT"});
  assert.equal(await readFile(path.join(directory, "report.json"), "utf8"), reportBytes);
});
