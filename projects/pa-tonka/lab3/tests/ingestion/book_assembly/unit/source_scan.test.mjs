import assert from "node:assert/strict";
import {mkdtemp, realpath, rm, symlink, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {selectUnique, walkJson} from "../../../../src/dnd_rag/ingestion/book_assembly/common/source_scan.mjs";
import {localJsonPath} from "../../../../src/dnd_rag/ingestion/book_assembly/runtime/upstream_runtime.mjs";

test("book selection uses ID and rejects missing/duplicate IDs", () => {
  const records = [{id: "OTHER"}, {id: "XPHB"}];
  assert.equal(selectUnique(records, "XPHB", "fixture"), records[1]);
  assert.throws(() => selectUnique(records, "XMM", "fixture"), /found 0/);
  assert.throws(() => selectUnique([...records, {id: "XPHB"}], "XPHB", "fixture"), /found 2/);
});

test("structural scan visits nested tables/images and fields outside entries without mutation", () => {
  const source = {entries: [{type: "table", rows: [[{type: "image", href: {"a/b~c": "img/example.webp"}}]]}], classTableGroups: [{rows: [[1, 2]]}]};
  const before = JSON.stringify(source);
  const pointers = [];
  walkJson(source, (_, pointer) => pointers.push(pointer));
  assert.ok(pointers.includes("/entries/0/rows/0/0/href/a~1b~0c"));
  assert.ok(pointers.includes("/classTableGroups/0/rows/0/1"));
  assert.equal(JSON.stringify(source), before);
});

test("runtime JSON transport rejects network URLs, traversal, and symlinks outside upstream", async t => {
  const temporary = await mkdtemp(path.join(os.tmpdir(), "dnd-ingestion-path-"));
  t.after(() => rm(temporary, {recursive: true, force: true}));
  const root = await realpath(temporary);
  await writeFile(path.join(root, "local.json"), "{}");
  await symlink(os.tmpdir(), path.join(root, "outside"));
  assert.equal(localJsonPath(root, "local.json"), "local.json");
  for (const url of ["https://5e.tools/data/books.json", "//5e.tools/data/books.json", "file:///tmp/example.json"]) assert.throws(() => localJsonPath(root, url), /Only local/);
  assert.throws(() => localJsonPath(root, ".."), /escapes/);
  assert.throws(() => localJsonPath(root, "outside"), /escapes/);
});
