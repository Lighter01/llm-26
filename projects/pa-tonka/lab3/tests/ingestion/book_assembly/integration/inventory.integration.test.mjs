import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {createReadStream} from "node:fs";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {createInterface} from "node:readline";
import test from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {atPointer, canonicalJson, sha256} from "../../../../src/dnd_rag/ingestion/book_assembly/common/book_schema.mjs";
import {readJson, walkJson} from "../../../../src/dnd_rag/ingestion/book_assembly/common/source_scan.mjs";
import {collectEmbedded} from "../../../../src/dnd_rag/ingestion/book_assembly/common/tree.mjs";

const exec = promisify(execFile);
const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const upstream = path.join(projectRoot, "external/5etools-src");
async function rows(file) {
  const result = [];
  for await (const line of createInterface({input: createReadStream(file), crlfDelay: Infinity})) if (line) result.push(JSON.parse(line));
  return result;
}

test("complete inventory matches local sources, native required targets and chapter prototypes; repeat is byte-identical", {timeout: 90_000}, async t => {
  const output = await mkdtemp(path.join(os.tmpdir(), "dnd-inventory-integration-"));
  t.after(() => rm(output, {recursive: true, force: true}));
  const env = {...process.env, INIT_CWD: projectRoot};
  delete env.NODE_TEST_CONTEXT;
  async function cli(file, extra = []) {
    return (await exec(process.execPath, [path.join(projectRoot, "src/dnd_rag/ingestion", file), "--upstream", upstream, "--output-root", output, ...extra], {cwd: projectRoot, env, timeout: 60_000, maxBuffer: 1024 * 1024})).stdout;
  }
  const firstOutput = await cli("book_assembly/inventory/inventory.mjs");
  const reportFile = /report: (.+)/.exec(firstOutput)?.[1];
  assert.ok(reportFile, firstOutput);
  const reportBytes = await readFile(reportFile, "utf8");
  const report = JSON.parse(reportBytes);
  const directory = path.dirname(reportFile);
  assert.equal(report.status, "PASS");
  assert.equal(report.stage, 3);
  assert.equal(report.assembly_status, "NOT_ASSEMBLED");
  assert.equal(report.upstream.checkout_sha, report.upstream.gitlink_sha);
  for (const [name, meta] of Object.entries(report.artifacts)) assert.equal(sha256(await readFile(path.join(directory, name))), meta.file_sha256, name);
  const files = await rows(path.join(directory, "files.jsonl"));
  const tracked = (await exec("git", ["-C", upstream, "ls-files", "-z", "--", "data"])).stdout.split("\0").filter(file => file.endsWith(".json")).sort();
  assert.deepEqual(files.map(row => row.file), tracked);
  for (const file of files) assert.equal(sha256(await readFile(path.join(upstream, file.file))), file.file_sha256, file.file);

  const books = JSON.parse(await readFile(path.join(directory, "books.json"), "utf8")).books;
  const sources = new Map();
  let expectedNodes = 0;
  for (const book of books) {
    const data = await readJson(upstream, book.file);
    sources.set(book.file, data);
    const selected = data.bookData.find(item => item.id === book.id);
    assert.equal(book.chapters.length, selected.data.length);
    assert.deepEqual(book.chapters.map(ch => ch.name), selected.data.map(ch => ch.name));
    let statblocks = 0, tables = 0, images = 0;
    for (const chapter of selected.data) walkJson(chapter, node => {
      expectedNodes++;
      if (node?.type === "statblock") statblocks++;
      if (["table", "tableGroup"].includes(node?.type)) tables++;
      if (node?.type === "image") images++;
    });
    assert.equal(book.counts.statblocks, statblocks);
    assert.equal(book.counts.tables, tables);
    assert.equal(book.counts.images, images);
    assert.equal(book.counts.unknown_types, 0);
  }
  let nodeCount = 0;
  const nodeIds = new Set();
  // Stream large node diagnostics instead of retaining the whole file in memory.
  for await (const line of createInterface({input: createReadStream(path.join(directory, "nodes.jsonl")), crlfDelay: Infinity})) {
    const node = JSON.parse(line);
    const raw = atPointer(sources.get(node.origin.file), node.origin.json_pointer);
    assert.equal(sha256(canonicalJson(raw)), node.raw_sha256);
    if (node.payload) assert.deepEqual(node.payload, raw);
    assert.ok(!nodeIds.has(node.occurrence_id));
    nodeIds.add(node.occurrence_id);
    nodeCount++;
  }
  assert.equal(nodeCount, expectedNodes);
  assert.equal(nodeCount, report.totals.nodes);

  const references = await rows(path.join(directory, "references.jsonl"));
  const entities = await rows(path.join(directory, "source-entities.jsonl"));
  const external = await rows(path.join(directory, "external-targets.jsonl"));
  const edges = await rows(path.join(directory, "dependencies.jsonl"));
  const recordIds = new Set([...entities, ...external].map(row => row.record_id));
  const physicalFiles = new Map(sources);
  async function physical(file) {
    if (!physicalFiles.has(file)) physicalFiles.set(file, await readJson(upstream, file));
    return physicalFiles.get(file);
  }
  for (const record of [...entities, ...external]) {
    assert.equal(sha256(canonicalJson(atPointer(await physical(record.origin.file), record.origin.json_pointer))), record.raw_sha256);
  }
  for (const ref of references) {
    assert.ok(nodeIds.has(ref.occurrence_id));
    if (ref.required) {
      assert.ok(ref.target);
      assert.equal(ref.loader_probe.status, "FOUND");
    }
    for (const id of ref.physical_record_ids || []) assert.ok(recordIds.has(id));
    if (ref.span) {
      const value = atPointer(sources.get(ref.origin.file), ref.origin.json_pointer);
      assert.equal(value.slice(ref.span.start, ref.span.end), ref.raw);
    }
  }
  assert.ok(entities.every(row => row.classification && row.classification_reason));
  for (const ref of references.filter(ref => ref.kind === "embedded_reference")) {
    const found = entities.filter(row => ref.physical_record_ids.includes(row.record_id));
    assert.ok(found.every(row => row.role !== "foundry_overlay"));
  }
  for (const edge of edges) {
    for (const id of edge.target_record_ids) assert.ok(recordIds.has(id));
    const value = atPointer(await physical(edge.file), edge.json_pointer);
    if (edge.span) assert.equal(value.slice(edge.span.start, edge.span.end), edge.raw);
  }
  assert.ok(edges.some(edge => edge.relation === "summoned_by_class"));
  assert.ok(entities.some(row => row.prop === "monster" && row.name === "Aberrant Spirit" && row.classification === "required_domain_component"));
  assert.ok(entities.some(row => row.prop === "optionalfeature" && row.name === "Agonizing Blast" && row.source === "XPHB" && row.structure.has_prerequisite && row.component_edges.length));
  assert.ok(entities.some(row => row.prop === "subclass" && row.name === "Path of the Berserker" && row.classification === "required_domain_component"));
  assert.ok(entities.some(row => row.classification === "requires_placement_review"), "Unplaced records must remain visible, not be silently excluded");
  assert.ok(external.every(row => row.classification === "external_reference_target" && !Object.hasOwn(row, "data")));

  // IDs/origins are shared with stage 2 without relying on pre-existing local outputs.
  const requiredByOccurrence = new Map(references.filter(ref => ref.required).map(ref => [ref.occurrence_id, ref]));
  for (const chapterIndex of [7, 9]) {
    const text = await cli("dev/chapter_probe.mjs", ["--chapter", String(chapterIndex)]);
    const prototype = JSON.parse(await readFile(/^Chapter: (.+)$/m.exec(text)[1], "utf8"));
    for (const embedded of collectEmbedded(prototype.chapters[0].content)) {
      const ref = requiredByOccurrence.get(embedded.occurrence_id);
      assert.ok(ref);
      assert.equal(embedded.entity_id, ref.target.entity_id);
      assert.deepEqual(embedded.original_reference, ref.raw);
      assert.deepEqual(embedded.placement.origin, ref.origin);
    }
  }
  const secondOutput = await cli("book_assembly/inventory/inventory.mjs");
  assert.match(secondOutput, /unchanged/);
  assert.equal(/report: (.+)/.exec(secondOutput)[1], reportFile);
  assert.equal(await readFile(reportFile, "utf8"), reportBytes);
  for (const [name, meta] of Object.entries(report.artifacts)) assert.equal(sha256(await readFile(path.join(directory, name))), meta.file_sha256);
});
