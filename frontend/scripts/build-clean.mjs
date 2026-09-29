// Builds into NEXT_DIST_DIR from a clean directory, and tries once more if
// the first attempt fails.
//
// Why: the build downloads the fonts, and it keeps a cache in the build
// directory. A network blip, or a build directory that a file-sync tool has
// copied into or restored, makes `next build` fail in ways that have nothing
// to do with the code. A clean second attempt separates those from real
// errors, which fail both times.
import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";

const dist = process.env.NEXT_DIST_DIR;
if (!dist || dist === ".next") {
  console.error("build-clean: set NEXT_DIST_DIR to a directory other than .next (it is deleted first).");
  process.exit(1);
}

function attempt() {
  rmSync(dist, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
  return spawnSync("npx", ["next", "build"], { stdio: "inherit", env: process.env }).status ?? 1;
}

let status = attempt();
if (status !== 0) {
  console.error("\nbuild-clean: the build failed; trying once more from a clean directory.\n");
  status = attempt();
}
process.exit(status);
