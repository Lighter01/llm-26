import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {promisify} from "node:util";
import {publishResolved, withBuildLock, exchangeHelper} from "../../../../src/dnd_rag/ingestion/book_assembly/resolution/resolved_store.mjs";

const exec = promisify(execFile);
const signature = "a".repeat(64);
const upstreamSha = "1".repeat(40);
const identity = {signature, upstreamSha, buildId: `${upstreamSha}/${signature}`};
const manifest = JSON.stringify({build_id: identity.buildId, assembler: {signature}, upstream: {checkout_sha: upstreamSha}});
const artifacts = text => ({"book.json": text, "manifest.json": manifest});

test("atomic force exchange preserves siblings and the previous build on validation/exchange errors", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-resolved-store-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  const directory = path.join(root, signature);
  const neighbor = path.join(root, "b".repeat(64));
  await mkdir(neighbor); await writeFile(path.join(neighbor, "marker"), "keep");
  const options = {force: false, identity, verify: async staged => assert.equal(await readFile(path.join(staged, "book.json"), "utf8"), "old")};
  assert.equal(await publishResolved(directory, artifacts("old"), options), "created");
  await assert.rejects(publishResolved(directory, artifacts("new"), {...options, force: true, verify: async () => { throw new Error("Validation failed"); }}), /Validation failed/);
  assert.equal(await readFile(path.join(directory, "book.json"), "utf8"), "old");
  const replacement = {...options, force: true, verify: async staged => assert.equal(await readFile(path.join(staged, "book.json"), "utf8"), "new")};
  await assert.rejects(publishResolved(directory, artifacts("new"), {...replacement, exchange: async () => { throw new Error("Exchange unavailable"); }}), /Exchange unavailable/);
  assert.equal(await readFile(path.join(directory, "book.json"), "utf8"), "old");
  assert.equal(await publishResolved(directory, artifacts("new"), replacement), "replaced");
  assert.equal(await readFile(path.join(directory, "book.json"), "utf8"), "new");
  assert.equal(await readFile(path.join(neighbor, "marker"), "utf8"), "keep");
  assert.ok((await readdir(root)).every(name => !name.includes("staging")));

  // A helper error after the syscall must not misreport a committed exchange as FAIL.
  const warning = console.warn;
  console.warn = () => {};
  try {
    assert.equal(await publishResolved(directory, artifacts("new"), {...replacement, exchange: async (temporary, target) => {
      await exec("python3", [exchangeHelper, root, path.basename(temporary), path.basename(target)]);
      throw new Error("Helper exited after commit");
    }}), "replaced");
  } finally { console.warn = warning; }
  await writeFile(path.join(directory, "notes.txt"), "user note");
  await assert.rejects(publishResolved(directory, artifacts("new"), replacement), /unexpected build entry/);
  assert.equal(await readFile(path.join(directory, "notes.txt"), "utf8"), "user note");
});

test("build locks exclude concurrent writers, reject symlink targets and do not release another writer's lock", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-resolved-lock-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  const directory = path.join(root, signature);
  let entered;
  const ready = new Promise(resolve => { entered = resolve; });
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const first = withBuildLock(directory, async () => { entered(); await pending; });
  await ready;
  await assert.rejects(withBuildLock(directory, async () => {}), /Build is locked/);
  assert.ok((await readdir(root)).some(name => name.endsWith(".lock")));
  release(); await first;
  assert.deepEqual(await readdir(root), []);
  const foreign = path.join(root, "foreign");
  await mkdir(foreign); await writeFile(path.join(foreign, "marker"), "keep");
  await symlink(foreign, directory, "dir");
  await assert.rejects(publishResolved(directory, artifacts("new"), {force: true, identity, verify: async () => {}}), /real directory/);
  assert.equal(await readFile(path.join(foreign, "marker"), "utf8"), "keep");
});
