import fs from "node:fs";
import path from "node:path";
import {pathToFileURL} from "node:url";

/** One upstream per process: upstream keeps globals, prototype helpers and caches. */
let initialized = false;

export function localJsonPath(root, url) {
  if (typeof url !== "string" || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(url)) {
    throw new Error(`Only local upstream JSON is allowed: ${url}`);
  }
  const file = fs.realpathSync(path.resolve(root, url));
  const relative = path.relative(root, file);
  if (relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative) || !relative.endsWith(".json")) {
    throw new Error(`JSON path escapes upstream or is not JSON: ${url}`);
  }
  return relative.split(path.sep).join("/");
}

export async function openUpstreamRuntime(root) {
  if (initialized) throw new Error("Upstream runtime already initialized; use a separate process.");
  initialized = true;
  const originalCwd = process.cwd();
  const files = new Set();
  const modules = [
    "js/parser.js", "js/utils.js", "js/utils-config.js", "js/render.js",
    "js/render-dice.js", "js/hist.js", "js/utils-dataloader.js",
  ];
  const guardedLoaders = {};
  let util;
  try {
    process.chdir(root);
    for (const file of modules) await import(pathToFileURL(path.join(root, file)).href);
    util = await import(pathToFileURL(path.join(root, "node/util.js")).href);
    util.patchLoadJson();
    for (const key of ["loadJSON", "loadRawJSON"]) {
      const original = DataUtil[key].bind(DataUtil);
      guardedLoaders[key] = original;
      DataUtil[key] = async (url, ...args) => {
        files.add(localJsonPath(root, url));
        return original(url, ...args);
      };
    }
  } catch (error) {
    if (util) util.unpatchLoadJson();
    process.chdir(originalCwd);
    throw error;
  }
  return {
    modules,
    get loadedFiles() { return [...files].sort(); },
    close() {
      for (const [key, original] of Object.entries(guardedLoaders)) DataUtil[key] = original;
      util.unpatchLoadJson();
      process.chdir(originalCwd);
    },
  };
}
