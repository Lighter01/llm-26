import {spawn} from "node:child_process";
import {mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";
import {parseArgs} from "node:util";
import {assertNodeVersion, inspectSnapshot} from "../../src/dnd_rag/ingestion/book_assembly/runtime/preflight.mjs";
import {canonicalJson, serializeJson, sha256} from "../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {outsideUpstream} from "../../src/dnd_rag/ingestion/book_assembly/common/artifact_store.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const toolRoot = fileURLToPath(new URL(".", import.meta.url));
const upstream = path.join(root, "external/5etools-src");
const suites = new Set(["all", "unit", "smoke", "integration"]);

export function selectTests(files, suite) {
  if (!suites.has(suite)) throw new Error(`Unknown test suite: ${suite}`);
  return files.filter(file => file.endsWith(".test.mjs") && (suite === "all" || suite === "smoke" && file.endsWith(".smoke.test.mjs") || suite === "integration" && file.endsWith(".integration.test.mjs") || suite === "unit" && !file.endsWith(".integration.test.mjs") && !file.endsWith(".smoke.test.mjs"))).sort();
}

export function summarizeEvents(events, exitCode) {
  const summary = events.findLast(event => event.type === "test:summary" && !event.data.file)?.data;
  const tests = events.filter(event => ["test:pass", "test:fail"].includes(event.type)).map(({type, data}) => ({
    ...data, status: data.skip ? "SKIP" : data.todo ? "TODO" : type === "test:pass" ? "PASS" : "FAIL",
  }));
  const counts = summary?.counts || {tests: 0, passed: 0, failed: 0, cancelled: 0, skipped: 0, todo: 0, suites: 0};
  const complete = tests.filter(test => test.kind !== "suite").length === counts.tests && tests.every(test => test.status === "PASS");
  const status = exitCode === 0 && summary?.success && counts.tests > 0 && complete && !["failed", "cancelled", "skipped", "todo"].some(key => counts[key]) ? "PASS" : "FAIL";
  return {status, exit_code: exitCode, counts, duration_ms: summary?.duration_ms ?? null, tests};
}

async function codeHashes() {
  const files = [];
  async function collect(directory) {
    for (const entry of await readdir(path.join(root, directory), {withFileTypes: true})) {
      const file = `${directory}/${entry.name}`;
      if (entry.isDirectory() && entry.name !== "node_modules" && entry.name !== "__pycache__") await collect(file);
      else if (entry.isFile() && /\.(?:mjs|json|py)$/.test(entry.name)) files.push(file);
    }
  }
  for (const directory of ["src/dnd_rag/ingestion", "tests/ingestion", "tools/ingestion"]) await collect(directory);
  return Object.fromEntries(await Promise.all(files.sort().map(async file => [file, sha256(await readFile(path.join(root, file)))])));
}

export async function runTests(args = process.argv.slice(2)) {
  const {values} = parseArgs({args, options: {suite: {type: "string", default: "all"}, report: {type: "string"}, help: {type: "boolean"}}});
  if (values.help) { console.log("npm --prefix tools/ingestion test -- [--suite all|unit|smoke|integration] [--report PATH]"); return; }
  const discovered = [];
  async function discover(directory = "") {
    for (const entry of await readdir(path.join(root, "tests/ingestion", directory), {withFileTypes: true})) {
      const file = path.posix.join(directory, entry.name);
      if (entry.isDirectory()) await discover(file);
      else if (entry.isFile()) discovered.push(file);
    }
  }
  await discover();
  const files = selectTests(discovered, values.suite);
  if (!files.length) throw new Error("Test selection is empty");
  const snapshot = await inspectSnapshot(root, upstream);
  assertNodeVersion(snapshot.node_engine);
  const hashes = await codeHashes();
  const configuration = {suite: values.suite, files: files.map(file => `tests/ingestion/${file}`), node_version: process.versions.node, code_sha256: sha256(canonicalJson(hashes))};
  const signature = sha256(canonicalJson(configuration));
  const defaultReport = path.join(root, ".cache/ingestion/tests", snapshot.checkout_sha, signature, "report.json");
  const reportPath = await outsideUpstream(values.report ? path.resolve(process.env.INIT_CWD || process.cwd(), values.report) : defaultReport, upstream);
  const temporary = await mkdtemp(path.join(os.tmpdir(), "dnd-test-events-"));
  try {
    const eventsPath = path.join(temporary, "events.jsonl");
    const env = {...process.env};
    delete env.NODE_TEST_CONTEXT;
    const child = spawn(process.execPath, ["--test", "--test-isolation=none", "--test-reporter=spec", "--test-reporter-destination=stdout", `--test-reporter=${path.join(toolRoot, "test_reporter.mjs")}`, `--test-reporter-destination=${eventsPath}`, ...files.map(file => path.join(root, "tests/ingestion", file))], {cwd: root, env, stdio: "inherit"});
    const exitCode = await new Promise((resolve, reject) => { child.once("error", reject); child.once("close", code => resolve(code)); });
    const rows = (await readFile(eventsPath, "utf8").catch(error => { if (error.code === "ENOENT") return ""; throw error; })).split("\n").filter(Boolean).map(line => JSON.parse(line));
    const result = summarizeEvents(rows, exitCode);
    for (const test of result.tests) if (test.file) test.file = path.relative(root, test.file).split(path.sep).join("/");
    const issues = [];
    try {
      const after = await inspectSnapshot(root, upstream);
      if (after.checkout_sha !== snapshot.checkout_sha) throw new Error("Upstream SHA changed during tests");
      if (canonicalJson(await codeHashes()) !== canonicalJson(hashes)) throw new Error("Adapter/test/tool code changed during tests");
    } catch (error) { result.status = "FAIL"; issues.push({severity: "ERROR", code: "TEST_INPUT_CHANGED", message: error.message}); }
    const report = {report_kind: "ingestion_tests", stage: 7, report_version: "1.0.0", ...result,
      upstream: {checkout_sha: snapshot.checkout_sha, gitlink_sha: snapshot.gitlink_sha, gitlink_matches_checkout: true, tracked_clean: true},
      generator: {name: "dnd_rag.ingestion.tests", signature, ...configuration}, code_file_sha256: hashes, issues};
    await mkdir(path.dirname(reportPath), {recursive: true});
    const staged = `${reportPath}.${process.pid}.tmp`;
    try { await writeFile(staged, serializeJson(report)); await rename(staged, reportPath); }
    finally { await rm(staged, {force: true}); }
    console.log(`Tests ${report.status}: ${result.counts.passed}/${result.counts.tests}; report: ${reportPath}`);
    if (report.status !== "PASS") process.exitCode = 1;
    return {report, reportPath};
  } finally { await rm(temporary, {recursive: true, force: true}); }
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  try { await runTests(); }
  catch (error) { console.error(`Tests FAIL: ${error.message}`); process.exitCode = 1; }
}
