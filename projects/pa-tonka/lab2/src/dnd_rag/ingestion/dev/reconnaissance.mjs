import {projectRoot, defaultDiagnosticsRoot} from "../book_assembly/common/project_paths.mjs";
import {outsideUpstream} from "../book_assembly/common/artifact_store.mjs";
import {createHash} from "node:crypto";
import {mkdir, readFile, rename, rm, writeFile} from "node:fs/promises";
import path from "node:path";

import {parseArgs} from "node:util";
import {assertNodeVersion, inspectSnapshot} from "../book_assembly/runtime/preflight.mjs";
import {scanBooks, scanClassSources} from "./source_review.mjs";
import {openUpstreamRuntime} from "../book_assembly/runtime/upstream_runtime.mjs";
import {smokeRuntime} from "./smoke_runtime.mjs";


const {values} = parseArgs({options: {upstream: {type: "string"}, report: {type: "string"}, help: {type: "boolean"}}});
if (values.help) {
  console.log("npm --prefix tools/ingestion run recon -- [--upstream PATH] [--report PATH]\nStage 1 only: source diagnostics and native loader smoke tests; no resolved books.");
} else {
  try {
    await main();
  } catch (error) {
    console.error(`Reconnaissance FAIL: ${error.message}`);
    process.exitCode = 1;
  }
}

async function main() {
  // Explicit CLI paths are relative to the caller (npm uses tools/ingestion).
  const callerRoot = process.env.INIT_CWD || process.cwd();
  const upstream = values.upstream ? path.resolve(callerRoot, values.upstream) : path.join(projectRoot, "external/5etools-src");
  const snapshot = await inspectSnapshot(projectRoot, upstream);
  assertNodeVersion(snapshot.node_engine);
  const reportPath = await outsideUpstream(values.report ? path.resolve(callerRoot, values.report) : path.join(defaultDiagnosticsRoot, snapshot.checkout_sha, "reconnaissance.json"), snapshot.upstream);
  if (reportPath === snapshot.upstream || reportPath.startsWith(`${snapshot.upstream}${path.sep}`)) throw new Error("Report must be outside the upstream submodule.");
  const books = await scanBooks(snapshot.upstream);
  const classSources = await scanClassSources(snapshot.upstream);
  const runtime = await openUpstreamRuntime(snapshot.upstream);
  let smoke;
  let loadedFiles;
  try {
    smoke = await smokeRuntime(snapshot.upstream, books, classSources);
    loadedFiles = runtime.loadedFiles;
  } finally {
    runtime.close();
  }
  // Detect changes during the run before publishing a successful report.
  const after = await inspectSnapshot(projectRoot, snapshot.upstream);
  if (after.checkout_sha !== snapshot.checkout_sha) throw new Error("Upstream changed during reconnaissance.");
  const failed = smoke.checks.filter(check => check.status === "FAIL");
  const files = [...new Set(["package.json", "data/books.json", "data/class/index.json", ...books.map(book => book.file), ...classSources.classes.map(e => e.file), ...classSources.subclasses.map(e => e.file), ...runtime.modules, "node/util.js", ...loadedFiles])].sort();
  const inputHashes = {};
  for (const file of files) inputHashes[file] = createHash("sha256").update(await readFile(path.join(snapshot.upstream, file))).digest("hex");
  const report = {
    report_kind: "reconnaissance", report_version: "0.1.0", stage: 1,
    status: failed.length ? "FAIL" : "PASS",
    assembly_status: "NOT_RUN",
    upstream: {
      checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha,
      gitlink_path: snapshot.gitlink_path, gitlink_matches_checkout: true,
      tracked_clean: true, package_version: snapshot.package_version,
    },
    environment: {node: process.versions.node, upstream_node_engine: snapshot.node_engine, runtime: "native-node", browser_required: false, upstream_npm_install_required: false},
    books, class_sources: classSources,
    smoke_checks: smoke.checks,
    warnings: [
      ...books.flatMap(book => book.chapters.filter(ch => !ch.title_matches_after_removing_number).map(ch => ({code: "CATALOG_TITLE_DIFFERENCE", book: book.id, chapter_index: ch.index, catalog_title: ch.catalog_title, source_title: ch.source_title}))),
      ...smoke.warnings,
    ],
    runtime_modules: runtime.modules, runtime_loaded_json_files: loadedFiles,
    inspected_file_sha256: inputHashes,
    limitations: ["Only representative insertions were resolved, not complete books.", "This is a preliminary structural scan, not a source-entity coverage/placement inventory.", "Browser rendering and Markdown export were not tested."],
  };
  await mkdir(path.dirname(reportPath), {recursive: true});
  const temporary = `${reportPath}.${process.pid}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await rename(temporary, reportPath);
  } finally {
    await rm(temporary, {force: true});
  }
  console.log(`Reconnaissance ${report.status}: 5etools ${snapshot.package_version}, ${snapshot.checkout_sha} (matches committed gitlink)`);
  for (const book of books) console.log(`${book.id}: ${book.chapters.length} parts, ${book.types.statblock || 0} statblocks, ${book.types.table || 0} tables, ${book.types.image || 0} images`);
  console.log(`Smoke checks: ${smoke.checks.length - failed.length}/${smoke.checks.length} passed; report: ${reportPath}`);
  for (const check of failed) console.error(`${check.name}: ${check.error}`);
  if (failed.length) process.exitCode = 1;
}
