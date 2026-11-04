import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {mkdir, mkdtemp, readFile, rename, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {parseArgs, promisify} from "node:util";
import {projectRoot, codeRoot, defaultDiagnosticsRoot, adapterHashes} from "../common/project_paths.mjs";
import {assertNodeVersion, inspectSnapshot} from "../runtime/preflight.mjs";
import {BOOK_IDS} from "../common/source_scan.mjs";
import {canonicalJson, serializeJson, sha256} from "../common/book_schema.mjs";
import {outsideUpstream, publishArtifacts} from "../common/artifact_store.mjs";
import {openUpstreamRuntime} from "../runtime/upstream_runtime.mjs";
import {AssemblyError} from "../assembly/assembly_content.mjs";
import {createEnrichmentApi} from "../enrichment/enrichment_content.mjs";
import {validateEnrichment} from "../validation/validate_enrichment.mjs";
import {findEnrichment, loadResolvedInputs} from "./resolved_inputs.mjs";
import {CONTENT_HASH_ALGORITHM, contentSha256} from "./resolved_content.mjs";
import {RESOLVED_SCHEMA_VERSION, RESOLVER_VERSION, toResolvedBook, validateResolvedBook} from "./resolved_schema.mjs";
import {MANIFEST_VERSION, fileMetadata, resolvedFiles, verifyResolvedBuild} from "./resolved_manifest.mjs";
import {assertOwnedBuild, buildExists, publishResolved, withBuildLock} from "./resolved_store.mjs";

const exec = promisify(execFile);
const REPOSITORY = "https://github.com/5etools-mirror-3/5etools-src";
const stageCli = {inventory: "inventory/inventory.mjs", assembly: "assembly/assemble_books.mjs", enrichment: "enrichment/enrich_books.mjs"};

export async function prepareInputs(snapshot, books, inventoryPath, assemblyPath, {diagnosticsRoot = defaultDiagnosticsRoot, verbose = true} = {}) {
  async function run(file, args) {
    const env = {...process.env, INIT_CWD: projectRoot};
    delete env.NODE_TEST_CONTEXT;
    const {stdout} = await exec(process.execPath, [path.join(codeRoot, file), "--upstream", snapshot.upstream, "--output-root", diagnosticsRoot, ...args], {cwd: projectRoot, env, timeout: 120_000, maxBuffer: 2 * 1024 * 1024});
    if (verbose) console.log(stdout.trim());
    const match = /report: (.+)/.exec(stdout);
    if (!match) throw new Error(`Prerequisite ${file} did not return a report path`);
    return path.dirname(match[1]);
  }
  inventoryPath ||= await run(stageCli.inventory, []);
  const preparationBooks = assemblyPath ? books : BOOK_IDS;
  assemblyPath ||= await run(stageCli.assembly, ["--inventory", inventoryPath, "--books", preparationBooks.join(",")]);
  const enrichmentPath = await run(stageCli.enrichment, ["--inventory", inventoryPath, "--assembly", assemblyPath, "--books", preparationBooks.join(",")]);
  return {inventoryPath, assemblyPath, enrichmentPath};
}

export async function runResolver(args = process.argv.slice(2)) {
  const {values} = parseArgs({args, options: {upstream: {type: "string"}, "output-root": {type: "string"}, books: {type: "string", default: BOOK_IDS.join(",")}, inventory: {type: "string"}, assembly: {type: "string"}, enrichment: {type: "string"}, "diagnostics-root": {type: "string"}, strict: {type: "boolean", default: true}, force: {type: "boolean", default: false}, "validate-only": {type: "boolean", default: false}, help: {type: "boolean"}}});
  if (values.help) {
    console.log("npm --prefix tools/ingestion run resolve -- [--books XPHB,XDMG,XMM] [--upstream PATH] [--output-root PATH] [--strict] [--force | --validate-only] [--enrichment PATH] [--inventory PATH] [--assembly PATH] [--diagnostics-root PATH]\nStandalone resolved JSON 1.0.0; only books and manifest are published. Prerequisites use a temporary workspace, removed on success/failure. --diagnostics-root retains detailed reports outside the dataset. --validate-only is read-only; critical failures always stop.");
    return;
  }
  if (values.force && values["validate-only"]) throw new Error("--force and --validate-only are mutually exclusive");
  const requested = values.books.split(",").map(id => id.trim().toUpperCase());
  if (!requested.length || new Set(requested).size !== requested.length || requested.some(id => !BOOK_IDS.includes(id))) throw new Error(`--books must contain unique IDs from ${BOOK_IDS.join(",")}`);
  const books = BOOK_IDS.filter(id => requested.includes(id));
  const caller = process.env.INIT_CWD || process.cwd();
  const absolute = value => value ? path.resolve(caller, value) : null;
  const snapshot = await inspectSnapshot(projectRoot, absolute(values.upstream) || path.join(projectRoot, "external/5etools-src"));
  assertNodeVersion(snapshot.node_engine);
  const sourceHashes = await adapterHashes();
  const config = {books, strict: true, content_hash_algorithm: CONTENT_HASH_ALGORITHM};
  const generatorBase = {name: "dnd_rag.ingestion.5etools_resolver", version: RESOLVER_VERSION, schema_version: RESOLVED_SCHEMA_VERSION, node_version: process.versions.node, source_sha256: sha256(canonicalJson(sourceHashes)), config_sha256: sha256(canonicalJson(config)), config};
  const signature = sha256(canonicalJson(generatorBase));
  const generator = {...generatorBase, signature};
  const upstream = {repository: REPOSITORY, checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha, gitlink_matches_checkout: true, tracked_clean: true, package_version: snapshot.package_version};
  const buildId = `${snapshot.checkout_sha}/${signature}`;
  const root = await outsideUpstream(absolute(values["output-root"]) || path.join(projectRoot, "data/resolved/5etools"), snapshot.upstream);
  const retainedRoot = values["diagnostics-root"] ? await outsideUpstream(absolute(values["diagnostics-root"]), snapshot.upstream) : null;
  if (retainedRoot && (!path.relative(root, retainedRoot) || !path.relative(root, retainedRoot).startsWith(`..${path.sep}`) && path.relative(root, retainedRoot) !== ".." && !path.isAbsolute(path.relative(root, retainedRoot)))) throw new Error("Diagnostics must be outside the resolved output root");
  const directory = path.join(root, snapshot.checkout_sha, signature);
  const expected = {books, generator, upstream, buildId, schemaSha256: sourceHashes["resolution/resolved-book.schema.json"]};
  async function checkSnapshot() {
    const after = await inspectSnapshot(projectRoot, snapshot.upstream);
    if (after.checkout_sha !== snapshot.checkout_sha) throw new Error("Upstream changed during finalization");
  }
  if (values["validate-only"]) {
    const verified = await verifyResolvedBuild(directory, expected);
    await checkSnapshot();
    console.log(`Resolved PASS (validated); manifest: ${path.join(directory, "manifest.json")}`);
    return {directory, ...verified};
  }
  return withBuildLock(directory, async () => {
    let temporary;
    try {
      if (await buildExists(directory)) {
        if (!values.force) {
          try {
            const verified = await verifyResolvedBuild(directory, expected);
            await checkSnapshot();
            console.log(`Resolved PASS (reused); manifest: ${path.join(directory, "manifest.json")}`);
            return {directory, ...verified};
          } catch (error) { throw new Error(`Existing resolved build failed verification: ${error.message}. Use --force to rebuild this build-id.`); }
        }
        await assertOwnedBuild(directory, {buildId, signature, upstreamSha: snapshot.checkout_sha, files: resolvedFiles(books)});
      }
      const workspace = retainedRoot || (temporary = await mkdtemp(path.join(await outsideUpstream(os.tmpdir(), snapshot.upstream), "dnd-book-assembly-")));
      let inventoryPath = absolute(values.inventory);
      let assemblyPath = absolute(values.assembly);
      let enrichment = await findEnrichment({projectRoot, snapshot, books, enrichmentPath: absolute(values.enrichment), diagnosticsRoot: workspace});
      if (!enrichment) {
        console.log("Preparing inventory/assembly/enrichment inputs...");
        const prepared = await prepareInputs(snapshot, books, inventoryPath, assemblyPath, {diagnosticsRoot: workspace, verbose: !!retainedRoot});
        ({inventoryPath, assemblyPath} = prepared);
        enrichment = await findEnrichment({projectRoot, snapshot, books, enrichmentPath: prepared.enrichmentPath, diagnosticsRoot: workspace});
      }
      const inputRoot = values.enrichment && !retainedRoot ? path.resolve(enrichment.directory, "../../..") : workspace;
      const inputs = await loadResolvedInputs({projectRoot, snapshot, books, enrichment, inventoryPath, assemblyPath, diagnosticsRoot: inputRoot});
      const artifacts = {};
      const validations = {};
      const manifestBooks = {};
      const audit = [];
      const runtime = await openUpstreamRuntime(snapshot.upstream);
      try {
        const api = await createEnrichmentApi(snapshot.upstream);
        for (const id of books) {
          const document = inputs.documents.get(id);
          const {audit: decisions, ...validation} = await validateEnrichment(document, inputs.inventory, inputs.assembly, api);
          if (validation.status !== "PASS") throw new AssemblyError("INCOMPLETE_ENRICHMENT", "Critical source-defined placements remain", {book: id, records: validation.unreviewed_critical});
          assert.deepEqual(decisions, inputs.audit.filter(row => row.source.toUpperCase() === id), "Enrichment placement audit differs from recomputed decisions");
          audit.push(...decisions);
          const provenance = {
            inventory: {signature: inputs.inventory.report.generator.signature, report_sha256: sha256(await readFile(path.join(inputs.inventory.directory, "report.json")))},
            assembly: {signature: inputs.assembly.report.generator.signature, report_sha256: inputs.assembly.report_sha256},
            enrichment: {signature: enrichment.report.generator.signature, report_sha256: enrichment.report_sha256, file_sha256: enrichment.report.artifacts[`${id.toLowerCase()}.enriched.json`].file_sha256},
          };
          const resolved = toResolvedBook(document, {generator, upstream, provenance});
          const bytes = serializeJson(resolved);
          const serialized = JSON.parse(bytes);
          const resolvedValidation = validateResolvedBook(serialized);
          const contentHash = contentSha256(serialized);
          const file = `${id.toLowerCase()}.resolved.json`;
          artifacts[file] = bytes;
          validations[id] = {...validation, resolved_validation: resolvedValidation, content_sha256: contentHash};
          manifestBooks[id] = {path: file, ...fileMetadata(bytes), content_sha256: contentHash};
          console.log(`${id}: ${resolvedValidation.chapters} chapters, ${resolvedValidation.embedded_occurrences} insertions, ${resolvedValidation.canonical_entities} canonical entities; PASS`);
        }
      } finally { runtime.close(); }
      await checkSnapshot();
      const report = {
        report_kind: "resolved_books", stage: 6, status: "PASS", corpus_completeness_status: "PASS_FOR_PINNED_SNAPSHOT", build_id: buildId, generator, upstream,
        adapter_file_sha256: sourceHashes, input_file_sha256: enrichment.report.input_file_sha256,
        input_enrichment: {signature: enrichment.report.generator.signature, report_sha256: enrichment.report_sha256},
        books: validations, placement_audit: {total_records: audit.length, unreviewed_critical: 0},
        artifacts: Object.fromEntries(Object.entries(artifacts).map(([file, bytes]) => [file, fileMetadata(bytes)])),
        checks: {schema: "PASS", source_layout: "PASS", required_insertions: "PASS", domain_rules: "PASS", self_contained: "PASS", placement_audit: "PASS", serialized_roundtrip: "PASS"},
        issues: enrichment.report.issues.filter(issue => !issue.book || books.includes(issue.book)), runtime_omissions: [...inputs.assembly.report.runtime_omissions, ...enrichment.report.runtime_omissions].filter(omission => !omission.book || books.includes(omission.book)),
        limitations: ["Images are retained as metadata/links; no pixel download or OCR.", "Validation concerns the pinned 5etools snapshot; a complete comparison with printed editions is not claimed."],
      };
      const manifest = {manifest_version: MANIFEST_VERSION, content_hash_algorithm: CONTENT_HASH_ALGORITHM, build_id: buildId, upstream, assembler: generator, books: manifestBooks,
        schema: {version: RESOLVED_SCHEMA_VERSION, file_sha256: expected.schemaSha256},
        validation: {status: "PASS", corpus_completeness_status: report.corpus_completeness_status, checks: report.checks,
          books: Object.fromEntries(Object.entries(validations).map(([id, value]) => [id, {resolved_validation: value.resolved_validation, source_records: value.source_records, domain_components: value.domain_components, placement_statuses: value.placement_statuses}])),
          placement_audit: report.placement_audit, warnings: report.issues.map(({severity, code, book, count}) => ({severity, code, ...(book ? {book} : {}), count: count ?? 1}))}};
      artifacts["manifest.json"] = serializeJson(manifest);
      // Detailed diagnostics are opt-in, outside the atomic four-file dataset.
      if (retainedRoot) {
        const diagnostics = path.join(retainedRoot, snapshot.checkout_sha, "resolution", signature);
        await publishArtifacts(diagnostics, {"report.json": serializeJson(report), "placement-audit.jsonl": audit.map(row => canonicalJson(row)).join("\n") + "\n"});
        console.log(`Diagnostics: ${diagnostics}`);
      }
      const publication = await publishResolved(directory, artifacts, {force: values.force, identity: {buildId, signature, upstreamSha: snapshot.checkout_sha}, verify: async staged => { await verifyResolvedBuild(staged, expected); await checkSnapshot(); }});
      console.log(`Resolved PASS (${publication}); manifest: ${path.join(directory, "manifest.json")}`);
      return {directory, manifest, report};
    } catch (error) {
      const reportPath = await outsideUpstream(path.join(retainedRoot || defaultDiagnosticsRoot, snapshot.checkout_sha, "failures", `${signature}.json`), snapshot.upstream);
      await mkdir(path.dirname(reportPath), {recursive: true});
      const staged = `${reportPath}.${process.pid}.tmp`;
      try {
        await writeFile(staged, serializeJson({report_kind: "resolved_books", stage: 6, status: "FAIL", build_id: buildId, generator, upstream, published_books: [], issues: [error instanceof AssemblyError ? error.issue : {severity: "ERROR", code: "RESOLUTION_FAILED", message: error.message}]}));
        await rename(staged, reportPath);
      } finally { await rm(staged, {force: true}); }
      error.reportPath = reportPath;
      throw error;
    } finally {
      if (temporary) await rm(temporary, {recursive: true, force: true});
    }
  }, {removeEmptyParent: true});
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await runResolver(); }
  catch (error) { console.error(`Resolved FAIL: ${error.message}`); if (error.reportPath) console.error(`Failure report: ${error.reportPath}`); process.exitCode = 1; }
}
