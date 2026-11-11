import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {inspectSnapshot} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/preflight.mjs";

const exec = promisify(execFile);
const root = fileURLToPath(new URL("../../../../", import.meta.url));
test("native smoke: pinned local spell, creature, copy/mod, silent miss and offline transport", {timeout: 30_000}, async t => {
  const upstream = path.join(root, "external/5etools-src");
  const before = await inspectSnapshot(root, upstream);
  const env = {...process.env}; delete env.NODE_TEST_CONTEXT;
  const {stdout} = await exec(process.execPath, [path.join(root, "tests/ingestion/book_assembly/helpers/native_smoke.mjs"), upstream], {cwd: root, env, timeout: 25_000, maxBuffer: 1024 * 1024});
  const result = JSON.parse(stdout);
  assert.ok(result.checks.length > 0);
  for (const check of result.checks) await t.test(check.name, () => assert.equal(check.status, "PASS", check.error));
  const tracked = new Set((await exec("git", ["-C", upstream, "ls-files", "-z", "--", "data"])).stdout.split("\0"));
  assert.ok(result.loaded_files.length > 0);
  assert.ok(result.loaded_files.every(file => tracked.has(file)));
  assert.equal((await inspectSnapshot(root, upstream)).checkout_sha, before.checkout_sha);
});
