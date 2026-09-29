// A small static file server that behaves the way AWS Amplify Hosting is
// documented to behave for a static site. The production test suite serves
// the exported site with it, so what is tested is the files themselves, the
// rewrite rules exactly as they are entered in Amplify, and the security
// headers from the one definition.
//
//   node scripts/static-server.mjs --dir out --port 3200
//     [--rules amplify-rewrites.json]   the rules file (default)
//     [--connect http://localhost:3400] extra origins for the header's
//                                       connect-src (tests use http://localhost
//                                       stand-ins; the real header allows https:)
//
// What it models, and where that comes from:
//   - Rules are applied from the top of the list down.
//     (Amplify user guide, "Understanding the order of redirects")
//   - 200 is a rewrite, 301 and 302 redirect, 404 serves the target when the
//     address doesn't exist. A `<name>` placeholder matches one path segment,
//     `<*>` at the end matches the rest.
//     (Amplify user guide, "Redirects and rewrites example reference")
//   - Clean URLs: /about serves /about.html; if that doesn't exist and
//     /about/index.html does, /about redirects to /about/.
//     (same page, "Trailing slashes and clean URLs")
//   - Custom headers are added to every response that matches the pattern.
//     (Amplify user guide, "Setting custom headers")
// It is a model, not Amplify: see the README for what can only be checked
// on the real thing.
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { securityHeaders } from "../security-headers.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
};

const root = path.resolve(arg("dir", "out"));
const port = Number(arg("port", "3200"));
const rules = JSON.parse(readFileSync(path.resolve(here, "..", arg("rules", "amplify-rewrites.json")), "utf8"));
const connect = arg("connect", "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const headers = securityHeaders({ dev: false, connect: connect.length ? ["https:", ...connect] : undefined });

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".map": "application/json; charset=utf-8",
};

/** "/applications/<id>" -> a matcher that returns the placeholder values. */
function matcher(source) {
  if (source.startsWith("</") && source.endsWith("/>")) {
    const re = new RegExp(source.slice(2, -2));
    return (p) => (re.test(p) ? {} : null);
  }
  const names = [];
  const pattern = source
    .split("/")
    .map((seg) => {
      if (seg === "<*>") {
        names.push("*");
        return "(.*)";
      }
      const m = seg.match(/^<(.+)>$/);
      if (m) {
        names.push(m[1]);
        return "([^/]+)";
      }
      return seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  const re = new RegExp(`^${pattern}$`);
  return (p) => {
    const m = p.match(re);
    return m ? Object.fromEntries(names.map((n, i) => [n, m[i + 1]])) : null;
  };
}

const compiled = rules.map((r) => ({ ...r, match: matcher(r.source) }));
const fill = (target, values) => target.replace(/<([^>]+)>/g, (_, n) => values[n] ?? "");

function fileFor(urlPath) {
  const full = path.join(root, path.normalize(urlPath));
  if (!full.startsWith(root)) return null; // no climbing out of the directory
  return existsSync(full) && statSync(full).isFile() ? full : null;
}

/** Amplify's clean URLs: the file for an address, or a redirect, or nothing. */
function resolve(urlPath) {
  if (urlPath.endsWith("/")) {
    const index = fileFor(urlPath + "index.html");
    return index ? { file: index } : null;
  }
  const exact = fileFor(urlPath);
  if (exact) return { file: exact };
  const html = fileFor(urlPath + ".html");
  if (html) return { file: html };
  if (fileFor(urlPath + "/index.html")) return { redirect: urlPath + "/" };
  return null;
}

function send(res, status, file, extra = {}) {
  res.writeHead(status, {
    "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream",
    "Cache-Control": "no-store",
    ...Object.fromEntries(headers.map((h) => [h.key, h.value])),
    ...extra,
  });
  createReadStream(file).pipe(res);
}

function redirect(res, status, location) {
  res.writeHead(status, { Location: location, ...Object.fromEntries(headers.map((h) => [h.key, h.value])) });
  res.end();
}

http
  .createServer((req, res) => {
    const url = new URL(req.url, `http://localhost:${port}`);
    let pathname;
    try {
      pathname = decodeURIComponent(url.pathname);
    } catch {
      res.writeHead(400).end();
      return;
    }

    let notFoundRule = null;
    for (const rule of compiled) {
      const values = rule.match(pathname);
      if (!values) continue;
      if (rule.status === "404" || rule.status === "404-200") {
        notFoundRule ??= { rule, values };
        continue;
      }
      const target = fill(rule.target, values);
      if (rule.status === "301" || rule.status === "302") {
        // Query strings are passed on unless the target has its own.
        redirect(res, Number(rule.status), target.includes("?") ? target : target + url.search);
        return;
      }
      if (rule.status === "200") {
        const found = resolve(target);
        if (found?.file) {
          send(res, 200, found.file);
          return;
        }
      }
    }

    const found = resolve(pathname);
    if (found?.file) return send(res, 200, found.file);
    if (found?.redirect) return redirect(res, 301, found.redirect + url.search);

    if (notFoundRule) {
      const target = resolve(fill(notFoundRule.rule.target, notFoundRule.values));
      if (target?.file) return send(res, notFoundRule.rule.status === "404" ? 404 : 200, target.file);
    }
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not found");
  })
  .listen(port, () => console.log(`static-server: ${root} on http://localhost:${port}`));
