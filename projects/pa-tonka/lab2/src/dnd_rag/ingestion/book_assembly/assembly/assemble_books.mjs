import {projectRoot, codeRoot, defaultDiagnosticsRoot} from "../common/project_paths.mjs";
import {mkdir, readFile, rename, rm, writeFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {parseArgs} from "node:util";
import {assertNodeVersion, inspectSnapshot} from "../runtime/preflight.mjs";
import {BOOK_IDS, selectUnique} from "../common/source_scan.mjs";
import {canonicalJson, copyJson, origin, serializeJson, sha256} from "../common/book_schema.mjs";
import {openUpstreamRuntime} from "../runtime/upstream_runtime.mjs";
import {outsideUpstream, publishArtifacts} from "../common/artifact_store.mjs";
import {loadAssemblyInventory} from "./assembly_inventory.mjs";
import {AssemblyError, assembleChapter, createAssemblyApi} from "./assembly_content.mjs";
import {ASSEMBLY_SCHEMA_VERSION, ASSEMBLY_VERSION} from "./assembly_schema.mjs";
import {validateAssemblyBook} from "../validation/validate_assembly.mjs";



const codeFiles = ["common/project_paths.mjs", "assembly/assemble_books.mjs", "assembly/assembly_inventory.mjs", "assembly/assembly_content.mjs", "assembly/assembly_schema.mjs", "validation/validate_assembly.mjs", "common/artifact_store.mjs", "runtime/preflight.mjs", "common/source_scan.mjs", "common/book_schema.mjs", "runtime/upstream_runtime.mjs", "runtime/inventory_runtime.mjs", "common/tree.mjs"];

export async function runAssembly(args = process.argv.slice(2)) {
  const {values} = parseArgs({args, options: {upstream: {type: "string"}, "output-root": {type: "string"}, books: {type: "string", default: BOOK_IDS.join(",")}, inventory: {type: "string"}, help: {type: "boolean"}}});
  if (values.help) {
    console.log("npm --prefix tools/ingestion run assemble -- [--books XPHB,XDMG,XMM] [--upstream PATH] [--inventory PATH] [--output-root PATH]\nStage 4: all original chapters and required insertions; domain enrichment is deferred.");
    return;
  }
  const requested = values.books.split(",").map(value => value.trim().toUpperCase());
  if (!requested.length || new Set(requested).size !== requested.length || requested.some(id => !BOOK_IDS.includes(id))) throw new Error(`--books must contain unique IDs from ${BOOK_IDS.join(",")}`);
  const selectedBooks = BOOK_IDS.filter(id => requested.includes(id));
  const caller = process.env.INIT_CWD || process.cwd();
  const upstream = values.upstream ? path.resolve(caller, values.upstream) : path.join(projectRoot, "external/5etools-src");
  const snapshot = await inspectSnapshot(projectRoot, upstream);
  assertNodeVersion(snapshot.node_engine);
  const inventory = await loadAssemblyInventory({projectRoot, snapshot, inventoryPath: values.inventory ? path.resolve(caller, values.inventory) : null});
  const sourceHashes = {};
  for (const file of codeFiles) sourceHashes[file] = sha256(await readFile(path.join(codeRoot, file)));
  const generator = {name: "dnd_rag.ingestion.assembly", version: ASSEMBLY_VERSION, schema_version: ASSEMBLY_SCHEMA_VERSION, node_version: process.versions.node, source_sha256: sha256(canonicalJson(sourceHashes)), config: {books: selectedBooks, stage: 4, domain_enrichment: false, inventory_signature: inventory.report.generator.signature, inventory_report_sha256: sha256(await readFile(path.join(inventory.directory, "report.json")))}};
  const signature = sha256(canonicalJson(generator));
  const outputRoot = values["output-root"] ? path.resolve(caller, values["output-root"]) : defaultDiagnosticsRoot;
  const directory = await outsideUpstream(path.join(outputRoot, snapshot.checkout_sha, "assembly", signature), snapshot.upstream);
  try {
    return await buildAssembly({snapshot, inventory, selectedBooks, generator, signature, sourceHashes, directory});
  } catch (error) {
    const reportPath = await outsideUpstream(path.join(path.dirname(directory), "failures", `${signature}.json`), snapshot.upstream);
    const failed = {
      report_kind: "book_assembly", stage: 4, status: "FAIL", published_books: [],
      generator: {...generator, signature}, upstream: {checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha},
      issues: [error instanceof AssemblyError ? error.issue : {severity: "ERROR", code: "ASSEMBLY_FAILED", message: error.message}],
    };
    await mkdir(path.dirname(reportPath), {recursive: true});
    const temporary = `${reportPath}.${process.pid}.tmp`;
    try { await writeFile(temporary, serializeJson(failed), "utf8"); await rename(temporary, reportPath); }
    finally { await rm(temporary, {force: true}); }
    error.reportPath = reportPath;
    throw error;
  }
}

async function buildAssembly({snapshot, inventory, selectedBooks, generator, signature, sourceHashes, directory}) {
  const upstreamMeta = {checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha, gitlink_matches_checkout: true, tracked_clean: true, package_version: snapshot.package_version};
  const artifacts = {};
  const validations = {};
  const omissions = [];
  const templateReferences = [];
  const recovered = [];
  const runtime = await openUpstreamRuntime(snapshot.upstream);
  let runtimeFiles;
  try {
    const api = await createAssemblyApi(snapshot.upstream);
    const catalog = await inventory.readSource("data/books.json");
    for (const bookId of selectedBooks) {
      const file = `data/book/book-${bookId.toLowerCase()}.json`;
      const raw = await inventory.readSource(file);
      const book = selectUnique(raw.bookData, bookId, file);
      const catalogEntry = selectUnique(catalog.book, bookId, "data/books.json");
      if (book.source !== bookId || book.data.length !== catalogEntry.contents.length) throw new Error(`${bookId}: invalid source/catalog chapter count`);
      const recorded = inventory.books.find(entry => entry.id === bookId);
      if (!recorded || recorded.chapters.length !== book.data.length || recorded.chapters.some((chapter, i) => chapter.name !== book.data[i].name || !["MATCH", "DOCUMENTED_ALIAS"].includes(chapter.catalog_title_status))) throw new Error(`${bookId}: source chapter order/titles disagree with inventory`);
      const bookIndex = raw.bookData.indexOf(book);
      const chapters = [];
      for (const [chapterIndex, chapter] of book.data.entries()) {
        const result = await assembleChapter({bookId, chapterIndex, chapter, file, pointer: `/bookData/${bookIndex}/data/${chapterIndex}`}, snapshot, inventory, api);
        chapters.push(result.chapter);
        omissions.push(...result.omissions);
        templateReferences.push(...result.templateReferences);
        recovered.push(...result.recovered);
      }
      const document = {
        artifact_kind: "assembled_book", stage: 4, schema_version: ASSEMBLY_SCHEMA_VERSION,
        generator: {...generator, signature}, upstream: upstreamMeta,
        scope: {all_source_chapters: true, embedded_references_resolved: true, domain_enrichment: false, book_complete: false},
        book: {id: bookId, title: catalogEntry.name, published: catalogEntry.published ?? null, source_file: file, source_metadata: Object.fromEntries(Object.entries(book).filter(([key]) => key !== "data")), catalog_entry: copyJson(catalogEntry), catalog_origin: origin({file: "data/books.json", pointer: `/book/${catalog.book.indexOf(catalogEntry)}`, source: bookId, commit: snapshot.checkout_sha})},
        chapters,
      };
      const bytes = serializeJson(document);
      validations[bookId] = validateAssemblyBook(JSON.parse(bytes), {bookId, book, file, bookIndex}, inventory);
      artifacts[`${bookId.toLowerCase()}.assembled.json`] = bytes;
      console.log(`${bookId}: ${chapters.length} chapters, ${validations[bookId].resolved_statblocks}/${validations[bookId].source_statblocks} required insertions`);
    }
    runtimeFiles = runtime.loadedFiles;
  } finally { runtime.close(); }
  for (const file of runtimeFiles) {
    if (!inventory.inputFiles.has(file)) throw new Error(`Untracked native JSON input: ${file}`);
  }
  const inputHashes = {};
  for (const file of [...new Set(["data/books.json", ...selectedBooks.map(id => `data/book/book-${id.toLowerCase()}.json`), ...runtimeFiles])].sort()) {
    const hash = sha256(await readFile(path.join(snapshot.upstream, file)));
    if (hash !== inventory.inputFiles.get(file)?.file_sha256) throw new Error(`Native input changed since inventory: ${file}`);
    inputHashes[file] = hash;
  }
  const after = await inspectSnapshot(projectRoot, snapshot.upstream);
  if (after.checkout_sha !== snapshot.checkout_sha) throw new Error("Upstream changed during assembly");
  const report = {
    report_kind: "book_assembly", stage: 4, status: "PASS", validation_scope: "source_chapters_and_required_insertions", corpus_completeness_status: "PENDING_DOMAIN_ENRICHMENT",
    generator: {...generator, signature}, upstream: upstreamMeta,
    inventory: {signature: inventory.report.generator.signature, report_sha256: sha256(await readFile(path.join(inventory.directory, "report.json")))},
    adapter_file_sha256: sourceHashes, input_file_sha256: inputHashes,
    artifacts: Object.fromEntries(Object.entries(artifacts).map(([file, bytes]) => [file, {file_sha256: sha256(bytes), bytes: Buffer.byteLength(bytes)}])),
    books: validations, recovered_reference_ids: recovered, template_references: templateReferences,
    runtime_omissions: omissions,
    warnings: [{severity: "WARNING", code: "DOMAIN_ENRICHMENT_DEFERRED", message: "Stage 5 must add subclasses, summoned creatures, related fluff/legendary groups and audit source-defined placement. Stage-4 PASS is not a full-corpus completeness verdict."}],
  };
  artifacts["report.json"] = serializeJson(report);
  const publication = await publishArtifacts(directory, artifacts);
  console.log(`Assembly PASS (${publication}), scope: stage 4; report: ${path.join(directory, "report.json")}`);
  return {directory, report};
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await runAssembly(); }
  catch (error) {
    console.error(`Assembly FAIL: ${error.message}`);
    if (error instanceof AssemblyError) console.error(JSON.stringify(error.issue));
    if (error.reportPath) console.error(`Failure report: ${error.reportPath}`);
    process.exitCode = 1;
  }
}
