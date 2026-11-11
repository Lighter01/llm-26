import assert from "node:assert/strict";
import test from "node:test";
import {selectTests, summarizeEvents} from "../../../../tools/ingestion/run_tests.mjs";
import reporter from "../../../../tools/ingestion/test_reporter.mjs";

test("test suite selection includes every test exactly once without silently dropping new files", () => {
  const files = ["book_assembly/unit/one.test.mjs", "book_assembly/integration/two.integration.test.mjs", "book_assembly/smoke/native.smoke.test.mjs", "book_assembly/helpers/helper.mjs"];
  assert.equal(selectTests(files, "all").length, 3);
  assert.deepEqual(selectTests(files, "unit"), ["book_assembly/unit/one.test.mjs"]);
  assert.deepEqual(selectTests(files, "smoke"), ["book_assembly/smoke/native.smoke.test.mjs"]);
  assert.deepEqual(selectTests(files, "integration"), ["book_assembly/integration/two.integration.test.mjs"]);
  assert.throws(() => selectTests(files, "unknown"));
});

test("test report cannot turn missing summary, skips, failures or a nonzero process exit into PASS", () => {
  const summary = {success: true, counts: {tests: 1, passed: 1, failed: 0, cancelled: 0, skipped: 0, todo: 0, suites: 0}, duration_ms: 1};
  const passed = {type: "test:pass", data: {name: "Fixture", kind: "test"}};
  assert.equal(summarizeEvents([passed, {type: "test:summary", data: summary}], 0).status, "PASS");
  assert.equal(summarizeEvents([{type: "test:summary", data: summary}], 0).status, "FAIL");
  assert.equal(summarizeEvents([], 0).status, "FAIL");
  assert.equal(summarizeEvents([{type: "test:summary", data: summary}], 1).status, "FAIL");
  for (const key of ["failed", "cancelled", "skipped", "todo"]) {
    const changed = {...summary, counts: {...summary.counts, [key]: 1}};
    assert.equal(summarizeEvents([{type: "test:summary", data: changed}], 0).status, "FAIL");
  }
});

test("machine reporter preserves failed test context without serializing huge assertion payloads", async () => {
  const error = new Error("test failed", {cause: new Error("missing prerequisite")});
  error.actual = {book: "x".repeat(100_000)};
  async function* events() { yield {type: "test:fail", data: {name: "Prerequisite", file: "/fixture/test.mjs", line: 3, details: {error, duration_ms: 1}}}; }
  const rows = [];
  for await (const row of reporter(events())) rows.push(JSON.parse(row));
  assert.equal(rows[0].data.error.message, "missing prerequisite");
  assert.ok(JSON.stringify(rows).length < 15_000);
  assert.equal(summarizeEvents(rows, 1).tests[0].status, "FAIL");
});
