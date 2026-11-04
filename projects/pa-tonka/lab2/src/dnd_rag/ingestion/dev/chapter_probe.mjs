import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {parseArgs, promisify} from "node:util";
import {projectRoot, codeRoot, defaultDiagnosticsRoot, adapterHashes} from "../book_assembly/common/project_paths.mjs";
import {BOOK_IDS, readJson, selectUnique, walkJson} from "../book_assembly/common/source_scan.mjs";
import {canonicalJson, origin, restoreReferences, serializeJson, sha256} from "../book_assembly/common/book_schema.mjs";
import {collectEmbedded} from "../book_assembly/common/tree.mjs";
import {outsideUpstream, publishArtifacts} from "../book_assembly/common/artifact_store.mjs";
import {inspectSnapshot, assertNodeVersion} from "../book_assembly/runtime/preflight.mjs";
import {openUpstreamRuntime} from "../book_assembly/runtime/upstream_runtime.mjs";
import {loadAssemblyInventory} from "../book_assembly/assembly/assembly_inventory.mjs";
import {assembleChapter, createAssemblyApi} from "../book_assembly/assembly/assembly_content.mjs";

const exec = promisify(execFile);

export async function selectChapter(root, bookId, chapterIndex) {
  if (!BOOK_IDS.includes(bookId)) throw new Error(`Unsupported book ID: ${bookId}. Expected ${BOOK_IDS.join(", ")}.`);
  const catalog = await readJson(root, "data/books.json");
  const entry = selectUnique(catalog.book, bookId, "data/books.json");
  const file = `data/book/book-${bookId.toLowerCase()}.json`;
  const data = await readJson(root, file);
  const book = selectUnique(data.bookData, bookId, file);
  if (book.source !== bookId) throw new Error(`${file}: source differs from book ID`);
  if (book.data.length !== entry.contents.length) throw new Error(`${bookId}: catalog/chapter count differs`);
  if (!Number.isSafeInteger(chapterIndex) || chapterIndex < 0 || chapterIndex >= book.data.length) throw new Error(`Chapter index must be in 0..${book.data.length - 1}; got ${chapterIndex}`);
  const pointer = `/bookData/${data.bookData.indexOf(book)}/data/${chapterIndex}`;
  const chapter = book.data[chapterIndex];
  const catalogTitle = entry.contents[chapterIndex].name;
  if (chapter.name.replace(/^(?:Chapter \d+|Appendix [A-Z]): /, "") !== catalogTitle) {
    throw new Error(`${bookId} chapter ${chapterIndex}: catalog title "${catalogTitle}" differs from "${chapter.name}". This prototype has no title aliases.`);
  }
  return {bookId, chapterIndex, chapter, file, pointer, catalogEntry: entry, catalogPointer: `/book/${catalog.book.indexOf(entry)}`};
}

