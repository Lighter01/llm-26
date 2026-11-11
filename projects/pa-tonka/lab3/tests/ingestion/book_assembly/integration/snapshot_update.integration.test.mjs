import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {inspectSnapshot} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/preflight.mjs";

const exec = promisify(execFile);
const root = fileURLToPath(new URL("../../../../", import.meta.url));
const originalUpstream = path.join(root, "external/5etools-src");
async function git(cwd, ...args) { return (await exec("git", ["-C", cwd, ...args], {timeout: 90_000, maxBuffer: 4 * 1024 * 1024})).stdout.trim(); }

test("R12/R11: real pinned commit update preserves content hashes; dirty/mismatch/unknown-required inputs cannot publish", {timeout: 240_000}, async t => {
  const original = await inspectSnapshot(root, originalUpstream);
  const temporary = await mkdtemp(path.join(os.tmpdir(), "dnd-snapshot-update-"));
  t.after(() => rm(temporary, {recursive: true, force: true}));
  const project = path.join(temporary, "project");
  const upstream = path.join(project, "external/5etools-src");
  await mkdir(path.dirname(upstream), {recursive: true});
  await git(temporary, "clone", "--shared", "--quiet", originalUpstream, upstream);
  for (const directory of [project, upstream]) {
    if (directory === project) await git(directory, "init", "--initial-branch=main");
    await git(directory, "config", "user.name", "Stage 7 isolated fixture");
    await git(directory, "config", "user.email", "fixture@example.invalid");
    await git(directory, "config", "commit.gpgSign", "false");
  }
  await cp(path.join(root, "src/dnd_rag/ingestion"), path.join(project, "src/dnd_rag/ingestion"), {recursive: true});
  await writeFile(path.join(project, ".gitmodules"), '[submodule "5etools"]\n\tpath = external/5etools-src\n\turl = https://example.invalid/local-fixture.git\n');
  async function pin(message) {
    const sha = await git(upstream, "rev-parse", "HEAD");
    await git(project, "add", ".gitmodules");
    await git(project, "update-index", "--add", "--cacheinfo", `160000,${sha},external/5etools-src`);
    await git(project, "commit", "-m", message);
    return sha;
  }
  await pin("pin original fixture snapshot");
  await git(project, "submodule", "absorbgitdirs", "--", "external/5etools-src");
  const outputRoot = path.join(project, "data/resolved/5etools");
  const scratch = path.join(temporary, "scratch");
  await mkdir(scratch);
  const env = {...process.env, INIT_CWD: project, TMPDIR: scratch}; delete env.NODE_TEST_CONTEXT;
  async function cli(extra = []) {
    return (await exec(process.execPath, [path.join(project, "src/dnd_rag/ingestion/book_assembly/resolution/resolve_books.mjs"), "--upstream", upstream, "--output-root", outputRoot, ...extra], {cwd: project, env, timeout: 120_000, maxBuffer: 4 * 1024 * 1024})).stdout;
  }
  const firstOutput = await cli();
  const firstPath = /manifest: (.+)/.exec(firstOutput)[1];
  const firstBytes = await readFile(firstPath);
  const first = JSON.parse(firstBytes);
  assert.equal(first.upstream.checkout_sha, original.checkout_sha);
  assert.deepEqual(await readdir(scratch), [], "Ordinary build must remove temporary intermediates");
  assert.deepEqual(await readdir(path.join(project, "data")), ["resolved"]);
  assert.deepEqual((await readdir(path.dirname(firstPath))).sort(), ["manifest.json", "xdmg.resolved.json", "xmm.resolved.json", "xphb.resolved.json"]);
  const firstFiles = new Map(await Promise.all(Object.values(first.books).map(async meta => [meta.path, sha256(await readFile(path.join(path.dirname(firstPath), meta.path)))])));

  await t.test("preflight rejects both unstaged and staged tracked edits, including without --strict", async () => {
    const packagePath = path.join(upstream, "package.json");
    const bytes = await readFile(packagePath);
    await writeFile(packagePath, Buffer.concat([bytes, Buffer.from("\n")]));
    await assert.rejects(cli(), error => /modified tracked files/.test(error.stderr));
    await git(upstream, "add", "package.json");
    await assert.rejects(cli(["--strict"]), error => /modified tracked files/.test(error.stderr));
    await writeFile(packagePath, bytes);
    await git(upstream, "restore", "--staged", "--", "package.json");
    assert.equal(await git(upstream, "status", "--porcelain", "--untracked-files=no"), "");
    assert.deepEqual(await readFile(firstPath), firstBytes);
  });
  await writeFile(path.join(upstream, "stage7-unrelated-fixture.txt"), "A tracked change unrelated to any book or runtime input.\n");
  await git(upstream, "add", "stage7-unrelated-fixture.txt");
  await git(upstream, "commit", "-m", "change only unrelated fixture file");
  const nextSha = await git(upstream, "rev-parse", "HEAD");
  await t.test("checkout mismatch and staged-only gitlink block the actual final CLI", async () => {
    await assert.rejects(cli(), error => /differs from gitlink in HEAD/.test(error.stderr));
    await git(project, "add", "external/5etools-src");
    await assert.rejects(cli(["--strict"]), error => /Staging alone is insufficient/.test(error.stderr));
    await assert.rejects(readdir(path.join(outputRoot, nextSha)), {code: "ENOENT"});
    assert.deepEqual(await readFile(firstPath), firstBytes);
  });
  await pin("commit next fixture gitlink");
  const nextOutput = await cli();
  const nextPath = /manifest: (.+)/.exec(nextOutput)[1];
  const nextBytes = await readFile(nextPath);
  const next = JSON.parse(nextBytes);
  await t.test("committed unrelated snapshot change creates a new directory with equal content hashes for all books", async () => {
    assert.equal(next.upstream.checkout_sha, nextSha); assert.equal(next.upstream.gitlink_sha, nextSha);
    assert.notEqual(path.dirname(nextPath), path.dirname(firstPath));
    for (const id of Object.keys(first.books)) {
      assert.notEqual(next.books[id].file_sha256, first.books[id].file_sha256);
      assert.equal(next.books[id].content_sha256, first.books[id].content_sha256, id);
    }
    assert.match(await cli(["--force"]), /PASS \(replaced\)/);
    assert.deepEqual(await readdir(scratch), [], "Force must remove temporary intermediates");
    assert.deepEqual(await readFile(nextPath), nextBytes);
    assert.deepEqual(await readFile(firstPath), firstBytes);
    for (const [file, checksum] of firstFiles) assert.equal(sha256(await readFile(path.join(path.dirname(firstPath), file))), checksum);
  });
  const spellFile = path.join(upstream, "data/spells/spells-xphb.json");
  const originalSpells = await readFile(spellFile);
  await t.test("R11: unknown entry type inside a loaded spell is blocking, with physical source evidence", async () => {
    const source = JSON.parse(originalSpells);
    const index = source.spell.findIndex(spell => spell.name === "Acid Splash" && spell.source === "XPHB");
    assert.ok(index >= 0);
    const entryIndex = source.spell[index].entries.length;
    source.spell[index].entries.push({type: "stage8Unsupported", entries: ["An unsupported rule block must be reviewed."]});
    await writeFile(spellFile, JSON.stringify(source));
    await git(upstream, "add", "data/spells/spells-xphb.json");
    await git(upstream, "commit", "-m", "introduce unsupported spell entry in fixture");
    const brokenSha = await pin("pin unsupported entity entry fixture");
    await assert.rejects(cli(["--diagnostics-root", path.join(project, ".cache/diagnostics")]), error => error.code === 1 && /UNKNOWN_SOURCE_ENTRY_TYPE/.test(error.stderr));
    await assert.rejects(readdir(path.join(outputRoot, brokenSha)), {code: "ENOENT"});
    const diagnostics = path.join(project, ".cache/diagnostics", brokenSha, "inventory");
    const [folder] = await readdir(diagnostics);
    const report = JSON.parse(await readFile(path.join(diagnostics, folder, "report.json"), "utf8"));
    assert.equal(report.status, "FAIL");
    const issues = (await readFile(path.join(diagnostics, folder, "issues.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
    assert.ok(issues.some(issue => issue.code === "UNKNOWN_SOURCE_ENTRY_TYPE" && issue.severity === "ERROR" && issue.file === "data/spells/spells-xphb.json" && issue.json_pointer === `/spell/${index}/entries/${entryIndex}` && issue.type === "stage8Unsupported"));
    await assert.rejects(cli(), error => error.code === 1 && /UNKNOWN_SOURCE_ENTRY_TYPE/.test(error.stderr));
    assert.deepEqual(await readdir(scratch), [], "Failed ordinary build must remove temporary intermediates");
    assert.deepEqual(await readdir(path.join(project, "data")), ["resolved"]);
    assert.deepEqual(await readFile(firstPath), firstBytes); assert.deepEqual(await readFile(nextPath), nextBytes);
  });
  await writeFile(spellFile, originalSpells);
  await t.test("R11: unknown required source type produces FAIL and no final manifest", async () => {
    const file = path.join(upstream, "data/book/book-xphb.json");
    const book = JSON.parse(await readFile(file, "utf8"));
    book.bookData.find(value => value.id === "XPHB").data[0].entries.push({type: "refStage7Unsupported", uid: "Fixture|XPHB"});
    await writeFile(file, JSON.stringify(book));
    await git(upstream, "add", "data/book/book-xphb.json", "data/spells/spells-xphb.json");
    await git(upstream, "commit", "-m", "introduce unsupported required reference in fixture");
    const brokenSha = await pin("pin unsupported fixture input");
    await assert.rejects(cli(["--diagnostics-root", path.join(project, ".cache/diagnostics")]), error => error.code === 1 && /UNKNOWN_BOOK_TYPE|INVALID_REQUIRED_REFERENCE/.test(error.stderr));
    await assert.rejects(readdir(path.join(outputRoot, brokenSha)), {code: "ENOENT"});
    const diagnostics = path.join(project, ".cache/diagnostics", brokenSha, "inventory");
    const folders = await readdir(diagnostics);
    assert.equal(folders.length, 1);
    const report = JSON.parse(await readFile(path.join(diagnostics, folders[0], "report.json"), "utf8"));
    assert.equal(report.status, "FAIL");
    assert.ok(report.totals.issues_by_severity.ERROR > 0);
    assert.deepEqual(await readFile(firstPath), firstBytes); assert.deepEqual(await readFile(nextPath), nextBytes);
  });
  assert.equal((await inspectSnapshot(root, originalUpstream)).checkout_sha, original.checkout_sha);
});
