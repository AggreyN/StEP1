// Builds the static export into NEXT_DIST_DIR, from a clean directory, and
// tries once more if the first attempt fails.
//
//   NEXT_DIST_DIR=.next-export node scripts/build-export.mjs
//
// Used by the production test suite. The deployed build is plain
// `npm run build`, which writes to out/.
//
// Why the retry: the build downloads the fonts, and a network blip there
// fails it in a way that has nothing to do with the code. A real error
// fails both times.
import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";

const dist = process.env.NEXT_DIST_DIR;
if (!dist || dist === ".next" || dist === "out") {
  console.error("build-export: set NEXT_DIST_DIR to a directory of its own (it is deleted first).");
  process.exit(1);
}

function attempt() {
  rmSync(dist, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
  return spawnSync("npx", ["next", "build"], { stdio: "inherit", env: process.env }).status ?? 1;
}

let status = attempt();
if (status !== 0) {
  console.error("\nbuild-export: the build failed; trying once more from a clean directory.\n");
  status = attempt();
}
process.exit(status);
