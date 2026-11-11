/** Machine events alongside Node's spec reporter; never stringify whole failed books. */
export default async function* reporter(source) {
  for await (const {type, data} of source) {
    if (type === "test:summary") yield `${JSON.stringify({type, data})}\n`;
    if (!["test:pass", "test:fail"].includes(type)) continue;
    const error = data.details?.error;
    yield `${JSON.stringify({type, data: {
      name: data.name, file: data.file ?? null, line: data.line ?? null,
      nesting: data.nesting, test_id: data.testId ?? null, parent_id: data.parentId ?? null,
      kind: data.details?.type || "test", duration_ms: data.details?.duration_ms ?? null,
      skip: data.skip ?? false, todo: data.todo ?? false,
      error: error ? {message: String(error.cause?.message || error.message).slice(0, 8000), stack: String(error.cause?.stack || error.stack).slice(0, 12000)} : null,
    }})}\n`;
  }
}