/** Compatibility command for chapter inspection, backed by the production assembler. */
export async function runPrototype(args = process.argv.slice(2)) {
  const {values} = parseArgs({args, options: {upstream: {type: "string"}, "output-root": {type: "string"}, book: {type: "string", default: "XPHB"}, chapter: {type: "string", default: "7"}, help: {type: "boolean"}}});
  if (values.help) {
    console.log("npm --prefix tools/ingestion run prototype -- [--book XPHB] [--chapter 7] [--upstream PATH] [--output-root PATH]\nDeveloper chapter probe using the production assembler, spell/monster chapters only; chapter index is zero-based.");
    return;
  }
  if (!/^(?:0|[1-9]\d*)$/.test(values.chapter)) throw new Error("--chapter must be a nonnegative zero-based integer");
  const caller = process.env.INIT_CWD || process.cwd();
  const snapshot = await inspectSnapshot(projectRoot, values.upstream ? path.resolve(caller, values.upstream) : path.join(projectRoot, "external/5etools-src"));
  assertNodeVersion(snapshot.node_engine);
  const selection = await selectChapter(snapshot.upstream, values.book.toUpperCase(), Number(values.chapter));
  const outputRoot = await outsideUpstream(values["output-root"] ? path.resolve(caller, values["output-root"]) : defaultDiagnosticsRoot, snapshot.upstream);
  const env = {...process.env, INIT_CWD: projectRoot}; delete env.NODE_TEST_CONTEXT;
  const {stdout} = await exec(process.execPath, [path.join(codeRoot, "inventory/inventory.mjs"), "--upstream", snapshot.upstream, "--output-root", outputRoot], {env, cwd: projectRoot, timeout: 120_000, maxBuffer: 2 * 1024 * 1024});
  const inventoryPath = path.dirname(/report: (.+)/.exec(stdout)[1]);
  const inventory = await loadAssemblyInventory({projectRoot, snapshot, inventoryPath});
  const references = inventory.references.filter(ref => ref.book_id === selection.bookId && ref.chapter_index === selection.chapterIndex && ref.required);
  if (references.some(ref => ref.kind !== "embedded_reference" || !["spell", "monster"].includes(ref.target.prop))) throw new Error("Unsupported chapter probe category; use the full resolve command for classes and domain enrichment");
  const runtime = await openUpstreamRuntime(snapshot.upstream);
  let result;
  try { result = await assembleChapter(selection, snapshot, inventory, await createAssemblyApi(snapshot.upstream)); }
  finally { runtime.close(); }
  const config = {book: selection.bookId, chapter_index: selection.chapterIndex, supported_props: ["spell", "monster"], domain_enrichment: false};
  const generatorBase = {name: "dnd_rag.ingestion.chapter_probe", source_sha256: sha256(canonicalJson(await adapterHashes())), probe_sha256: sha256(await readFile(new URL(import.meta.url))), config, node_version: process.versions.node};
  const signature = sha256(canonicalJson(generatorBase));
  const generator = {...generatorBase, assembler_signature: signature};
  const document = {artifact_kind: "chapter_prototype", stage: 2, schema_version: "0.1.0", generator,
    upstream: {checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha, gitlink_matches_checkout: true, package_version: snapshot.package_version, tracked_clean: true},
    scope: {book_complete: false, domain_enrichment: false, chapter_indexes: [selection.chapterIndex], supported_props: ["spell", "monster"]},
    book: {id: selection.bookId, title: selection.catalogEntry.name, published: selection.catalogEntry.published ?? null, source_file: selection.file, catalog_entry: selection.catalogEntry, catalog_origin: origin({file: "data/books.json", pointer: selection.catalogPointer, source: selection.bookId, commit: snapshot.checkout_sha})}, chapters: [result.chapter]};
  const bytes = serializeJson(document);
  assert.deepEqual(restoreReferences(JSON.parse(bytes).chapters[0].content), selection.chapter);
  assert.equal(collectEmbedded(result.chapter.content).length, references.length);
  let tables = 0, images = 0;
  walkJson(selection.chapter, node => { if (node?.type === "table") tables++; if (node?.type === "image") images++; });
  const validation = {status: "PASS", resolved_statblocks: references.length, source_statblocks: references.length, source_tables_preserved: tables, source_images_preserved: images};
  const report = {report_kind: "chapter_probe", stage: 2, status: "PASS", book: selection.bookId, chapter_index: selection.chapterIndex, upstream: document.upstream, generator, validation, artifact: {path: "chapter.prototype.json", file_sha256: sha256(bytes)}};
  const after = await inspectSnapshot(projectRoot, snapshot.upstream);
  assert.equal(after.checkout_sha, snapshot.checkout_sha);
  const directory = path.join(outputRoot, snapshot.checkout_sha, "prototype", signature);
  const publication = await publishArtifacts(directory, {"chapter.prototype.json": bytes, "report.json": serializeJson(report)});
  console.log(`Prototype PASS (${publication}): ${selection.bookId}, chapter ${selection.chapterIndex}, ${references.length}/${references.length} insertions`);
  console.log(`Chapter: ${path.join(directory, "chapter.prototype.json")}`);
  console.log(`Report: ${path.join(directory, "report.json")}`);
  return {directory, document, report};
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await runPrototype(); }
  catch (error) { console.error(`Prototype FAIL: ${error.message}`); process.exitCode = 1; }
}
