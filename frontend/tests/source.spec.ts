// Rules about the source itself. No browser needed.
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const ROOT = path.resolve(__dirname, "..");

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) files(full, out);
    else if (/\.(tsx?|mjs|css)$/.test(name)) out.push(full);
  }
  return out;
}

/** Source with comments removed, so a rule can be named in a comment. */
function code(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

const SRC = files(path.join(ROOT, "src"));

test("nothing writes raw HTML or evaluates strings", () => {
  const banned: [RegExp, string][] = [
    [/dangerouslySetInnerHTML/, "dangerouslySetInnerHTML"],
    [/\.innerHTML\s*=/, "innerHTML ="],
    [/\.outerHTML\s*=/, "outerHTML ="],
    [/insertAdjacentHTML/, "insertAdjacentHTML"],
    [/document\.write/, "document.write"],
    [/\beval\s*\(/, "eval("],
    [/new Function\s*\(/, "new Function("],
  ];
  const hits: string[] = [];
  for (const file of SRC) {
    const text = code(file);
    for (const [pattern, name] of banned) {
      if (pattern.test(text)) hits.push(`${path.relative(ROOT, file)}: ${name}`);
    }
  }
  expect(hits).toEqual([]);
});

test("nothing renders with an inline style (the Content-Security-Policy forbids them)", () => {
  const hits = SRC.filter((f) => /\.tsx$/.test(f) && /\bstyle=\{/.test(code(f))).map((f) => path.relative(ROOT, f));
  expect(hits).toEqual([]);
});

test("screens and components never reach for the mock data", () => {
  const hits = SRC.filter((f) => /src\/(app|components)\//.test(f) && /mock/i.test(readFileSync(f, "utf8"))).map((f) =>
    path.relative(ROOT, f)
  );
  expect(hits).toEqual([]);
});

test("the application state graph lives only in the mock's fixture", () => {
  const hits = SRC.filter(
    (f) => !/src\/lib\/mock\//.test(f) && /transitions\.json/.test(readFileSync(f, "utf8"))
  ).map((f) => path.relative(ROOT, f));
  expect(hits).toEqual([]);
});

test("no gradients, no pill-shaped controls, no emoji used as icons", () => {
  const hits: string[] = [];
  for (const file of SRC.filter((f) => !/src\/lib\/mock\//.test(f))) {
    const text = code(file);
    const rel = path.relative(ROOT, file);
    if (/gradient/i.test(text)) hits.push(`${rel}: gradient`);
    if (/\p{Extended_Pictographic}/u.test(text)) hits.push(`${rel}: emoji`);
    // rounded-full is allowed only on things that are dots or rings, never on a control or a chip
    for (const line of text.split("\n")) {
      if (/rounded-full/.test(line) && /<(button|a|input|li|Link|Button|Chip)\b/.test(line)) {
        hits.push(`${rel}: pill-shaped ${line.trim().slice(0, 60)}`);
      }
    }
  }
  expect(hits).toEqual([]);
});

test("the palette passes the contrast check", () => {
  const out = execFileSync("node", [path.join(ROOT, "scripts/contrast.mjs")], { encoding: "utf8" });
  expect(out).toContain("All checks pass.");
  expect(out).not.toContain("FAIL");
});

test("amplify.yml carries the same security headers as next.config", () => {
  // The generator is the judge: it builds the block from security-headers.mjs,
  // which is what next.config.ts serves, and compares it with the file.
  const check = (env: NodeJS.ProcessEnv) => {
    try {
      execFileSync("node", [path.join(ROOT, "scripts/amplify-headers.mjs"), "--check"], { env, encoding: "utf8" });
      return true;
    } catch {
      return false;
    }
  };
  const launchDefaults = { ...process.env, NEXT_PUBLIC_API_BASE: "", NEXT_PUBLIC_UPLOAD_ORIGIN: "" };
  // up to date either with the launch defaults or pinned to this environment's origins
  expect(check(launchDefaults) || check(process.env)).toBe(true);

  const yml = readFileSync(path.resolve(ROOT, "../amplify.yml"), "utf8");
  for (const name of [
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "X-Frame-Options",
    "Permissions-Policy",
    "Content-Security-Policy",
  ]) {
    expect(yml).toContain(`key: "${name}"`);
  }
});
