import {createHash} from "node:crypto";

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

/** Reject silent JSON losses rather than stripping unknown loader properties. */
export function copyJson(value, pointer = "", ancestors = new Set()) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "object" || value === null) throw new Error(`Non-JSON value at ${pointer || "/"}: ${typeof value}`);
  if (ancestors.has(value)) throw new Error(`Cyclic JSON value at ${pointer || "/"}`);
  const prototype = Object.getPrototypeOf(value);
  if (!Array.isArray(value) && prototype !== Object.prototype && prototype !== null) throw new Error(`Non-JSON object at ${pointer || "/"}: ${value.constructor?.name}`);
  if (Object.getOwnPropertySymbols(value).some(key => Object.getOwnPropertyDescriptor(value, key).enumerable)) throw new Error(`Symbol key at ${pointer || "/"}`);
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      const result = [];
      for (let i = 0; i < value.length; i++) result.push(copyJson(value[i], `${pointer}/${i}`, ancestors));
      if (Object.keys(value).length !== value.length) throw new Error(`Non-JSON array properties at ${pointer || "/"}`);
      return result;
    }
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, copyJson(child, `${pointer}/${pointerToken(key)}`, ancestors)]));
  } finally {
    ancestors.delete(value);
  }
}

export function canonicalJson(value) {
  function ordered(node) {
    if (Array.isArray(node)) return node.map(ordered);
    if (node && typeof node === "object") return Object.fromEntries(Object.keys(node).sort().map(key => [key, ordered(node[key])]));
    return node;
  }
  return JSON.stringify(ordered(copyJson(value)));
}

export function serializeJson(value) {
  return `${JSON.stringify(copyJson(value), null, 2)}\n`;
}

export function pointerToken(value) {
  return String(value).replace(/~/g, "~0").replace(/\//g, "~1");
}

export function atPointer(value, pointer) {
  if (!pointer) return value;
  if (!pointer.startsWith("/")) throw new Error(`Invalid JSON Pointer: ${pointer}`);
  return pointer.slice(1).split("/").reduce((node, token) => {
    const key = token.replace(/~1/g, "/").replace(/~0/g, "~");
    if (node === null || typeof node !== "object" || !Object.hasOwn(node, key)) throw new Error(`Missing JSON Pointer: ${pointer}`);
    return node[key];
  }, value);
}

export function occurrenceId(bookId, chapterIndex, pointer) {
  if (!Number.isSafeInteger(chapterIndex) || chapterIndex < 0 || !pointer.startsWith("/")) throw new Error("Invalid occurrence position");
  return `occurrence:${encodeURIComponent(bookId.toUpperCase())}:chapter:${chapterIndex}:${encodeURIComponent(pointer)}`;
}

export function entityId({prop, source, hash}) {
  if (![prop, source, hash].every(value => typeof value === "string" && value.length)) throw new Error("Entity identity requires prop, source and upstream hash");
  return `entity:${[prop, source, hash].map(value => encodeURIComponent(value.toLowerCase())).join(":")}`;
}

export function pageContext(node, pointer, inherited = null) {
  if (node?.page === undefined || node.page === null) return inherited;
  if (!Number.isSafeInteger(node.page) || node.page < 0) throw new Error(`Invalid printed page at ${pointer}: ${node.page}`);
  return {printed_page: node.page, json_pointer: pointer};
}

export function origin({file, pointer, source, commit, page = null}) {
  return {
    file, json_pointer: pointer, source, upstream_commit: commit,
    printed_page: page?.printed_page ?? null,
    page_attribution: !page ? "unknown" : page.json_pointer === pointer ? "explicit" : "inherited_section_start",
    page_origin_pointer: page?.json_pointer ?? null,
  };
}

/** Project an enriched chapter back to its exact source tree. */
export function restoreReferences(node) {
  if (Array.isArray(node)) return node.map(restoreReferences);
  if (!node || typeof node !== "object") return node;
  if (node.kind === "embedded_entity") return copyJson(node.original_reference);
  return Object.fromEntries(Object.entries(node).map(([key, child]) => [key, restoreReferences(child)]));
}
