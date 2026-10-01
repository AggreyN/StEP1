// Contrast check for the palette in src/app/globals.css.
//
//   node scripts/contrast.mjs          prints the table, exits 1 on any failure
//
// It reads the tokens straight from the stylesheet (light, dark via
// prefers-color-scheme, and dark via data-theme) and checks every
// text-on-background pair the components use against WCAG 2.1:
//   4.5:1 for text (1.4.3), including faint and placeholder text
//   3:1   for control boundaries, state indicators and focus rings (1.4.11)
// It also checks that the semantic colours stay apart from the brown accent
// and from each other, so amber never reads as "just more brown".
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const css = readFileSync(fileURLToPath(new URL("../src/app/globals.css", import.meta.url)), "utf8");

function block(startMarker) {
  const at = css.indexOf(startMarker);
  if (at === -1) throw new Error(`globals.css: can't find "${startMarker}"`);
  const open = css.indexOf("{", at + startMarker.length - 1);
  const close = css.indexOf("}", open);
  const tokens = {};
  for (const m of css.slice(open + 1, close).matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    tokens[m[1]] = m[2].toLowerCase();
  }
  return tokens;
}

const light = block(":root {");
const darkMedia = block(':root:not([data-theme="light"]) {');
const darkAttr = block(':root[data-theme="dark"] {');

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lin = (c) => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const luminance = (h) => {
  const [r, g, b] = hex(h).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// CIE76 distance in Lab: crude, but enough to say "these two read as
// different colours". ~2 is just noticeable; we ask for much more.
function lab(h) {
  const [r, g, b] = hex(h).map(lin);
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
}
const distance = (a, b) => Math.hypot(...lab(a).map((v, i) => v - lab(b)[i]));
const hue = (h) => {
  const [, a, b] = lab(h);
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
};

// [foreground, background, minimum, where it is used]
const TEXT = 4.5;
const UI = 3;
const PAIRS = [
  ["text", "bg", TEXT, "body text on the page"],
  ["text", "surface", TEXT, "body text on cards, inputs, dialogs"],
  ["text", "surface-2", TEXT, "text on chips, tags, selected nav"],
  ["muted", "bg", TEXT, "secondary text on the page"],
  ["muted", "surface", TEXT, "secondary text on cards"],
  ["muted", "surface-2", TEXT, "secondary text on chips, counts, notices"],
  ["faint", "bg", TEXT, "footer, freshness line, About labels"],
  ["faint", "surface", TEXT, "placeholders, hints, dates, ghosted text"],
  ["faint", "surface-2", TEXT, "faint text on tinted rows"],
  ["accent-text", "accent-soft", TEXT, "reason chips, selected term"],
  ["accent-text", "bg", TEXT, "links on the page"],
  ["accent-text", "surface", TEXT, "links on cards"],
  ["accent", "bg", TEXT, "wordmark, About section labels"],
  ["accent", "surface", TEXT, "wordmark, saved star, About section labels in the card"],
  ["accent", "accent-soft", TEXT, "About roadmap tags"],
  ["accent-fg", "accent", TEXT, "primary buttons, score badge"],
  ["accent-fg", "accent-hover", TEXT, "primary buttons, hovered"],
  ["bg", "accent", TEXT, "About contact button"],
  ["danger", "bg", TEXT, "error text on the page"],
  ["danger", "surface", TEXT, "danger buttons, error text on cards"],
  ["danger", "danger-soft", TEXT, "error notes, rejected pill"],
  ["positive", "bg", TEXT, "positive text on the page"],
  ["positive", "surface", TEXT, "interest status, applied tick"],
  ["positive", "surface-2", TEXT, "applied tick on the timeline link"],
  ["positive", "positive-soft", TEXT, "offer and accepted pills"],
  ["warn", "bg", TEXT, "freshness warning"],
  ["warn", "surface", TEXT, "warning text on cards"],
  ["warn", "warn-soft", TEXT, "warning notes"],
  ["text", "warn-soft", TEXT, "admin: viewing another person's data"],
  ["muted", "warn-soft", TEXT, "admin: viewing another person's data"],
  ["warn", "warn-soft", UI, "admin banner border"],
  ["border-strong", "bg", UI, "control boundaries on the page"],
  ["border-strong", "surface", UI, "input, button and checkbox boundaries"],
  ["border-strong", "surface-2", UI, "boundaries inside tinted groups"],
  ["accent", "bg", UI, "focus ring on the page"],
  ["accent", "surface", UI, "focus ring on cards; active tab marker"],
  ["accent", "surface-2", UI, "focus ring inside tinted groups"],
  ["danger", "surface", UI, "rejected marker on the timeline"],
  ["positive", "surface", UI, "offer marker on the timeline"],
  ["faint", "surface", UI, "ghosted marker on the timeline"],
];

// Colours that must not be mistaken for one another.
// Hue is only compared between two saturated colours; --muted is close to
// neutral, so for it the overall distance is what counts.
const APART = [
  ["warn", "accent", true],
  ["warn", "accent-text", true],
  ["warn", "muted", false],
  ["danger", "accent", true],
  ["danger", "warn", true],
  ["positive", "accent", true],
];
const MIN_DISTANCE = 20;
const MIN_HUE_GAP = 15;

let failures = 0;
const pad = (s, n) => String(s).padEnd(n);

function report(name, t) {
  console.log(`\n${name}`);
  console.log(`${pad("foreground", 24)}${pad("background", 24)}${pad("ratio", 9)}${pad("needs", 7)}${pad("", 6)}used for`);
  for (const [fg, bg, min, where] of PAIRS) {
    if (!t[fg] || !t[bg]) throw new Error(`missing token --${!t[fg] ? fg : bg}`);
    const r = ratio(t[fg], t[bg]);
    const ok = r >= min;
    if (!ok) failures++;
    console.log(
      `${pad(`${fg} ${t[fg]}`, 24)}${pad(`${bg} ${t[bg]}`, 24)}${pad(r.toFixed(2) + ":1", 9)}${pad(min + ":1", 7)}${pad(ok ? "pass" : "FAIL", 6)}${where}`
    );
  }
  console.log(`\n${pad("kept apart", 30)}${pad("distance", 10)}${pad("hue gap", 9)}`);
  for (const [a, b, compareHue] of APART) {
    const d = distance(t[a], t[b]);
    const gap = Math.min(Math.abs(hue(t[a]) - hue(t[b])), 360 - Math.abs(hue(t[a]) - hue(t[b])));
    const ok = d >= MIN_DISTANCE && (!compareHue || gap >= MIN_HUE_GAP);
    if (!ok) failures++;
    console.log(
      `${pad(`${a} / ${b}`, 30)}${pad(d.toFixed(1), 10)}${pad(compareHue ? gap.toFixed(0) + "°" : "n/a", 9)}${ok ? "pass" : "FAIL"}`
    );
  }
}

report("LIGHT", light);
report("DARK", darkMedia);

const same = JSON.stringify(darkMedia) === JSON.stringify(darkAttr);
console.log(`\nDark tokens under prefers-color-scheme and under [data-theme="dark"] are ${same ? "identical" : "DIFFERENT"}.`);
if (!same) failures++;

console.log(failures ? `\n${failures} check(s) failed.` : "\nAll checks pass.");
process.exit(failures ? 1 : 0);
