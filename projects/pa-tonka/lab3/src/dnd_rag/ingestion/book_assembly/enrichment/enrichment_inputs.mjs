import {adapterPath, defaultDiagnosticsRoot} from "../common/project_paths.mjs";
import {readFile, readdir, realpath} from "node:fs/promises";
import path from "node:path";
import {atPointer, canonicalJson, sha256} from "../common/book_schema.mjs";
import {validateAssemblyBook} from "../validation/validate_assembly.mjs";

/** Stage 5 consumes the verified products of stages 3 and 4, never a loose JSON. */
export async function loadEnrichmentInputs({projectRoot, snapshot, inventory, assemblyPath, books, diagnosticsRoot = defaultDiagnosticsRoot}) {
  const extra = {};
  for (const file of ["dependencies.jsonl", "variant-definitions.jsonl"]) {
    const bytes = await readFile(path.join(inventory.directory, file));
    if (sha256(bytes) !== inventory.report.artifacts[file]?.file_sha256) throw new Error(`Inventory integrity check failed: ${file}`);
    extra[file] = bytes.toString("utf8").split("\n").filter(Boolean).map(line => JSON.parse(line));
  }
  async function reportAt(directory) {
    const bytes = await readFile(path.join(directory, "report.json"));
    const report = JSON.parse(bytes);
    if (report.stage !== 4 || report.status !== "PASS" || report.generator.config.inventory_signature !== inventory.report.generator.signature) throw new Error("Expected a successful stage-4 assembly using the current inventory");
    if (report.upstream.checkout_sha !== snapshot.checkout_sha || report.upstream.gitlink_sha !== snapshot.gitlink_sha || !report.upstream.tracked_clean) throw new Error("Assembly snapshot mismatch");
    const {signature, ...generator} = report.generator;
    if (sha256(canonicalJson(generator)) !== signature || generator.node_version !== process.versions.node || sha256(canonicalJson(report.adapter_file_sha256)) !== generator.source_sha256) throw new Error("Assembly signature/runtime mismatch");
    if (report.inventory.report_sha256 !== sha256(await readFile(path.join(inventory.directory, "report.json"))) || generator.config.inventory_report_sha256 !== report.inventory.report_sha256) throw new Error("Assembly inventory report mismatch");
    for (const [file, checksum] of Object.entries(report.adapter_file_sha256)) {
      if (sha256(await readFile(adapterPath(projectRoot, file))) !== checksum) throw new Error(`Assembly is stale for ${file}; rerun assemble`);
    }
    if (books.some(book => !report.books[book])) throw new Error("Assembly does not contain all requested books");
    return {directory, report, report_sha256: sha256(bytes)};
  }
  let selected;
  if (assemblyPath) selected = await reportAt(await realpath(assemblyPath.endsWith(".json") ? path.dirname(assemblyPath) : assemblyPath));
  else {
    const parent = path.join(diagnosticsRoot, snapshot.checkout_sha, "assembly");
    const candidates = [];
    for (const entry of await readdir(parent, {withFileTypes: true}).catch(error => { if (error.code === "ENOENT") return []; throw error; })) {
      if (!entry.isDirectory() || entry.name === "failures") continue;
      try { candidates.push(await reportAt(path.join(parent, entry.name))); }
      catch { /* Historical or partial selections are not eligible. */ }
    }
    if (candidates.length !== 1) throw new Error(`Expected one current assembly, found ${candidates.length}; run assemble or supply --assembly PATH`);
    [selected] = candidates;
  }
  const documents = new Map();
  for (const id of books) {
    const file = `${id.toLowerCase()}.assembled.json`;
    const bytes = await readFile(path.join(selected.directory, file));
    if (sha256(bytes) !== selected.report.artifacts[file]?.file_sha256) throw new Error(`Assembly integrity check failed: ${file}`);
    const document = JSON.parse(bytes);
    if (canonicalJson(document.generator) !== canonicalJson(selected.report.generator)) throw new Error(`Assembly book/report generator mismatch: ${file}`);
    const sourceFile = document.book.source_file;
    const source = await inventory.readSource(sourceFile);
    const book = source.bookData.find(entry => entry.id === id);
    validateAssemblyBook(document, {bookId: id, book, file: sourceFile, bookIndex: source.bookData.indexOf(book)}, inventory);
    documents.set(id, document);
  }
  for (const [file, checksum] of Object.entries(selected.report.input_file_sha256)) {
    await inventory.readSource(file);
    if (inventory.inputFiles.get(file)?.file_sha256 !== checksum) throw new Error(`Assembly input differs from inventory: ${file}`);
  }
  const rawRecords = new Map();
  for (const record of inventory.byRecord.values()) {
    const raw = atPointer(await inventory.readSource(record.origin.file), record.origin.json_pointer);
    if (sha256(canonicalJson(raw)) !== record.raw_sha256) throw new Error(`Source record integrity check failed: ${record.record_id}`);
    rawRecords.set(record.record_id, raw);
  }
  return {...selected, documents, dependencies: extra["dependencies.jsonl"], variants: extra["variant-definitions.jsonl"], rawRecords};
}
