import {readFile} from "node:fs/promises";
import path from "node:path";

export const BOOK_IDS = ["XPHB", "XDMG", "XMM"];

export async function readJson(root, file) {
  return JSON.parse((await readFile(path.join(root, file), "utf8")).replace(/^\uFEFF/, ""));
}

export function selectUnique(records, id, context) {
  const matches = records.filter(record => record.id === id);
  if (matches.length !== 1) throw new Error(`${context}: expected one ${id}, found ${matches.length}`);
  return matches[0];
}

function pointerToken(value) {
  return String(value).replace(/~/g, "~0").replace(/\//g, "~1");
}

/** Walk all fields, including data outside entries. Paths are JSON Pointers. */
export function walkJson(value, visit, pointer = "") {
  visit(value, pointer);
  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      walkJson(child, visit, `${pointer}/${pointerToken(key)}`);
    }
  }
}
