import {readJson, selectUnique, walkJson, BOOK_IDS} from "../book_assembly/common/source_scan.mjs";

function increment(counts, key) {
  counts[key] = (counts[key] || 0) + 1;
}

export async function scanBooks(root) {
  const catalog = await readJson(root, "data/books.json");
  const books = [];
  for (const id of BOOK_IDS) {
    const entry = selectUnique(catalog.book, id, "data/books.json");
    const file = `data/book/book-${id.toLowerCase()}.json`;
    const raw = await readJson(root, file);
    const book = selectUnique(raw.bookData, id, file);
    if (book.source !== id) throw new Error(`${file}: source ${book.source} differs from ${id}`);
    if (book.data.length !== entry.contents.length) throw new Error(`${id}: catalog/chapter count differs`);
    const bookIndex = raw.bookData.indexOf(book);
    const types = {};
    const statblocks = {};
    const sources = {};
    const textTags = {};
    const examples = {};
    const chapters = [];
    for (const [index, chapter] of book.data.entries()) {
      const chapterTypes = {};
      const prefix = `/bookData/${bookIndex}/data/${index}`;
      walkJson(chapter, (node, pointer) => {
        if (typeof node === "string") {
          for (const match of node.matchAll(/\{@([\w]+)(?:\s|\})/g)) increment(textTags, match[1]);
        }
        if (!node || typeof node !== "object" || Array.isArray(node)) return;
        if (typeof node.type === "string") {
          increment(types, node.type);
          increment(chapterTypes, node.type);
        }
        if (node.type !== "statblock") return;
        const route = node.prop || node.tag;
        increment(statblocks, route);
        increment(sources, node.source || "<default>");
        examples[route] ||= {book_id: id, chapter_index: index, file, json_pointer: pointer, reference: node};
      }, prefix);
      const catalogTitle = entry.contents[index].name;
      const unnumberedTitle = chapter.name.replace(/^(?:Chapter \d+|Appendix [A-Z]): /, "");
      chapters.push({
        index, catalog_title: catalogTitle, source_title: chapter.name,
        title_matches_after_removing_number: unnumberedTitle === catalogTitle,
        printed_page: chapter.page ?? null,
        json_pointer: prefix, types: chapterTypes,
      });
    }
    books.push({id, title: entry.name, published: entry.published, file, chapters, types, statblocks, statblock_sources: sources, text_tags: textTags, route_examples: examples});
  }
  return books;
}

export async function scanClassSources(root) {
  const index = await readJson(root, "data/class/index.json");
  const classes = [];
  const subclasses = [];
  for (const name of [...new Set(Object.values(index))].sort()) {
    const file = `data/class/${name}`;
    const data = await readJson(root, file);
    for (const [i, entity] of (data.class || []).entries()) {
      if (entity.source === "XPHB") classes.push({name: entity.name, source: entity.source, file, json_pointer: `/class/${i}`, table_groups: entity.classTableGroups?.length || 0});
    }
    for (const [i, entity] of (data.subclass || []).entries()) {
      if (entity.source === "XPHB" && entity.classSource === "XPHB") subclasses.push({name: entity.name, short_name: entity.shortName, source: entity.source, class_name: entity.className, file, json_pointer: `/subclass/${i}`});
    }
  }
  return {classes, subclasses};
}
