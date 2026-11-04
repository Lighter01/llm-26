import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {cp, lstat, mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {restoreReferences, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {contentSha256} from "../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolved_content.mjs";
import {validateResolvedBook} from "../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolved_schema.mjs";
import {prepareInputs} from "../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolve_books.mjs";
import {corpusRegressions} from "../helpers/corpus_regressions.mjs";

const exec = promisify(execFile);
const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const upstream = path.join(projectRoot, "external/5etools-src");
const env = {...process.env, INIT_CWD: projectRoot};
delete env.NODE_TEST_CONTEXT;

test("R13: final pipeline, verified reuse, atomic force, corruption recovery and subset isolation", {timeout: 240_000}, async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-resolved-integration-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  // Exercise the same real prerequisite orchestrator used by a clean-clone resolve.
  const prepared = await prepareInputs({upstream}, ["XPHB", "XDMG", "XMM"], null, null, {diagnosticsRoot: path.join(root, "diagnostics")});
  const args = ["--diagnostics-root", path.join(root, "diagnostics"), "--inventory", prepared.inventoryPath, "--assembly", prepared.assemblyPath, "--enrichment", prepared.enrichmentPath];
  const outputRoot = path.join(root, "resolved");
  async function cli(extra = []) {
    return (await exec(process.execPath, [path.join(projectRoot, "src/dnd_rag/ingestion/book_assembly/resolution/resolve_books.mjs"), "--upstream", upstream, "--output-root", outputRoot, ...args, ...extra], {cwd: projectRoot, env, timeout: 90_000, maxBuffer: 1024 * 1024})).stdout;
  }
  const output = await cli();
  const manifestPath = /manifest: (.+)/.exec(output)[1];
  const directory = path.dirname(manifestPath);
  const manifestBytes = await readFile(manifestPath, "utf8");
  const manifest = JSON.parse(manifestBytes);
  const diagnostics = /^Diagnostics: (.+)$/m.exec(output)[1];
  const report = JSON.parse(await readFile(path.join(diagnostics, "report.json"), "utf8"));
  assert.deepEqual((await readdir(directory)).sort(), ["manifest.json", "xdmg.resolved.json", "xmm.resolved.json", "xphb.resolved.json"]);
  assert.equal(report.status, "PASS");
  assert.equal(manifest.upstream.checkout_sha, manifest.upstream.gitlink_sha);
  assert.equal(manifest.validation.status, "PASS");
  assert.equal(report.placement_audit.unreviewed_critical, 0);
  const originalFiles = new Map();
  for (const file of await readdir(directory)) originalFiles.set(file, await readFile(path.join(directory, file)));
  for (const [id, metadata] of Object.entries(manifest.books)) {
    const bytes = originalFiles.get(metadata.path);
    assert.equal(sha256(bytes), metadata.file_sha256);
    const book = JSON.parse(bytes);
    assert.equal(book.schema_version, "1.0.0");
    assert.equal(book.scope.book_complete, true);
    assert.equal(book.stage, 6);
    assert.equal(contentSha256(book), metadata.content_sha256);
    assert.deepEqual(validateResolvedBook(book), report.books[id].resolved_validation);
    const enriched = JSON.parse(await readFile(path.join(prepared.enrichmentPath, `${id.toLowerCase()}.enriched.json`), "utf8"));
    assert.deepEqual(book.chapters, enriched.chapters);
    assert.deepEqual(book.domain, enriched.domain);
    const raw = JSON.parse(await readFile(path.join(upstream, book.book.source_file), "utf8")).bookData.find(row => row.id === id);
    assert.deepEqual(book.chapters.map(chapter => restoreReferences(chapter.content)), raw.data);
  }
  await corpusRegressions(t, {directory, upstream, diagnostics});
  const hidden = path.join(root, "hidden-diagnostics");
  await rename(path.join(root, "diagnostics"), hidden);
  const before = await lstat(manifestPath);
  assert.match(await cli(), /PASS \(reused\)/);
  assert.equal((await lstat(manifestPath)).ino, before.ino);
  assert.equal((await lstat(manifestPath)).mtimeMs, before.mtimeMs);
  assert.match(await cli(["--validate-only"]), /PASS \(validated\)/);
  assert.equal((await lstat(manifestPath)).mtimeMs, before.mtimeMs);

  await rename(hidden, path.join(root, "diagnostics"));

  const neighbor = path.join(path.dirname(directory), "b".repeat(64));
  const otherSnapshot = path.join(outputRoot, "2".repeat(40), "c".repeat(64));
  for (const folder of [neighbor, otherSnapshot]) { await mkdir(folder, {recursive: true}); await writeFile(path.join(folder, "marker"), "preserve"); }
  assert.match(await cli(["--force"]), /PASS \(replaced\)/);
  assert.notEqual((await lstat(manifestPath)).ino, before.ino, "Force must actually rebuild and exchange, rather than reuse");
  for (const [file, bytes] of originalFiles) assert.deepEqual(await readFile(path.join(directory, file)), bytes, `Force changed deterministic bytes: ${file}`);
  for (const folder of [neighbor, otherSnapshot]) assert.equal(await readFile(path.join(folder, "marker"), "utf8"), "preserve");

  const badInput = path.join(root, "corrupt-enrichment");
  await cp(prepared.enrichmentPath, badInput, {recursive: true});
  await writeFile(path.join(badInput, "xphb.enriched.json"), "{}\n");
  await assert.rejects(cli(["--enrichment", badInput, "--force"]), error => /Enrichment integrity check failed/.test(error.stderr));
  for (const [file, bytes] of originalFiles) assert.deepEqual(await readFile(path.join(directory, file)), bytes, "Failed force damaged previous valid build");

  await writeFile(path.join(directory, "xphb.resolved.json"), "{}\n");
  let failure;
  await assert.rejects(cli(), error => { failure = error; return /Book integrity check failed/.test(error.stderr) && /--force/.test(error.stderr); });
  const failurePath = /Failure report: (.+)/.exec(failure.stderr)[1];
  const failed = JSON.parse(await readFile(failurePath, "utf8"));
  assert.equal(failed.status, "FAIL");
  assert.deepEqual(failed.published_books, []);
  const failureBytes = await readFile(failurePath);
  await assert.rejects(cli(["--validate-only"]));
  assert.deepEqual(await readFile(failurePath), failureBytes, "Validate-only must not write failure reports");
  assert.match(await cli(["--force"]), /PASS \(replaced\)/);
  assert.deepEqual(await readFile(path.join(directory, "xphb.resolved.json")), originalFiles.get("xphb.resolved.json"));
  assert.equal(await readFile(manifestPath, "utf8"), manifestBytes);

  const changedManifest = JSON.parse(manifestBytes);
  changedManifest.books.XPHB.content_sha256 = "0".repeat(64);
  await writeFile(manifestPath, JSON.stringify(changedManifest));
  await assert.rejects(cli(), error => /Content integrity check failed|strictly equal/.test(error.stderr));
  assert.match(await cli(["--force"]), /PASS \(replaced\)/);
  assert.equal(await readFile(manifestPath, "utf8"), manifestBytes);

  const subsetOutput = await cli(["--books", "xmm"]);
  const subsetDirectory = path.dirname(/manifest: (.+)/.exec(subsetOutput)[1]);
  assert.notEqual(subsetDirectory, directory);
  assert.ok((await readdir(subsetDirectory)).includes("xmm.resolved.json"));
  assert.ok(!(await readdir(subsetDirectory)).includes("xphb.resolved.json"));
  assert.equal(await readFile(manifestPath, "utf8"), manifestBytes);
  assert.ok((await readdir(path.dirname(directory))).every(name => !name.includes("staging-") && !name.endsWith(".lock")));
});
