import {readFile, readdir} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {sha256} from "./book_schema.mjs";

export const projectRoot = fileURLToPath(new URL("../../../../../", import.meta.url));
export const codeRoot = fileURLToPath(new URL("../", import.meta.url));
export const defaultDiagnosticsRoot = path.join(projectRoot, ".cache/ingestion/diagnostics/5etools");

/** Report keys are relative code paths, never arbitrary filesystem inputs. */
export function adapterPath(project, file) {
  if (typeof file !== "string" || !file || path.isAbsolute(file) || file.split(/[\\/]/).some(part => !part || part === "." || part === "..")) throw new Error(`Invalid adapter filename: ${file}`);
  return path.join(project, "src/dnd_rag/ingestion/book_assembly", file);
}

/** Stable identity must be available before creating temporary prerequisites. */
export async function adapterHashes() {
  const files = [];
  async function collect(directory = "") {
    for (const entry of await readdir(path.join(codeRoot, directory), {withFileTypes: true})) {
      const file = path.posix.join(directory, entry.name);
      if (entry.isDirectory() && entry.name !== "__pycache__") await collect(file);
      else if (entry.isFile() && /\.(?:mjs|json|py)$/.test(entry.name)) files.push(file);
    }
  }
  await collect();
  return Object.fromEntries(await Promise.all(files.sort().map(async file => [file, sha256(await readFile(path.join(codeRoot, file)))])));
}
