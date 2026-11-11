import {execFile} from "node:child_process";
import {readFile, realpath} from "node:fs/promises";
import path from "node:path";
import {promisify} from "node:util";

const exec = promisify(execFile);

async function git(cwd, ...args) {
  const {stdout} = await exec("git", ["-C", cwd, ...args], {timeout: 30_000});
  return stdout.trim();
}

export function assertNodeVersion(engine, version = process.versions.node) {
  const match = /^>=(\d+)$/.exec(engine);
  if (!match) throw new Error(`Unsupported upstream Node.js engine: ${engine}`);
  if (Number(version.split(".")[0]) < Number(match[1])) {
    throw new Error(`5etools requires Node.js ${engine}; active: ${version}. Use the local Node.js runtime in tools/ingestion/node_modules/.bin/node.`);
  }
}

/** Validate the committed gitlink, never the index. Does not mutate Git state. */
export async function inspectSnapshot(projectRoot, upstreamPath) {
  let upstream;
  try {
    upstream = await realpath(upstreamPath);
  } catch (error) {
    if (error.code === "ENOENT") throw new Error(`Upstream not found: ${upstreamPath}. Run git submodule update --init --recursive.`);
    throw error;
  }
  const repositoryRoot = await git(projectRoot, "rev-parse", "--show-toplevel");
  const gitlinkPath = path.relative(repositoryRoot, upstream).split(path.sep).join("/");
  if (gitlinkPath === ".." || gitlinkPath.startsWith("../") || !gitlinkPath) {
    throw new Error("Upstream must be a registered submodule inside the main Git repository.");
  }
  const entry = await git(repositoryRoot, "ls-tree", "HEAD", "--", gitlinkPath);
  const match = /^160000 commit ([0-9a-f]{40,64})\t/.exec(entry);
  if (!match) throw new Error(`No committed gitlink in HEAD for ${gitlinkPath}. Commit the submodule registration first.`);
  const checkoutRoot = await git(upstream, "rev-parse", "--show-toplevel");
  if (await realpath(checkoutRoot) !== upstream) {
    throw new Error("Submodule is not initialized. Run git submodule update --init --recursive.");
  }
  const checkoutSha = await git(upstream, "rev-parse", "HEAD");
  if (checkoutSha !== match[1]) {
    throw new Error(`Submodule checkout ${checkoutSha} differs from gitlink in HEAD ${match[1]}. Commit the updated gitlink in the main project, or restore it with git submodule update --init --recursive. Staging alone is insufficient.`);
  }
  const changes = await git(upstream, "status", "--porcelain=v1", "--untracked-files=no");
  if (changes) throw new Error(`Upstream has modified tracked files (including staged changes):\n${changes}`);
  const pkg = JSON.parse(await readFile(path.join(upstream, "package.json"), "utf8"));
  return {
    upstream,
    repository_root: repositoryRoot,
    gitlink_path: gitlinkPath,
    checkout_sha: checkoutSha,
    gitlink_sha: match[1],
    gitlink_matches_checkout: true,
    tracked_clean: true,
    package_version: pkg.version,
    node_engine: pkg.engines?.node,
  };
}
