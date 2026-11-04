import assert from "node:assert/strict";
import {mkdtemp, mkdir, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {selectChapter} from "../../../../src/dnd_rag/ingestion/dev/chapter_probe.mjs";

const ref = {type: "statblock", tag: "creature", name: "Fixture Monster", source: "XMM"};

test("selection uses actual bookData/catalog positions and checks chapter bounds and titles", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dnd-chapter-source-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  await mkdir(path.join(root, "data/book"), {recursive: true});
  await writeFile(path.join(root, "data/books.json"), JSON.stringify({book: [{id: "OTHER"}, {id: "XPHB", contents: [{name: "Fixture"}]}]}));
  await writeFile(path.join(root, "data/book/book-xphb.json"), JSON.stringify({bookData: [{id: "OTHER"}, {id: "XPHB", source: "XPHB", data: [{name: "Chapter 1: Fixture", entries: [ref]}]}]}));
  const selected = await selectChapter(root, "XPHB", 0);
  assert.equal(selected.pointer, "/bookData/1/data/0");
  assert.equal(selected.catalogPointer, "/book/1");
  await assert.rejects(selectChapter(root, "XPHB", 1), /Chapter index/);
  await assert.rejects(selectChapter(root, "PHB", 0), /Unsupported book ID/);
});

