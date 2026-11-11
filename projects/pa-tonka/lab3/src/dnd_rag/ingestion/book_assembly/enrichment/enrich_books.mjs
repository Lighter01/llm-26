import {projectRoot, codeRoot, defaultDiagnosticsRoot} from "../common/project_paths.mjs";
import {mkdir, readFile, rename, rm, writeFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {parseArgs} from "node:util";
import {assertNodeVersion, inspectSnapshot} from "../runtime/preflight.mjs";
import {BOOK_IDS} from "../common/source_scan.mjs";
import {canonicalJson, serializeJson, sha256} from "../common/book_schema.mjs";
import {openUpstreamRuntime} from "../runtime/upstream_runtime.mjs";
import {outsideUpstream, publishArtifacts} from "../common/artifact_store.mjs";
import {loadAssemblyInventory} from "../assembly/assembly_inventory.mjs";
import {AssemblyError} from "../assembly/assembly_content.mjs";
import {loadEnrichmentInputs} from "./enrichment_inputs.mjs";
import {annotateSharedFluff, createEnrichmentApi, enrichBook, ENRICHMENT_SCHEMA_VERSION, ENRICHMENT_VERSION} from "./enrichment_content.mjs";
import {validateEnrichment} from "../validation/validate_enrichment.mjs";



const codeFiles = ["common/project_paths.mjs", "enrichment/enrich_books.mjs", "enrichment/enrichment_inputs.mjs", "enrichment/enrichment_plan.mjs", "enrichment/enrichment_content.mjs", "validation/validate_enrichment.mjs", "assembly/assembly_inventory.mjs", "assembly/assembly_content.mjs", "assembly/assembly_schema.mjs", "validation/validate_assembly.mjs", "common/artifact_store.mjs", "runtime/preflight.mjs", "common/source_scan.mjs", "common/book_schema.mjs", "runtime/upstream_runtime.mjs", "runtime/inventory_runtime.mjs", "common/tree.mjs"];

export async function runEnrichment(args = process.argv.slice(2)) {
  const {values} = parseArgs({args, options: {upstream: {type: "string"}, "output-root": {type: "string"}, books: {type: "string", default: BOOK_IDS.join(",")}, inventory: {type: "string"}, assembly: {type: "string"}, strict: {type: "boolean", default: true}, help: {type: "boolean"}}});
  if (values.help) {
    console.log("npm --prefix tools/ingestion run enrich -- [--books XPHB,XDMG,XMM] [--inventory PATH] [--assembly PATH] [--upstream PATH] [--output-root PATH] [--strict]\nStage 5: domain enrichment and exhaustive placement audit; final manifest is stage 6. Critical omissions always fail.");
    return;
  }
  const requested = values.books.split(",").map(value => value.trim().toUpperCase());
  if (!requested.length || new Set(requested).size !== requested.length || requested.some(id => !BOOK_IDS.includes(id))) throw new Error(`--books must contain unique IDs from ${BOOK_IDS.join(",")}`);
  const books = BOOK_IDS.filter(id => requested.includes(id));
  const caller = process.env.INIT_CWD || process.cwd();
  const snapshot = await inspectSnapshot(projectRoot, values.upstream ? path.resolve(caller, values.upstream) : path.join(projectRoot, "external/5etools-src"));
  assertNodeVersion(snapshot.node_engine);
  const inventory = await loadAssemblyInventory({projectRoot, snapshot, inventoryPath: values.inventory ? path.resolve(caller, values.inventory) : null});
  const inputs = await loadEnrichmentInputs({projectRoot, snapshot, inventory, assemblyPath: values.assembly ? path.resolve(caller, values.assembly) : null, books});
  const sourceHashes = {};
  for (const file of codeFiles) sourceHashes[file] = sha256(await readFile(path.join(codeRoot, file)));
  const generator = {name: "dnd_rag.ingestion.enrichment", version: ENRICHMENT_VERSION, schema_version: ENRICHMENT_SCHEMA_VERSION, node_version: process.versions.node, source_sha256: sha256(canonicalJson(sourceHashes)), config: {books, stage: 5, strict: true, inventory_signature: inventory.report.generator.signature, assembly_signature: inputs.report.generator.signature, assembly_report_sha256: inputs.report_sha256}};
  const signature = sha256(canonicalJson(generator));
  const root = values["output-root"] ? path.resolve(caller, values["output-root"]) : defaultDiagnosticsRoot;
  const directory = await outsideUpstream(path.join(root, snapshot.checkout_sha, "enrichment", signature), snapshot.upstream);
  const baseReport = {report_kind: "book_domain_enrichment", stage: 5, generator: {...generator, signature}, upstream: inputs.report.upstream, adapter_file_sha256: sourceHashes, input_assembly: {signature: inputs.report.generator.signature, report_sha256: inputs.report_sha256}};
  try {
    const artifacts = {};
    const stats = {};
    const audits = [];
    const omissions = [];
    const issues = [];
    const runtime = await openUpstreamRuntime(snapshot.upstream);
    let runtimeFiles;
    try {
      const api = await createEnrichmentApi(snapshot.upstream);
      for (const bookId of books) {
        const result = await enrichBook(inputs.documents.get(bookId), inventory, inputs, api);
        const document = result.document;
        document.input_assembly = {signature: inputs.report.generator.signature, file_sha256: inputs.report.artifacts[`${bookId.toLowerCase()}.assembled.json`].file_sha256};
        document.generator = {...generator, signature};
        annotateSharedFluff(document);
        const bytes = serializeJson(document);
        const {audit, ...validation} = await validateEnrichment(JSON.parse(bytes), inventory, inputs, api);
        if (validation.status !== "PASS") throw new AssemblyError("UNREVIEWED_SOURCE_RECORDS", "Unplaced critical source-defined records remain", {book: bookId, records: validation.unreviewed_critical});
        stats[bookId] = validation;
        if (validation.unknown_component_pages) issues.push({severity: "WARNING", code: "UNKNOWN_COMPONENT_PAGES", book: bookId, count: validation.unknown_component_pages, message: "No exact entity printed page; null/unknown is retained independently of the book anchor."});
        if (validation.ordinary_text_reference_scopes.outside_core) issues.push({severity: "WARNING", code: "ORDINARY_EXTERNAL_REFERENCES", book: bookId, count: validation.ordinary_text_reference_scopes.outside_core, message: "Ordinary external text references are retained without expanding foreign books."});
        for (const entity of document.domain.entities.filter(entity => entity.canonical_placement.relation === "monster_in_materialized_fluff_group")) issues.push({severity: "INFO", code: "SOURCE_GROUP_SUPPLEMENT", book: bookId, entity_id: entity.entity_id, origin: entity.data_origin, placement: entity.canonical_placement, message: "Source-defined monster without its own book insertion is added to its verified fluff group; source insertions remain unchanged."});
        audits.push(...audit);
        omissions.push(...result.omissions);
        artifacts[`${bookId.toLowerCase()}.enriched.json`] = bytes;
        console.log(`${bookId}: ${validation.entities} canonical entities, ${validation.domain_components} domain components; placement audit PASS`);
      }
      runtimeFiles = runtime.loadedFiles;
    } finally { runtime.close(); }
    const inputHashes = {...inputs.report.input_file_sha256};
    for (const file of [...new Set([...runtimeFiles, ...[...inventory.byRecord.values()].map(record => record.origin.file)])].sort()) {
      const hash = sha256(await readFile(path.join(snapshot.upstream, file)));
      if (hash !== inventory.inputFiles.get(file)?.file_sha256) throw new Error(`Native input differs from inventory: ${file}`);
      inputHashes[file] = hash;
    }
    const after = await inspectSnapshot(projectRoot, snapshot.upstream);
    if (after.checkout_sha !== snapshot.checkout_sha) throw new Error("Upstream changed during enrichment");
    artifacts["placement-audit.jsonl"] = audits.map(row => canonicalJson(row)).join("\n") + "\n";
    const report = {...baseReport, status: "PASS", validation_scope: "domain_enrichment_and_all_source_defined_placements", corpus_completeness_status: "DOMAIN_AUDIT_PASS_FINAL_SCHEMA_PENDING", input_file_sha256: inputHashes, books: stats, runtime_omissions: omissions, issues,
      artifacts: Object.fromEntries(Object.entries(artifacts).map(([file, bytes]) => [file, {file_sha256: sha256(bytes), bytes: Buffer.byteLength(bytes)}])),
      limitations: ["Final resolved schema, manifest, content_sha256 and --force remain stage 6.", "Printed pages are retained when known; no pixel downloads/OCR or complete printed-edition comparison."],
    };
    artifacts["report.json"] = serializeJson(report);
    const publication = await publishArtifacts(directory, artifacts);
    console.log(`Enrichment PASS (${publication}); report: ${path.join(directory, "report.json")}`);
    return {directory, report};
  } catch (error) {
    const reportPath = await outsideUpstream(path.join(path.dirname(directory), "failures", `${signature}.json`), snapshot.upstream);
    const failed = {...baseReport, status: "FAIL", published_books: [], issues: [error instanceof AssemblyError ? error.issue : {severity: "ERROR", code: "ENRICHMENT_FAILED", message: error.message}]};
    await mkdir(path.dirname(reportPath), {recursive: true});
    const temporary = `${reportPath}.${process.pid}.tmp`;
    try { await writeFile(temporary, serializeJson(failed)); await rename(temporary, reportPath); }
    finally { await rm(temporary, {force: true}); }
    error.reportPath = reportPath;
    throw error;
  }
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await runEnrichment(); }
  catch (error) {
    console.error(`Enrichment FAIL: ${error.message}`);
    if (error instanceof AssemblyError) console.error(JSON.stringify(error.issue));
    if (error.reportPath) console.error(`Failure report: ${error.reportPath}`);
    process.exitCode = 1;
  }
}
