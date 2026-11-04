/** Stop at wrappers; their entity payload is not part of the source book tree. */
export function collectEmbedded(node, result = []) {
  if (!node || typeof node !== "object") return result;
  if (node.kind === "embedded_entity") {
    result.push(node);
    return result;
  }
  for (const child of Object.values(node)) collectEmbedded(child, result);
  return result;
}
