import {projectRoot, codeRoot, defaultDiagnosticsRoot} from "../common/project_paths.mjs";
import {execFile} from "node:child_process";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";
import {parseArgs, promisify} from "node:util";
import {assertNodeVersion, inspectSnapshot} from "../runtime/preflight.mjs";
import {BOOK_IDS} from "../common/source_scan.mjs";
import {canonicalJson, serializeJson, sha256} from "../common/book_schema.mjs";
import {openUpstreamRuntime} from "../runtime/upstream_runtime.mjs";
import {outsideUpstream, publishArtifacts} from "../common/artifact_store.mjs";
import {createInventoryApi} from "../runtime/inventory_runtime.mjs";
import {inventoryBooks} from "./inventory_books.mjs";
import {classifySourceRecords, inventoryDependencies, inventorySources} from "./inventory_sources.mjs";

const exec = promisify(execFile);


const codeFiles = ["common/project_paths.mjs", "inventory/inventory.mjs", "runtime/inventory_runtime.mjs", "inventory/inventory_books.mjs", "inventory/inventory_sources.mjs", "common/artifact_store.mjs", "runtime/preflight.mjs", "common/source_scan.mjs", "common/book_schema.mjs", "runtime/upstream_runtime.mjs"];
export const INVENTORY_VERSION = "0.1.0";

export function jsonLines(rows) { return rows.length ? `${rows.map(row => canonicalJson(row)).join("\n")}\n` : ""; }
function counts(rows, field) {
  const result = {};
  for (const row of rows) result[row[field] ?? "null"] = (result[row[field] ?? "null"] || 0) + 1;
  return result;
}

