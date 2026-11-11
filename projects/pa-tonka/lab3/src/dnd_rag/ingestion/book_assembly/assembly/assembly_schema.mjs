import {copyJson, pointerToken} from "../common/book_schema.mjs";

export const ASSEMBLY_SCHEMA_VERSION = "0.2.0";
export const ASSEMBLY_VERSION = "0.4.0";
const OPTIONAL_BASE_FLAGS = new Set(["_baseSrd", "_baseSrd52", "_baseBasicRules", "_baseFreeRules2024", "_baseValue"]);

/** Only documented native cache fields may be omitted; source/game data stays intact. */
export function serializeLoaderData(entity, {sourceRecords = [], pointer = "", onOmission = () => {}} = {}) {
  const ancestors = new Set();
  function clone(value, position, owner = null, key = null) {
    if (value === undefined && owner?.__prop === "item" && owner?._category === "Specific Variant" && OPTIONAL_BASE_FLAGS.has(key)) {
      onOmission({kind: "undefined_runtime_flag", path: position, property: key});
      return undefined;
    }
    if (!value || typeof value !== "object") return copyJson(value, position);
    if (ancestors.has(value)) throw new Error(`Cyclic loader data at ${position}`);
    const proto = Object.getPrototypeOf(value);
    if (!Array.isArray(value) && proto !== Object.prototype && proto !== null) return copyJson(value, position);
    if (Object.getOwnPropertySymbols(value).some(key => Object.getOwnPropertyDescriptor(value, key).enumerable)) throw new Error(`Symbol key in loader data at ${position}`);
    ancestors.add(value);
    try {
      if (Array.isArray(value)) {
        if (Object.keys(value).length !== value.length) throw new Error(`Non-JSON array properties at ${position}`);
        return Array.from({length: value.length}, (_, i) => clone(value[i], `${position}/${i}`));
      }
      const result = {};
      for (const [field, child] of Object.entries(value)) {
        const childPointer = `${position}/${pointerToken(field)}`;
        if (field === "variants") {
          if (value.__prop !== "magicvariant" || value._category !== "Generic Variant" || !Array.isArray(child) || !child.every(row => row.base && row.specificVariant) || sourceRecords.some(record => record.fields.includes("variants"))) throw new Error(`Unrecognized/source-defined variants field at ${childPointer}`);
          onOmission({kind: "native_generated_variant_cache", path: childPointer, property: field, combinations: child.length});
          continue;
        }
        const copied = clone(child, childPointer, value, field);
        if (copied !== undefined) Object.defineProperty(result, field, {value: copied, enumerable: true, writable: true, configurable: true});
      }
      return result;
    } finally { ancestors.delete(value); }
  }
  return copyJson(clone(entity, pointer), pointer);
}

/** Required executable references must be absent; raw variant recipes remain labeled. */
export function auditRequiredReferences(value, pointer = "") {
  const unresolved = [];
  const templates = [];
  function walk(node, position, template = false) {
    if (node && typeof node === "object") {
      if (node.type === "statblock" || (node.type === "statblockInline" && !node.statblockData) || /^ref[A-Z]/.test(node.type || "") || Object.hasOwn(node, "_copy")) {
        (template ? templates : unresolved).push({path: position, type: node.type || "_copy"});
      }
      for (const [key, child] of Object.entries(node)) walk(child, `${position}/${pointerToken(key)}`, template || ["_versions", "entriesTemplate", "_mod"].includes(key));
    } else if (typeof node === "string" && node.includes("{#")) {
      (template ? templates : unresolved).push({path: position, type: "structural_string_reference", raw: node});
    }
  }
  walk(value, pointer);
  return {unresolved, templates};
}
