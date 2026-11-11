import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {mkdtemp, mkdir, readFile, rm, stat, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {promisify} from "node:util";
import {assertNodeVersion, inspectSnapshot} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/preflight.mjs";

const exec = promisify(execFile);
async function git(cwd, ...args) {
  return (await exec("git", ["-C", cwd, ...args])).stdout.trim();
}
async function init(dir) {
  await mkdir(dir, {recursive: true});
  await git(dir, "init", "--initial-branch=main");
  await git(dir, "config", "user.email", "fixture@example.invalid");
  await git(dir, "config", "user.name", "Ingestion test fixture");
  await git(dir, "config", "commit.gpgSign", "false");
}
async function fixture(t) {
  const temporary = await mkdtemp(path.join(os.tmpdir(), "dnd-ingestion-git-"));
  t.after(() => rm(temporary, {recursive: true, force: true}));
  const repository = path.join(temporary, "main");
  // The Python project is nested inside a larger Git repository, as in this workspace.
  const project = path.join(repository, "projects/lab2");
  const subpath = "projects/lab2/external/5etools-src";
  const upstream = path.join(repository, subpath);
  await init(repository);
  await init(upstream);
  await writeFile(path.join(upstream, "package.json"), '{"version":"fixture","engines":{"node":">=24"}}\n');
  await git(upstream, "add", "package.json");
  await git(upstream, "commit", "-m", "fixture source");
  const pinned = await git(upstream, "rev-parse", "HEAD");
  await writeFile(path.join(repository, ".gitmodules"), `[submodule "5etools"]\n\tpath = ${subpath}\n\turl = https://example.invalid/5etools.git\n`);
  await git(repository, "add", ".gitmodules");
  await git(repository, "update-index", "--add", "--cacheinfo", `160000,${pinned},${subpath}`);
  await git(repository, "commit", "-m", "pin fixture submodule");
  await git(repository, "submodule", "absorbgitdirs", "--", subpath);
  return {repository, project, upstream, subpath, pinned};
}

test("clean checkout matches committed gitlink; .git is a file; untracked files are harmless", async t => {
  const f = await fixture(t);
  assert.ok((await stat(path.join(f.upstream, ".git"))).isFile());
  await writeFile(path.join(f.upstream, "local-cache.json"), "{}\n");
  const snapshot = await inspectSnapshot(f.project, f.upstream);
  assert.equal(snapshot.checkout_sha, f.pinned);
  assert.equal(snapshot.gitlink_sha, f.pinned);
  assert.equal(snapshot.gitlink_path, f.subpath);
});

test("staged-only gitlink update cannot bypass the committed HEAD check", async t => {
  const f = await fixture(t);
  await writeFile(path.join(f.upstream, "new.json"), "{}\n");
  await git(f.upstream, "add", "new.json");
  await git(f.upstream, "commit", "-m", "next source version");
  await git(f.repository, "add", f.subpath);
  await assert.rejects(inspectSnapshot(f.project, f.upstream), /differs from gitlink in HEAD.*Staging alone/s);
});

for (const staged of [false, true]) {
  test(`modified tracked source is rejected (staged=${staged})`, async t => {
    const f = await fixture(t);
    await writeFile(path.join(f.upstream, "package.json"), '{"changed":true}\n');
    if (staged) await git(f.upstream, "add", "package.json");
    await assert.rejects(inspectSnapshot(f.project, f.upstream), /modified tracked files/);
  });
}

test("uninitialized submodule is rejected instead of reading the parent repository", async t => {
  const f = await fixture(t);
  await rm(f.upstream, {recursive: true});
  await mkdir(f.upstream);
  await assert.rejects(inspectSnapshot(f.project, f.upstream), /not initialized/);
});

test("missing gitlink in HEAD is rejected", async t => {
  const f = await fixture(t);
  const other = path.join(f.project, "external/not-registered");
  await init(other);
  await assert.rejects(inspectSnapshot(f.project, other), /No committed gitlink in HEAD/);
});

test("preflight performs no tracked writes", async t => {
  const f = await fixture(t);
  const before = await readFile(path.join(f.upstream, "package.json"));
  await inspectSnapshot(f.project, f.upstream);
  assert.deepEqual(await readFile(path.join(f.upstream, "package.json")), before);
  assert.equal(await git(f.repository, "status", "--porcelain"), "");
});

test("Node engine check rejects Node 22 for the current upstream requirement", () => {
  assert.throws(() => assertNodeVersion(">=24", "22.22.3"), /requires Node.js >=24/);
  assert.doesNotThrow(() => assertNodeVersion(">=24", "24.22.2"));
});
