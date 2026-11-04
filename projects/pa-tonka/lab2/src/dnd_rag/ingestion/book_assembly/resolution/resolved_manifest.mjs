import assert from "node:assert/strict";
import {readFile, readdir} from "node:fs/promises";
import path from "node:path";
import {sha256} from "../common/book_schema.mjs";
import {CONTENT_HASH_ALGORITHM, contentSha256} from "./resolved_content.mjs";
import {RESOLVED_SCHEMA_VERSION, validateResolvedBook} from "./resolved_schema.mjs";
import {buildExists} from "./resolved_store.mjs";

export const MANIFEST_VERSION = "2.0.0";
export const resolvedFiles = books => [...books.map(id => `${id.toLowerCase()}.resolved.json`), "manifest.json"].sort();
export const fileMetadata = bytes => ({file_sha256: sha256(bytes), bytes: Buffer.byteLength(bytes)});

/** Ready builds are independent of temporary intermediates and diagnostic reports. */
export async function verifyResolvedBuild(directory, expected) {
  if (!await buildExists(directory)) throw new Error(`No resolved build: ${directory}`);
  const entries = await readdir(directory, {withFileTypes: true});
  assert.deepEqual(entries.map(entry => entry.name).sort(), resolvedFiles(expected.books), "Unexpected/missing output files");
  assert.ok(entries.every(entry => entry.isFile() && !entry.isSymbolicLink()), "Resolved files must be regular files");
  const manifest = JSON.parse(await readFile(path.join(directory, "manifest.json"), "utf8"));
  assert.equal(manifest.manifest_version, MANIFEST_VERSION);
  assert.equal(manifest.content_hash_algorithm, CONTENT_HASH_ALGORITHM);
  assert.equal(manifest.build_id, expected.buildId);
  assert.deepEqual(manifest.assembler, expected.generator);
  assert.deepEqual(manifest.upstream, expected.upstream);
  assert.deepEqual(Object.keys(manifest.books).sort(), [...expected.books].sort());
  assert.deepEqual(manifest.schema, {version: RESOLVED_SCHEMA_VERSION, file_sha256: expected.schemaSha256});
  assert.equal(manifest.validation.status, "PASS");
  assert.equal(manifest.validation.corpus_completeness_status, "PASS_FOR_PINNED_SNAPSHOT");
  assert.deepEqual(manifest.validation.checks, {schema: "PASS", source_layout: "PASS", required_insertions: "PASS", domain_rules: "PASS", self_contained: "PASS", placement_audit: "PASS", serialized_roundtrip: "PASS"});
  assert.deepEqual(Object.keys(manifest.validation.books).sort(), [...expected.books].sort());
  assert.equal(manifest.validation.placement_audit.unreviewed_critical, 0);
  let audited = 0;
  for (const id of expected.books) {
    const meta = manifest.books[id];
    const file = `${id.toLowerCase()}.resolved.json`;
    assert.equal(meta.path, file);
    const value = await readFile(path.join(directory, file));
    assert.equal(sha256(value), meta.file_sha256, `Book integrity check failed: ${file}`);
    assert.equal(value.length, meta.bytes);
    const document = JSON.parse(value);
    assert.equal(document.book.id, id);
    assert.deepEqual(document.generator, expected.generator);
    assert.deepEqual(document.upstream, expected.upstream);
    assert.deepEqual(validateResolvedBook(document), manifest.validation.books[id].resolved_validation);
    assert.equal(contentSha256(document), meta.content_sha256, `Content integrity check failed: ${file}`);
    const stats = manifest.validation.books[id];
    assert.equal(document.domain.entities.reduce((n, entity) => n + entity.source_records.length, 0), stats.source_records);
    assert.equal(document.domain.entities.filter(entity => entity.representation === "domain_component").length, stats.domain_components);
    assert.ok(!stats.placement_statuses.unreviewed_critical);
    audited += Object.values(stats.placement_statuses).reduce((n, count) => { assert.ok(Number.isSafeInteger(count) && count >= 0); return n + count; }, 0);
  }
  assert.equal(audited, manifest.validation.placement_audit.total_records);
  return {manifest};
}
