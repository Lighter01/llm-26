import {execFile} from "node:child_process";
import {lstat, mkdir, mkdtemp, open, readFile, readdir, rename, rm, rmdir} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";

const exec = promisify(execFile);
export const exchangeHelper = fileURLToPath(new URL("./atomic_exchange.py", import.meta.url));

export async function buildExists(directory) {
  try {
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`Build path must be a real directory: ${directory}`);
    return true;
  } catch (error) { if (error.code === "ENOENT") return false; throw error; }
}

export async function withBuildLock(directory, action, {removeEmptyParent = false} = {}) {
  const parent = path.dirname(directory);
  await mkdir(parent, {recursive: true});
  if ((await lstat(parent)).isSymbolicLink()) throw new Error("Snapshot output directory must not be a symlink");
  const lock = path.join(parent, `.${path.basename(directory)}.lock`);
  try { await mkdir(lock); }
  catch (error) { if (error.code === "EEXIST") throw new Error(`Build is locked: ${lock}`); throw error; }
  try { return await action(); }
  finally {
    await rm(lock, {recursive: true, force: true});
    // A failed first build must not leave an empty snapshot directory in data/.
    if (removeEmptyParent) {
      try { await rmdir(parent); }
      catch (error) { if (!["ENOTEMPTY", "EEXIST", "ENOENT"].includes(error.code)) throw error; }
    }
  }
}

export async function assertOwnedBuild(directory, {buildId, signature, upstreamSha, files}) {
  await buildExists(directory);
  const manifest = JSON.parse(await readFile(path.join(directory, "manifest.json"), "utf8"));
  if (manifest.build_id !== buildId || manifest.assembler.signature !== signature || manifest.upstream.checkout_sha !== upstreamSha) throw new Error("Refusing to replace a different build identity");
  for (const entry of await readdir(directory, {withFileTypes: true})) {
    if (!files.includes(entry.name) || !entry.isFile() || entry.isSymbolicLink()) throw new Error(`Refusing to replace an unexpected build entry: ${entry.name}`);
  }
}

async function syncDirectory(directory) {
  const handle = await open(directory, "r");
  try { await handle.sync(); } finally { await handle.close(); }
}

/** Fully verified staging -> one atomic create/exchange. No partial live build. */
export async function publishResolved(directory, artifacts, {force, identity, verify, exchange = async (temporary, target) => {
  await exec("python3", [exchangeHelper, path.dirname(target), path.basename(temporary), path.basename(target)], {timeout: 30_000});
}}) {
  const exists = await buildExists(directory);
  if (exists && !force) throw new Error("Build already exists; use --force for a verified replacement");
  const files = Object.keys(artifacts);
  if (exists) await assertOwnedBuild(directory, {...identity, files});
  await mkdir(path.dirname(directory), {recursive: true});
  const temporary = await mkdtemp(path.join(path.dirname(directory), `.${path.basename(directory)}.staging-`));
  let published = false;
  try {
    for (const [file, bytes] of Object.entries(artifacts)) {
      if (path.basename(file) !== file) throw new Error("Output filename must be a basename");
      const handle = await open(path.join(temporary, file), "wx");
      try { await handle.writeFile(bytes, "utf8"); await handle.sync(); }
      finally { await handle.close(); }
    }
    await syncDirectory(temporary);
    await verify(temporary);
    if (exists) {
      await assertOwnedBuild(directory, {...identity, files});
      const stagedInfo = await lstat(temporary);
      try { await exchange(temporary, directory); }
      catch (error) {
        const current = await lstat(directory);
        if (current.dev !== stagedInfo.dev || current.ino !== stagedInfo.ino) throw error;
        console.warn(`Exchange committed before helper exit: ${error.message}`);
      }
    } else {
      if (await buildExists(directory)) throw new Error("Build appeared during publication; refusing overwrite");
      await rename(temporary, directory);
    }
    published = true;
    // Publication is already committed. Cleanup errors cannot turn it into a FAIL.
    try { await syncDirectory(path.dirname(directory)); }
    catch (error) { console.warn(`Published build; parent sync warning: ${error.message}`); }
    return exists ? "replaced" : "created";
  } finally {
    try { await rm(temporary, {recursive: true, force: true}); }
    catch (error) { if (!published) throw error; console.warn(`Published build; old staging cleanup warning: ${error.message}`); }
  }
}
