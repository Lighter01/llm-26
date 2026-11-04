import {BOOK_IDS, readJson, selectUnique} from "../common/source_scan.mjs";
import {copyJson, occurrenceId, origin, pageContext, pointerToken, sha256, canonicalJson} from "../common/book_schema.mjs";

const TITLE_ALIASES = [{book: "XMM", index: 0, catalog: "Introduction", chapter: "How to Use a Monster"}];

export async function inventoryBooks(root, commit, api, issues) {
  const catalog = await readJson(root, "data/books.json");
  const books = [];
  const nodes = [];
  const references = [];
  function issue(code, message, context, severity = "ERROR") { issues.push({severity, code, message, ...context}); }
  for (const bookId of BOOK_IDS) {
    const catalogEntry = selectUnique(catalog.book, bookId, "data/books.json");
    const file = `data/book/book-${bookId.toLowerCase()}.json`;
    const raw = await readJson(root, file);
    const book = selectUnique(raw.bookData, bookId, file);
    if (book.source !== bookId || book.data.length !== catalogEntry.contents.length) throw new Error(`${bookId}: invalid source or catalog/chapter count`);
    const chapters = [];
    const counts = {nodes: 0, statblocks: 0, structured_references: 0, inline_entities: 0, text_tags: 0, tables: 0, images: 0, unknown_types: 0};
    const routes = {};
    for (const [chapterIndex, chapter] of book.data.entries()) {
      const pointer = `/bookData/${raw.bookData.indexOf(book)}/data/${chapterIndex}`;
      const context = {book_id: bookId, chapter_index: chapterIndex};
      const catalogTitle = catalogEntry.contents[chapterIndex].name;
      const matches = chapter.name.replace(/^(?:Chapter \d+|Appendix [A-Z]): /, "") === catalogTitle;
      const alias = TITLE_ALIASES.some(a => a.book === bookId && a.index === chapterIndex && a.catalog === catalogTitle && a.chapter === chapter.name);
      if (!matches) issue(alias ? "KNOWN_CATALOG_TITLE_ALIAS" : "CATALOG_TITLE_MISMATCH", `${catalogTitle} / ${chapter.name}`, {...context, file, json_pointer: pointer}, alias ? "INFO" : "ERROR");
      const chapterCounts = {nodes: 0, statblocks: 0, structured_references: 0, inline_entities: 0, text_tags: 0, tables: 0, images: 0, unknown_types: 0};
      function count(key) { counts[key]++; chapterCounts[key]++; }
      function walk(value, position, inherited = null) {
        const page = pageContext(value, position, inherited);
        const nodeOrigin = origin({file, pointer: position, source: bookId, commit, page});
        const occurrence = occurrenceId(bookId, chapterIndex, position);
        const row = {occurrence_id: occurrence, ...context, origin: nodeOrigin, value_kind: value === null ? "null" : Array.isArray(value) ? "array" : typeof value, raw_sha256: sha256(canonicalJson(value))};
        count("nodes");
        if (value && typeof value === "object" && !Array.isArray(value)) {
          row.type = typeof value.type === "string" ? value.type : null;
          row.name = typeof value.name === "string" ? value.name : null;
          row.original_id = value.id ?? null;
          row.type_classification = row.type ? api.classifyType(row.type, position) : "untyped_object";
          if (["unknown", "unknown_required_reference"].includes(row.type_classification)) {
            count("unknown_types"); issue("UNKNOWN_BOOK_TYPE", `Unclassified type ${row.type}`, {...context, file, json_pointer: position, type: row.type});
          }
          if (value.type === "table" || value.type === "tableGroup" || value.type === "image") {
            row.payload = copyJson(value);
            count(value.type === "image" ? "images" : "tables");
          }
          if (value.type === "statblock" || value.type === "statblockInline" || /^ref[A-Z]/.test(value.type || "")) {
            const kind = value.type === "statblock" ? "embedded_reference" : value.type === "statblockInline" ? "inline_entity" : "structural_reference";
            const ref = {reference_id: `${occurrence}:required`, occurrence_id: occurrence, ...context, origin: nodeOrigin, kind, required: true, raw: copyJson(value)};
            try {
              if (kind === "embedded_reference") ref.target = api.statblockLookup(value);
              else if (kind === "inline_entity") ref.target = api.lookup(value.statblockType, value.statblockData);
              else ref.target = api.structural(value);
            } catch (error) {
              ref.error = error.message; issue("INVALID_REQUIRED_REFERENCE", error.message, {...context, file, json_pointer: position, reference: value});
            }
            references.push(ref);
            count(kind === "embedded_reference" ? "statblocks" : kind === "inline_entity" ? "inline_entities" : "structured_references");
            if (ref.target) routes[ref.target.prop] = (routes[ref.target.prop] || 0) + 1;
          }
        } else if (typeof value === "string") {
          for (const tag of [...api.tags(value), ...api.stringRefs(value)]) {
            const ref = {reference_id: `${occurrence}:text:${tag.span?.start ?? 0}:${tag.span?.end ?? value.length}:${tag.kind}`, occurrence_id: occurrence, ...context, origin: nodeOrigin, required: tag.kind === "structural_reference", ...tag};
            references.push(ref);
            count(tag.kind === "structural_reference" ? "structured_references" : "text_tags");
            if (["unknown_tag", "malformed_tag", "unparsed_entity_reference"].includes(tag.kind) || tag.error) issue("UNCLASSIFIED_REFERENCE", tag.error || tag.kind, {...context, file, json_pointer: position, raw: tag.raw});
          }
        }
        nodes.push(row);
        if (value && typeof value === "object") for (const [key, child] of Object.entries(value)) walk(child, `${position}/${pointerToken(key)}`, page);
      }
      walk(chapter, pointer);
      chapters.push({chapter_index: chapterIndex, name: chapter.name, catalog_name: catalogTitle, original_id: chapter.id ?? null, catalog_title_status: matches ? "MATCH" : alias ? "DOCUMENTED_ALIAS" : "MISMATCH", origin: origin({file, pointer, source: bookId, commit, page: pageContext(chapter, pointer)}), counts: chapterCounts});
    }
    books.push({id: bookId, name: catalogEntry.name, file, catalog_origin: {file: "data/books.json", json_pointer: `/book/${catalog.book.indexOf(catalogEntry)}`}, chapters, counts, required_routes: routes});
  }
  return {books, nodes, references};
}
