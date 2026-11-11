import assert from "node:assert/strict";
import {atPointer, copyJson, entityId, occurrenceId, restoreReferences} from "../common/book_schema.mjs";
import {walkJson} from "../common/source_scan.mjs";
import {collectEmbedded} from "../common/tree.mjs";
import {ASSEMBLY_SCHEMA_VERSION, auditRequiredReferences} from "../assembly/assembly_schema.mjs";

/** Stage 4 only: complete source layout and closed required insertions, not domain enrichment. */
export function validateAssemblyBook(document, selection, inventory) {
  const {bookId, book, file, bookIndex} = selection;
  assert.equal(document.schema_version, ASSEMBLY_SCHEMA_VERSION);
  assert.equal(document.artifact_kind, "assembled_book");
  assert.equal(document.stage, 4);
  assert.equal(document.scope.all_source_chapters, true);
  assert.equal(document.scope.embedded_references_resolved, true);
  assert.equal(document.scope.domain_enrichment, false);
  assert.equal(document.scope.book_complete, false);
  assert.equal(document.book.id, bookId);
  assert.equal(document.upstream.checkout_sha, document.upstream.gitlink_sha);
  assert.equal(document.upstream.gitlink_matches_checkout, true);
  assert.equal(document.upstream.tracked_clean, true);
  assert.equal(document.chapters.length, book.data.length);
  const expectedRefs = inventory.references.filter(ref => ref.book_id === bookId && ref.required);
  const refs = new Map(expectedRefs.map(ref => [ref.occurrence_id, ref]));
  const inserted = [];
  const counts = {chapters: book.data.length, source_statblocks: 0, resolved_statblocks: 0, unresolved_required_references: 0, preserved_source_tables: 0, preserved_source_images: 0, generated_items: 0, unknown_entity_pages: 0, cross_book_insertions: 0};
  const props = {};
  const sourcePages = {};
  for (const [i, chapter] of document.chapters.entries()) {
    const original = book.data[i];
    assert.equal(chapter.chapter_index, i);
    assert.equal(chapter.title, original.name);
    assert.equal(chapter.original_id, original.id ?? null);
    assert.equal(chapter.origin.file, file);
    assert.equal(chapter.origin.json_pointer, `/bookData/${bookIndex}/data/${i}`);
    assert.deepEqual(restoreReferences(chapter.content), original, `Source tree/order changed: ${bookId}/${i}`);
    const embedded = collectEmbedded(chapter.content);
    inserted.push(...embedded);
    walkJson(original, (node, relativePointer) => {
      if (node?.type === "table" || node?.type === "tableGroup") counts.preserved_source_tables++;
      if (node?.type === "image") counts.preserved_source_images++;
      if (node?.type !== "statblock") return;
      counts.source_statblocks++;
      const wrapper = atPointer(chapter.content, relativePointer);
      assert.equal(wrapper.occurrence_id, occurrenceId(bookId, i, chapter.origin.json_pointer + relativePointer));
    });
    for (const wrapper of embedded) {
      const expected = refs.get(wrapper.occurrence_id);
      assert.ok(expected, `Unexpected inserted entity ${wrapper.occurrence_id}`);
      assert.equal(wrapper.entity_id, expected.target.entity_id);
      assert.equal(wrapper.entity_id, entityId(wrapper.lookup));
      assert.deepEqual(wrapper.lookup, expected.target);
      assert.deepEqual(wrapper.original_reference, expected.raw);
      assert.deepEqual(wrapper.placement, {book_id: bookId, chapter_index: i, origin: expected.origin});
      assert.equal(wrapper.data.source.toLowerCase(), wrapper.lookup.source.toLowerCase());
      assert.equal(wrapper.entity_origin.source, wrapper.data.source);
      assert.equal(wrapper.entity_origin.printed_page, wrapper.data.page ?? null);
      assert.equal(wrapper.entity_origin.upstream_commit, document.upstream.checkout_sha);
      assert.equal(wrapper.entity_origin.page_attribution, wrapper.data.page == null ? "unknown" : "explicit");
      if (wrapper.entity_origin.file !== null) {
        const record = inventory.byRecord.get(wrapper.entity_origin.record_id);
        assert.ok(record);
        assert.equal(wrapper.entity_origin.file, record.origin.file);
        assert.equal(wrapper.entity_origin.json_pointer, record.origin.json_pointer);
      } else {
        assert.equal(wrapper.entity_origin.json_pointer, null);
        assert.ok(["generated_item", "ambiguous_physical_candidates"].includes(wrapper.entity_origin.lookup_source));
        if (wrapper.entity_origin.lookup_source === "generated_item") {
          assert.equal(wrapper.derivation?.method, "native_item_variant");
          assert.ok(wrapper.derivation.base_item.origins.length && wrapper.derivation.template.origins.length);
          counts.generated_items++;
        }
      }
      assert.deepEqual(auditRequiredReferences(wrapper.data).unresolved, [], `Unresolved entity content: ${wrapper.occurrence_id}`);
      props[wrapper.lookup.prop] = (props[wrapper.lookup.prop] || 0) + 1;
      sourcePages[wrapper.placement.origin.page_attribution] = (sourcePages[wrapper.placement.origin.page_attribution] || 0) + 1;
      counts.unknown_entity_pages += wrapper.data.page == null ? 1 : 0;
      counts.cross_book_insertions += wrapper.data.source.toUpperCase() !== bookId ? 1 : 0;
    }
  }
  assert.equal(inserted.length, expectedRefs.length);
  assert.equal(new Set(inserted.map(wrapper => wrapper.occurrence_id)).size, inserted.length);
  assert.equal(counts.source_statblocks, expectedRefs.filter(ref => ref.kind === "embedded_reference").length);
  counts.resolved_statblocks = inserted.length;
  copyJson(document);
  return {status: "PASS", scope: "stage_4_source_chapters_and_required_insertions", ...counts, props, placement_page_attributions: sourcePages};
}
