import {entityId, pointerToken} from "../common/book_schema.mjs";

const ITEM_PROPS = new Set(["baseitem", "itemGroup", "magicvariant"]);
const REF_PROPS = {refClassFeature: "classFeature", refSubclassFeature: "subclassFeature", refOptionalfeature: "optionalfeature", refFeat: "feat", refItemEntry: "itemEntry"};

/** Metadata only: UID/hash semantics and tag tokenization stay in upstream. */
export function createInventoryApi() {
  const rendererTypes = new Set(["section", ...Renderer.ENTRIES_WITH_CHILDREN.map(row => row.type), ...[...Renderer.get()._recursiveRender.toString().matchAll(/case "([^"]+)"/g)].map(match => match[1])]);
  if (!rendererTypes.has("statblock") || !Array.isArray(DataLoader._DATA_TYPE_LOADER_LIST)) throw new Error("Upstream inventory API changed: inspect renderer/loader registry again.");
  const loaders = DataLoader._DATA_TYPE_LOADER_LIST.map(loader => ({
    name: loader.constructor.name, props: [...loader.constructor.PROPS],
    lookup_page: loader.constructor.PAGE ?? null, filename: loader._filename ? `data/${loader._filename}` : null,
  }));
  const loaderProps = new Set(loaders.flatMap(loader => loader.props));

  function lookup(prop, entity) {
    const lookupProp = ITEM_PROPS.has(prop) ? "item" : prop === "bookData" ? "book" : prop;
    const builder = UrlUtil.getHashBuilder(lookupProp);
    if (!builder) throw new Error(`No upstream hash builder for ${lookupProp}`);
    const source = entity.source || entity.inherits?.source;
    if (!source) throw new Error(`Missing source for ${prop}`);
    const hash = builder({...entity, source});
    return {prop: lookupProp, source, hash, lookup_page: Renderer.tag.getPage(Parser.getPropTag(lookupProp), {isHover: true}) || DataLoader.getPropPage(lookupProp) || lookupProp, entity_id: entityId({prop: lookupProp, source, hash})};
  }
  function uidLookup(prop, uid, tag = Parser.getPropTag(prop) || prop) {
    const unpacked = DataUtil.proxy.unpackUid(prop, uid, tag);
    return {...lookup(prop, unpacked), uid};
  }
  function statblockLookup(node) {
    const meta = Renderer.utils.getStatblockEntryMeta(node);
    return {prop: meta.prop, source: meta.source, hash: meta.hash, lookup_page: meta.page, uid: meta.uid ?? null, entity_id: entityId(meta)};
  }
  function structural(node) {
    const prop = REF_PROPS[node.type];
    if (!prop) throw new Error(`Unknown required reference type ${node.type}`);
    return uidLookup(prop, node[prop]);
  }

  function tags(text) {
    const result = [];
    function parse(value, offset = 0, parent = null) {
      let cursor = offset;
      for (const chunk of Renderer.splitByTags(value)) {
        const start = cursor;
        cursor += chunk.length;
        if (!chunk.startsWith("{@") && !chunk.startsWith("{=")) continue;
        const span = {start, end: cursor, unit: "utf16_code_unit"};
        if (!chunk.endsWith("}")) {
          result.push({kind: "malformed_tag", raw: chunk, span, parent_start: parent});
          continue;
        }
        if (chunk.startsWith("{=")) {
          result.push({kind: "template_tag", raw: chunk, span, parent_start: parent});
          continue;
        }
        const [tagWithAt, body] = Renderer.splitFirstSpace(chunk.slice(1, -1));
        const tag = tagWithAt.slice(1);
        const info = Renderer.tag.getTagInfo(tag);
        const row = {kind: "formatting_tag", tag, raw: chunk, span, parent_start: parent};
        if (!info) row.kind = "unknown_tag";
        else if (info.defaultSource) {
          row.kind = "entity_reference";
          try { row.target = uidLookup(Parser.getTagProps(tag)[0], body, tag); }
          catch (error) { row.kind = "unparsed_entity_reference"; row.error = error.message; }
        } else if (tag === "filter") {
          row.kind = "query_reference";
          const [display, page, ...filters] = Renderer.splitTagByPipe(body);
          row.query = {display, page: page ?? null, filters};
        } else if (["book", "adventure"].includes(tag)) {
          row.kind = "document_reference";
          row.document = UidUtil.unpackUidAdventureBook(body);
          // Keep only defined metadata; upstream also returns runtime optionals.
          row.document = {id: row.document.id ?? null, chapter_index: row.document.ixChapter ?? null, section: row.document.sectionName ?? null};
        } else if (["area", "5etools", "link"].includes(tag)) row.kind = "navigation_reference";
        result.push(row);
        const space = chunk.indexOf(" ");
        if (space >= 0) parse(body, start + space + 1, start);
      }
    }
    parse(text);
    return result;
  }
  function stringRefs(text) {
    const result = [];
    const starts = new Set();
    for (const match of text.matchAll(/\{#([^{}]+)\}/g)) {
      starts.add(match.index);
      const [prop, uid] = Renderer.splitFirstSpace(match[1]);
      const type = `ref${prop[0]?.toUpperCase() || ""}${prop.slice(1)}`;
      const row = {kind: "structural_reference", raw: match[0], span: {start: match.index, end: match.index + match[0].length, unit: "utf16_code_unit"}};
      try { row.target = structural({type, [prop]: uid}); }
      catch (error) { row.error = error.message; }
      result.push(row);
    }
    for (let start = text.indexOf("{#"); start >= 0; start = text.indexOf("{#", start + 2)) {
      if (!starts.has(start)) result.push({kind: "structural_reference", raw: text.slice(start), span: {start, end: text.length, unit: "utf16_code_unit"}, error: "Malformed structural reference"});
    }
    return result;
  }
  const entryFields = new Set([...DataUtil.generic.COPY_ENTRY_PROPS, "entry", "images", "classTableGroups", "subclassTableGroups", "lairActions", "regionalEffects", "mythicEncounter"]);
  function auditEntryTypes(value) {
    const unknown = [];
    function walk(node, pointer, inEntry = false) {
      if (!node || typeof node !== "object") return;
      if (!Array.isArray(node) && inEntry && typeof node.type === "string" && classifyType(node.type, pointer) === "unknown") unknown.push({path: pointer, type: node.type});
      for (const [key, child] of Object.entries(node)) {
        // Inline statblocks contain a new entity, whose range/duration/item type
        // belongs to its rules schema rather than to the renderer entry grammar.
        const childIsEntry = key === "statblockData" ? false : inEntry || entryFields.has(key) || /entries/i.test(key);
        walk(child, `${pointer}/${pointerToken(key)}`, childIsEntry);
      }
    }
    walk(value, "");
    return unknown;
  }
  function classifyType(type, pointer) {
    if (/^ref[A-Z]/.test(type)) return Object.hasOwn(REF_PROPS, type) ? "required_reference" : "unknown_required_reference";
    if (rendererTypes.has(type)) return "render_entry";
    if (["row", "cell", "cellHeader"].includes(type)) return "table_structure";
    if (/\/(?:href|hrefThumbnail)(?:\/|$)/.test(pointer) && ["internal", "external"].includes(type)) return "link_metadata";
    if (/\/grid(?:\/|$)/.test(pointer) && ["square", "hexColsEven", "hexColsOdd", "hexRowsEven", "hexRowsOdd", "none"].includes(type)) return "map_grid_metadata";
    return "unknown";
  }
  return {
    loaders, loaderProps, rendererTypes, lookup, uidLookup, statblockLookup, structural, tags, stringRefs,
    classifyType, auditEntryTypes,
    async probe(target) {
      const entity = await DataLoader.pCacheAndGet(target.lookup_page, target.source, target.hash, {isRequired: true});
      if (!entity) throw new Error("Loader returned no entity");
      if (entity.source.toLowerCase() !== target.source.toLowerCase()) throw new Error(`Loader returned source ${entity.source}, expected ${target.source}`);
      return {status: "FOUND", name: entity.name ?? null, source: entity.source, printed_page: entity.page ?? null, prop: entity.__prop ?? target.prop, base_item: entity.baseItem ?? null};
    },
  };
}
