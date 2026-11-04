import {mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile} from "node:fs/promises";
import path from "node:path";

export async function outsideUpstream(directory, upstream) {
  let current = path.resolve(directory);
  const suffix = [];
  while (true) {
    try { current = await realpath(current); break; }
    catch (error) {
      if (error.code !== "ENOENT") throw error;
      suffix.unshift(path.basename(current));
      const parent = path.dirname(current);
      if (parent === current) throw error;
      current = parent;
    }
  }
  const result = path.join(current, ...suffix);
  const relative = path.relative(upstream, result);
  if (!relative || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative))) throw new Error("Outputs must be outside upstream.");
  return result;
}

export async function publishArtifacts(directory, artifacts) {
  let exists = false;
  try { await realpath(directory); exists = true; }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  if (exists) {
    for (const [name, bytes] of Object.entries(artifacts)) if (await readFile(path.join(directory, name), "utf8") !== bytes) throw new Error(`Existing artifact differs: ${directory}/${name}; refusing to overwrite.`);
    return "unchanged";
  }
  await mkdir(path.dirname(directory), {recursive: true});
  const temporary = await mkdtemp(path.join(path.dirname(directory), ".inventory-"));
  try {
    for (const [name, bytes] of Object.entries(artifacts)) {
      if (path.basename(name) !== name) throw new Error(`Artifact filename must be a basename: ${name}`);
      await writeFile(path.join(temporary, name), bytes, "utf8");
    }
    await rename(temporary, directory);
  } finally { await rm(temporary, {recursive: true, force: true}); }
  return "created";
}
