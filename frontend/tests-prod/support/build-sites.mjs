// Builds every site in sites.mjs, one after the other. They can't be built
// side by side: every export shares Next's working directory (.next).
import { spawnSync } from "node:child_process";
import { SITES } from "./sites.mjs";

for (const [name, site] of Object.entries(SITES)) {
  console.log(`\nbuild-sites: ${name} -> ${site.dir}`);
  const { status } = spawnSync("node", ["scripts/build-export.mjs"], {
    stdio: "inherit",
    env: { ...process.env, ...site.env, NEXT_DIST_DIR: site.dir },
  });
  if (status !== 0) process.exit(status ?? 1);
}
