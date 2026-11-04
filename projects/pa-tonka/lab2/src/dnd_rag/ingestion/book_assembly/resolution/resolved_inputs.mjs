import {adapterPath, defaultDiagnosticsRoot} from "../common/project_paths.mjs";
import {readFile, readdir, realpath} from "node:fs/promises";
import path from "node:path";
import {canonicalJson, sha256} from "../common/book_schema.mjs";
import {loadAssemblyInventory} from "../assembly/assembly_inventory.mjs";
import {loadEnrichmentInputs} from "../enrichment/enrichment_inputs.mjs";

export async function findEnrichment({projectRoot, snapshot, books, enrichmentPath, diagnosticsRoot = defaultDiagnosticsRoot}) {
  async function read(directory) {
    const bytes = await readFile(path.join(directory, "report.json"));
    const report = JSON.parse(bytes);
    if (report.stage !== 5 || report.status !== "PASS" || report.generator.schema_version !== "0.3.0") throw new Error("Expected successful stage-5 enrichment 0.3.0");
    if (report.upstream.checkout_sha !== snapshot.checkout_sha || report.upstream.gitlink_sha !== snapshot.gitlink_sha || !report.upstream.gitlink_matches_checkout || !report.upstream.tracked_clean) throw new Error("Enrichment does not match the clean pinned snapshot");
    const {signature, ...generator} = report.generator;
    if (sha256(canonicalJson(generator)) !== signature || sha256(canonicalJson(report.adapter_file_sha256)) !== generator.source_sha256 || generator.node_version !== process.versions.node) throw new Error("Enrichment signature/runtime mismatch");
    for (const [file, checksum] of Object.entries(report.adapter_file_sha256)) {
      if (sha256(await readFile(adapterPath(projectRoot, file))) !== checksum) throw new Error(`Enrichment is stale for ${file}; rerun enrich`);
    }
    if (books.some(book => report.books[book]?.status !== "PASS" || report.books[book].unreviewed_critical.length)) throw new Error("Enrichment does not cover requested books without critical omissions");
    if (report.input_assembly.signature !== generator.config.assembly_signature || report.input_assembly.report_sha256 !== generator.config.assembly_report_sha256) throw new Error("Enrichment assembly provenance mismatch");
    return {directory, report, report_sha256: sha256(bytes)};
  }
  if (enrichmentPath) return read(await realpath(enrichmentPath.endsWith(".json") ? path.dirname(enrichmentPath) : enrichmentPath));
  const parent = path.join(diagnosticsRoot, snapshot.checkout_sha, "enrichment");
  const candidates = [];
  for (const entry of await readdir(parent, {withFileTypes: true}).catch(error => { if (error.code === "ENOENT") return []; throw error; })) {
    if (!entry.isDirectory() || entry.name === "failures") continue;
    try { candidates.push(await read(path.join(parent, entry.name))); }
    catch { /* A historical code/snapshot/selection is not an eligible input. */ }
  }
  if (candidates.length > 1) throw new Error("Ambiguous current enrichment; supply --enrichment PATH");
  return candidates[0] || null;
}

export async function loadResolvedInputs({projectRoot, snapshot, books, enrichment, inventoryPath, assemblyPath, diagnosticsRoot = defaultDiagnosticsRoot}) {
  const inventory = await loadAssemblyInventory({projectRoot, snapshot, inventoryPath, diagnosticsRoot});
  const assembly = await loadEnrichmentInputs({projectRoot, snapshot, inventory, assemblyPath, books, diagnosticsRoot});
  if (assembly.report.generator.signature !== enrichment.report.input_assembly.signature || assembly.report_sha256 !== enrichment.report.input_assembly.report_sha256 || inventory.report.generator.signature !== enrichment.report.generator.config.inventory_signature) throw new Error("Stage-3/4/5 provenance chain mismatch");
  for (const [file, checksum] of Object.entries(enrichment.report.input_file_sha256)) {
    await inventory.readSource(file);
    if (inventory.inputFiles.get(file)?.file_sha256 !== checksum) throw new Error(`Enrichment source input mismatch: ${file}`);
  }
  const documents = new Map();
  for (const id of books) {
    const file = `${id.toLowerCase()}.enriched.json`;
    const bytes = await readFile(path.join(enrichment.directory, file));
    if (sha256(bytes) !== enrichment.report.artifacts[file]?.file_sha256) throw new Error(`Enrichment integrity check failed: ${file}`);
    const document = JSON.parse(bytes);
    if (canonicalJson(document.generator) !== canonicalJson(enrichment.report.generator) || document.input_assembly.signature !== assembly.report.generator.signature || document.input_assembly.file_sha256 !== assembly.report.artifacts[`${id.toLowerCase()}.assembled.json`].file_sha256) throw new Error(`Enrichment book/report provenance mismatch: ${file}`);
    documents.set(id, document);
  }
  const auditBytes = await readFile(path.join(enrichment.directory, "placement-audit.jsonl"));
  if (sha256(auditBytes) !== enrichment.report.artifacts["placement-audit.jsonl"]?.file_sha256) throw new Error("Enrichment integrity check failed: placement-audit.jsonl");
  const audit = auditBytes.toString("utf8").trim().split("\n").map(line => JSON.parse(line)).filter(row => books.includes(row.source.toUpperCase()));
  return {inventory, assembly, documents, audit};
}
