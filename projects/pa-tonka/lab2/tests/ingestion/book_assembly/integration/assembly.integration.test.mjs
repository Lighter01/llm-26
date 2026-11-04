import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {cp, mkdtemp, readFile, readdir, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {atPointer, copyJson, restoreReferences, serializeJson, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {readJson, walkJson} from "../../../../src/dnd_rag/ingestion/book_assembly/common/source_scan.mjs";
import {collectEmbedded} from "../../../../src/dnd_rag/ingestion/book_assembly/common/tree.mjs";
import {auditRequiredReferences} from "../../../../src/dnd_rag/ingestion/book_assembly/assembly/assembly_schema.mjs";
import {validateAssemblyBook} from "../../../../src/dnd_rag/ingestion/book_assembly/validation/validate_assembly.mjs";
import {loadAssemblyInventory} from "../../../../src/dnd_rag/ingestion/book_assembly/assembly/assembly_inventory.mjs";
import {inspectSnapshot} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/preflight.mjs";

const exec = promisify(execFile);
const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const upstream = path.join(projectRoot, "external/5etools-src");
const env = {...process.env, INIT_CWD: projectRoot};
delete env.NODE_TEST_CONTEXT;

test("stage 4: complete local books, inventory audit, generated-item provenance, deterministic rerun and failure isolation", {timeout: 120_000}, async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-assembly-integration-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  async function cli(file, args = []) {
    return (await exec(process.execPath, [path.join(projectRoot, "src/dnd_rag/ingestion", file), "--upstream", upstream, "--output-root", root, ...args], {cwd: projectRoot, env, timeout: 60_000, maxBuffer: 1024 * 1024})).stdout;
  }
  const inventoryOutput = await cli("book_assembly/inventory/inventory.mjs");
  const inventoryPath = path.dirname(/report: (.+)/.exec(inventoryOutput)[1]);
  const snapshot = await inspectSnapshot(projectRoot, upstream);
  const inventory = await loadAssemblyInventory({projectRoot, snapshot, inventoryPath});
  const output = await cli("book_assembly/assembly/assemble_books.mjs", ["--inventory", inventoryPath]);
  const reportFile = /report: (.+)/.exec(output)[1];
  const directory = path.dirname(reportFile);
  const reportBytes = await readFile(reportFile, "utf8");
  const report = JSON.parse(reportBytes);
  assert.equal(report.status, "PASS");
  assert.equal(report.stage, 4);
  assert.equal(report.corpus_completeness_status, "PENDING_DOMAIN_ENRICHMENT");
  assert.equal(report.upstream.checkout_sha, report.upstream.gitlink_sha);
  const wrappers = new Map();
  for (const id of ["XPHB", "XDMG", "XMM"]) {
    const file = `${id.toLowerCase()}.assembled.json`;
    const bytes = await readFile(path.join(directory, file));
    assert.equal(sha256(bytes), report.artifacts[file].file_sha256);
    const document = JSON.parse(bytes);
    const sourceFile = `data/book/book-${id.toLowerCase()}.json`;
    const source = await readJson(upstream, sourceFile);
    const book = source.bookData.find(item => item.id === id);
    assert.equal(document.scope.book_complete, false);
    assert.equal(document.scope.domain_enrichment, false);
    assert.deepEqual(document.chapters.map(ch => ch.title), book.data.map(ch => ch.name));
    assert.deepEqual(document.chapters.map(ch => restoreReferences(ch.content)), book.data);
    assert.deepEqual(validateAssemblyBook(document, {bookId: id, book, file: sourceFile, bookIndex: source.bookData.indexOf(book)}, inventory), report.books[id]);
    const embedded = document.chapters.flatMap(ch => collectEmbedded(ch.content));
    wrappers.set(id, embedded);
    assert.equal(embedded.length, inventory.references.filter(ref => ref.book_id === id && ref.required).length);
    for (const wrapper of embedded) assert.deepEqual(auditRequiredReferences(wrapper.data).unresolved, []);
    const tampered = copyJson(document);
    tampered.chapters[0].title = "Changed chapter";
    assert.throws(() => validateAssemblyBook(tampered, {bookId: id, book, file: sourceFile, bookIndex: source.bookData.indexOf(book)}, inventory));
  }
  const phb = wrappers.get("XPHB");
  const dmg = wrappers.get("XDMG");
  const mm = wrappers.get("XMM");
  const acid = phb.find(wrapper => wrapper.data.name === "Acid Splash");
  const rawSpell = atPointer(await readJson(upstream, acid.entity_origin.file), acid.entity_origin.json_pointer);
  for (const [field, value] of Object.entries(rawSpell)) assert.deepEqual(acid.data[field], value);
  const barbarian = phb.find(wrapper => wrapper.data.name === "Barbarian");
  const rawClass = atPointer(await readJson(upstream, barbarian.entity_origin.file), barbarian.entity_origin.json_pointer);
  assert.deepEqual(barbarian.data.classTableGroups, rawClass.classTableGroups);
  assert.deepEqual(barbarian.data.startingEquipment, rawClass.startingEquipment);
  assert.ok(barbarian.data.classFeatures.flat().every(feature => feature.entries?.length));
  const agonizing = [];
  walkJson(phb.find(wrapper => wrapper.data.name === "Warlock").data, node => {
    if (node?.name === "Agonizing Blast" && node.source === "XPHB") agonizing.push(node);
  });
  const rawOptional = (await readJson(upstream, "data/optionalfeatures.json")).optionalfeature.find(entry => entry.name === "Agonizing Blast" && entry.source === "XPHB");
  assert.ok(agonizing.length);
  assert.deepEqual(agonizing[0].prerequisite, rawOptional.prerequisite);
  const ape = phb.find(wrapper => wrapper.data.name === "Ape");
  assert.equal(ape.data.source, "XMM");
  assert.equal(ape.placement.book_id, "XPHB");
  assert.notEqual(ape.placement.origin.printed_page, ape.entity_origin.printed_page);
  for (const name of ["Aboleth", "Adult Black Dragon"]) {
    const monster = mm.find(wrapper => wrapper.lookup.prop === "monster" && wrapper.data.name === name);
    const raw = atPointer(await readJson(upstream, monster.entity_origin.file), monster.entity_origin.json_pointer);
    for (const field of ["ac", "hp", "action", "legendary", "legendaryGroup", "page"]) assert.deepEqual(monster.data[field], raw[field]);
  }
  assert.ok(mm.some(wrapper => wrapper.lookup.prop === "monsterFluff" && wrapper.data.name === "Aarakocra" && wrapper.data.entries.length));
  const generated = dmg.filter(wrapper => wrapper.entity_origin.lookup_source === "generated_item");
  assert.equal(generated.length, inventory.references.filter(ref => ref.book_id === "XDMG" && ref.required && ref.target_status === "loader_generated").length);
  for (const wrapper of generated) {
    assert.equal(wrapper.entity_origin.file, null);
    assert.equal(wrapper.entity_origin.json_pointer, null);
    assert.ok(wrapper.data._fullEntries.length);
    for (const where of [...wrapper.derivation.base_item.origins, ...wrapper.derivation.template.origins]) atPointer(await readJson(upstream, where.file), where.json_pointer);
    const templateOrigin = wrapper.derivation.template.origins[0];
    const template = atPointer(await readJson(upstream, templateOrigin.file), templateOrigin.json_pointer);
    assert.equal(wrapper.data.rarity, template.inherits.rarity);
    assert.equal(wrapper.data.page, template.inherits.page);
    if (template.inherits.bonusAc) assert.equal(wrapper.data.bonusAc, template.inherits.bonusAc);
  }
  assert.ok(dmg.every(wrapper => !Object.hasOwn(wrapper.data, "variants")));
  assert.ok(report.runtime_omissions.some(entry => entry.kind === "native_generated_variant_cache"));
  assert.ok(report.runtime_omissions.every(entry => ["native_generated_variant_cache", "undefined_runtime_flag"].includes(entry.kind)));

  // Exercise the actual native dereferencer on an intentionally unresolved feature.
  const nativeScript = `
    import path from 'node:path'; import {pathToFileURL} from 'node:url';
    const root = process.argv[1];
    const load = file => import(pathToFileURL(path.join(root, 'src/dnd_rag/ingestion', file)).href);
    const {openUpstreamRuntime} = await load('book_assembly/runtime/upstream_runtime.mjs');
    const {createAssemblyApi, resolveRemaining} = await load('book_assembly/assembly/assembly_content.mjs');
    const runtime = await openUpstreamRuntime(path.join(root, 'external/5etools-src'));
    try {
      const api = await createAssemblyApi(path.join(root, 'external/5etools-src'));
      const resolved = await resolveRemaining({name:'Fixture',source:'XPHB',className:'Barbarian',classSource:'XPHB',level:1,entries:[{type:'refOptionalfeature',optionalfeature:'Agonizing Blast|XPHB'}]}, 'classFeature', api);
      console.log(JSON.stringify(resolved));
    } finally {runtime.close();}
  `;
  const native = JSON.parse((await exec(process.execPath, ["--input-type=module", "-e", nativeScript, projectRoot], {cwd: projectRoot, env, timeout: 30_000})).stdout);
  assert.equal(native.entries[0].name, "Agonizing Blast");
  assert.deepEqual(native.entries[0].prerequisite, rawOptional.prerequisite);

  const repeated = await cli("book_assembly/assembly/assemble_books.mjs", ["--inventory", inventoryPath]);
  assert.match(repeated, /unchanged/);
  assert.equal(/report: (.+)/.exec(repeated)[1], reportFile);
  assert.equal(await readFile(reportFile, "utf8"), reportBytes);
  for (const [file, meta] of Object.entries(report.artifacts)) assert.equal(sha256(await readFile(path.join(directory, file))), meta.file_sha256);

  const brokenInventory = path.join(root, "broken-inventory");
  await cp(inventoryPath, brokenInventory, {recursive: true});
  const referenceFile = path.join(brokenInventory, "references.jsonl");
  const originalReferences = await readFile(referenceFile, "utf8");
  await writeFile(referenceFile, originalReferences + "\n");
  await assert.rejects(cli("book_assembly/assembly/assemble_books.mjs", ["--inventory", brokenInventory]), error => /integrity check failed/.test(error.stderr));
  const altered = originalReferences.trim().split("\n").map(line => JSON.parse(line));
  altered.find(ref => ref.book_id === "XPHB" && ref.required).raw.name = "__bad_inventory_reference__";
  const referenceBytes = altered.map(value => JSON.stringify(value)).join("\n") + "\n";
  await writeFile(referenceFile, referenceBytes);
  const alteredReport = JSON.parse(await readFile(path.join(brokenInventory, "report.json"), "utf8"));
  alteredReport.artifacts["references.jsonl"].file_sha256 = sha256(referenceBytes);
  alteredReport.artifacts["references.jsonl"].bytes = Buffer.byteLength(referenceBytes);
  await writeFile(path.join(brokenInventory, "report.json"), serializeJson(alteredReport));
  let assemblyError;
  await assert.rejects(cli("book_assembly/assembly/assemble_books.mjs", ["--inventory", brokenInventory]), error => {
    assemblyError = error;
    return error.code === 1;
  });
  const failurePath = /^Failure report: (.+)$/m.exec(assemblyError.stderr)[1];
  const failure = JSON.parse(await readFile(failurePath, "utf8"));
  assert.equal(failure.status, "FAIL");
  assert.deepEqual(failure.published_books, []);
  assert.equal(failure.issues[0].code, "INSERTION_RESOLUTION_FAILED");
  assert.ok(failure.issues[0].occurrence_path.startsWith("/bookData/"));
  const failedBuild = path.join(path.dirname(path.dirname(failurePath)), failure.generator.signature);
  await assert.rejects(readdir(failedBuild), {code: "ENOENT"});
  assert.equal(await readFile(reportFile, "utf8"), reportBytes, "Failed build must preserve the successful result");
});