export async function runInventory(args = process.argv.slice(2)) {
  const {values} = parseArgs({args, options: {upstream: {type: "string"}, "output-root": {type: "string"}, help: {type: "boolean"}}});
  if (values.help) {
    console.log("npm --prefix tools/ingestion run inventory -- [--upstream PATH] [--output-root PATH]\nStage 3: all three raw books and source-defined records; no resolved-book assembly.");
    return;
  }
  const callerRoot = process.env.INIT_CWD || process.cwd();
  const upstream = values.upstream ? path.resolve(callerRoot, values.upstream) : path.join(projectRoot, "external/5etools-src");
  const snapshot = await inspectSnapshot(projectRoot, upstream);
  assertNodeVersion(snapshot.node_engine);
  const sourceHashes = {};
  for (const file of codeFiles) sourceHashes[file] = sha256(await readFile(path.join(codeRoot, file)));
  const generator = {name: "dnd_rag.ingestion.inventory", version: INVENTORY_VERSION, source_sha256: sha256(canonicalJson(sourceHashes)), node_version: process.versions.node, config: {books: BOOK_IDS, tracked_data_json: true, probe_required_book_targets: true}};
  const signature = sha256(canonicalJson(generator));
  const outputRoot = values["output-root"] ? path.resolve(callerRoot, values["output-root"]) : defaultDiagnosticsRoot;
  const directory = await outsideUpstream(path.join(outputRoot, snapshot.checkout_sha, "inventory", signature), snapshot.upstream);
  const {stdout} = await exec("git", ["-C", snapshot.upstream, "ls-files", "-z", "--", "data"], {maxBuffer: 8 * 1024 * 1024});
  const fileNames = stdout.split("\0").filter(file => file.endsWith(".json")).sort();
  if (!fileNames.length) throw new Error("No tracked data JSON files found in upstream");
  const issues = [];
  const runtime = await openUpstreamRuntime(snapshot.upstream);
  let bookInventory, catalog, edges, runtimeFiles, loaders;
  try {
    const api = createInventoryApi();
    loaders = api.loaders;
    bookInventory = await inventoryBooks(snapshot.upstream, snapshot.checkout_sha, api, issues);
    catalog = await inventorySources(snapshot.upstream, snapshot.checkout_sha, fileNames, api, issues);
    edges = inventoryDependencies(catalog, api, issues);
    const probes = new Map();
    for (const ref of bookInventory.references) {
      if (!ref.target) continue;
      ref.physical_record_ids = (catalog.byEntity.get(ref.target.entity_id) || []).map(record => record.record_id);
      const source = ref.target.source.toUpperCase();
      ref.target_scope = source === ref.book_id ? "same_book" : BOOK_IDS.includes(source) ? "other_core_book" : "outside_core_books";
      if (!ref.required) {
        ref.target_status = ref.physical_record_ids.length ? "catalog_record" : "catalog_miss_not_expanded";
        continue;
      }
      if (!probes.has(ref.target.entity_id)) {
        try { probes.set(ref.target.entity_id, await api.probe(ref.target)); }
        catch (error) { probes.set(ref.target.entity_id, {status: "MISSING", error: error.message}); }
      }
      ref.loader_probe = probes.get(ref.target.entity_id);
      ref.target_status = ref.loader_probe.status === "MISSING" ? "missing" : !ref.physical_record_ids.length ? "loader_generated" : ref.physical_record_ids.length > 1 ? "multiple_physical_candidates" : "physical_record";
      if (ref.target_status === "loader_generated" && ref.loader_probe.base_item) {
        ref.base_item_target = api.uidLookup("item", ref.loader_probe.base_item);
        ref.base_item_record_ids = (catalog.byEntity.get(ref.base_item_target.entity_id) || []).map(record => record.record_id);
      }
      if (ref.target_status === "missing") issues.push({severity: "ERROR", code: "MISSING_REQUIRED_BOOK_TARGET", message: ref.loader_probe.error, reference_id: ref.reference_id, origin: ref.origin, target: ref.target});
    }
    for (const edge of edges) {
      if (edge.required && !edge.target_record_ids.length) issues.push({severity: "ERROR", code: "MISSING_REQUIRED_DEPENDENCY", edge_id: edge.edge_id, file: edge.file, json_pointer: edge.json_pointer, target: edge.target});
    }
    classifySourceRecords(catalog, bookInventory.references, edges);
    for (const book of bookInventory.books) {
      const refs = bookInventory.references.filter(ref => ref.book_id === book.id);
      book.reference_kinds = counts(refs, "kind");
      book.target_scopes = counts(refs.filter(ref => ref.target), "target_scope");
      const expected = new Map();
      for (const ref of refs.filter(ref => ref.required && ref.target)) {
        if (!expected.has(ref.target.entity_id)) expected.set(ref.target.entity_id, {...ref.target, reference_ids: []});
        expected.get(ref.target.entity_id).reference_ids.push(ref.reference_id);
      }
      book.expected_entities = [...expected.values()];
    }
    runtimeFiles = runtime.loadedFiles;
  } finally { runtime.close(); }

  // Every JSON requested by the native loader must belong to the tracked snapshot.
  const tracked = new Set(fileNames);
  for (const file of runtimeFiles) if (!tracked.has(file)) issues.push({severity: "ERROR", code: "UNTRACKED_RUNTIME_INPUT", file});
  const after = await inspectSnapshot(projectRoot, snapshot.upstream);
  if (after.checkout_sha !== snapshot.checkout_sha) throw new Error("Upstream changed during inventory");
  const required = bookInventory.references.filter(ref => ref.required);
  const exportedIds = new Set(catalog.records.map(record => record.record_id));
  const externalIds = new Set([
    ...bookInventory.references.flatMap(ref => ref.physical_record_ids || []),
    ...edges.flatMap(edge => edge.target_record_ids),
    ...catalog.variants.map(variant => variant.parent_record_id),
  ].filter(id => !exportedIds.has(id)));
  const externalRecords = [...externalIds].sort().map(id => ({...catalog.all.get(id).record, classification: "external_reference_target", classification_reason: "Metadata/locator only for a direct reference from the selected scope; no recursive foreign corpus expansion."}));
  const nodeIds = new Set(bookInventory.nodes.map(node => node.occurrence_id));
  if (nodeIds.size !== bookInventory.nodes.length) throw new Error("Duplicate source node occurrence IDs");
  for (const ref of bookInventory.references) if (!nodeIds.has(ref.occurrence_id)) throw new Error(`Reference has no original source node: ${ref.reference_id}`);
  for (const [name, rows, key] of [["references", bookInventory.references, "reference_id"], ["records", catalog.records, "record_id"], ["edges", edges, "edge_id"], ["variants", catalog.variants, "definition_id"]]) {
    if (new Set(rows.map(row => row[key])).size !== rows.length) throw new Error(`Duplicate ${name} IDs`);
  }
  if (catalog.records.some(record => !record.classification || !record.classification_reason)) throw new Error("Unclassified source record");
  const artifacts = {
    "books.json": serializeJson({artifact_kind: "raw_book_inventory", inventory_version: INVENTORY_VERSION, books: bookInventory.books}),
    "nodes.jsonl": jsonLines(bookInventory.nodes),
    "references.jsonl": jsonLines(bookInventory.references),
    "source-entities.jsonl": jsonLines(catalog.records),
    "external-targets.jsonl": jsonLines(externalRecords),
    "dependencies.jsonl": jsonLines(edges),
    "variant-definitions.jsonl": jsonLines(catalog.variants),
    "files.jsonl": jsonLines(catalog.files),
    "issues.jsonl": jsonLines(issues),
  };
  const errors = issues.filter(issue => issue.severity === "ERROR");
  const report = {
    report_kind: "inventory", stage: 3, inventory_version: INVENTORY_VERSION,
    status: errors.length ? "FAIL" : "PASS", assembly_status: "NOT_ASSEMBLED", placement_audit_status: "REVIEW_REQUIRED",
    upstream: {checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha, gitlink_matches_checkout: true, tracked_clean: true, package_version: snapshot.package_version},
    generator: {...generator, signature}, adapter_file_sha256: sourceHashes,
    artifacts: Object.fromEntries(Object.entries(artifacts).map(([name, bytes]) => [name, {file_sha256: sha256(bytes), bytes: Buffer.byteLength(bytes)}])),
    books: bookInventory.books.map(book => ({id: book.id, chapters: book.chapters.length, ...book.counts, required_routes: book.required_routes})),
    totals: {tracked_data_files: fileNames.length, nodes: bookInventory.nodes.length, references: bookInventory.references.length, required_book_references: required.length, required_book_target_statuses: counts(required, "target_status"), book_reference_scopes: counts(bookInventory.references.filter(ref => ref.target), "target_scope"), source_records: catalog.records.length, source_classifications: counts(catalog.records, "classification"), source_props: counts(catalog.records.filter(record => record.role === "canonical_source"), "prop"), dependency_edges: edges.length, dependency_relations: counts(edges, "relation"), variant_definitions: catalog.variants.length, issues_by_severity: counts(issues, "severity")},
    native_loaders: loaders, runtime_loaded_json_files: runtimeFiles,
    validation: {unique_occurrences: true, references_have_source_nodes: true, unique_record_reference_edge_ids: true, all_source_records_classified: true, all_native_json_inputs_tracked: !issues.some(issue => issue.code === "UNTRACKED_RUNTIME_INPUT")},
    page_attributions: {
      book_nodes: counts(bookInventory.nodes.map(node => node.origin), "page_attribution"),
      book_references: counts(bookInventory.references.map(ref => ref.origin), "page_attribution"),
      source_records: counts(catalog.records.map(record => record.origin), "page_attribution"),
    },
    external_target_records: externalRecords.length,
    unique_required_book_targets: new Set(required.filter(ref => ref.target).map(ref => ref.target.entity_id)).size,
    limitations: ["No complete books were assembled.", "Source classifications are placement evidence/planning, not materialization or a full-book completeness verdict.", "Ordinary text/query links are recorded without recursive expansion.", "Generated projections and Foundry overlays are separate representations; no generated item combinations are appended."],
  };
  artifacts["report.json"] = serializeJson(report);
  const publication = await publishArtifacts(directory, artifacts);
  console.log(`Inventory ${report.status} (${publication}): ${fileNames.length} tracked JSON files, ${catalog.records.length} source records`);
  for (const book of report.books) console.log(`${book.id}: ${book.chapters} parts, ${book.statblocks} statblocks, ${book.tables} tables, ${book.images} images, ${book.unknown_types} unknown types`);
  console.log(`Required book targets: ${required.length}; errors: ${errors.length}; report: ${path.join(directory, "report.json")}`);
  for (const issue of errors.slice(0, 10)) console.error(JSON.stringify(issue));
  if (errors.length) process.exitCode = 1;
  return {directory, report};
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await runInventory(); }
  catch (error) { console.error(`Inventory FAIL: ${error.message}`); process.exitCode = 1; }
}
