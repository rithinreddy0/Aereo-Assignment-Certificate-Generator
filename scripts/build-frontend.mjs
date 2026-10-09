import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";

const backend = process.env.BACKEND_URL;
if (!backend || !/^https:\/\/[a-z0-9.-]+\/?$/i.test(backend)) {
  throw new Error("Set BACKEND_URL to your HTTPS backend origin, e.g. https://folio-api.onrender.com");
}
// The Vercel Build Output API supports generated external rewrites.
await rm(".vercel/output", { recursive: true, force: true });
await mkdir(".vercel/output/static/static", { recursive: true });
await cp("app/static", ".vercel/output/static/static", { recursive: true });
await cp("app/static/index.html", ".vercel/output/static/index.html");
await cp("app/static/docs.html", ".vercel/output/static/docs.html");
const origin = backend.replace(/\/$/, "");
const routes = [
  { src: "/api/(.*)", dest: `${origin}/api/$1` },
  ...["health", "ui-config", "ui-session", "openapi.json", "redoc"].map((path) => ({
    src: `/${path.replaceAll(".", "\\.")}`, dest: `${origin}/${path}`,
  })),
  { src: "/docs/?", dest: "/docs.html" },
  { handle: "filesystem" },
];
await writeFile(".vercel/output/config.json", JSON.stringify({ version: 3, routes }, null, 2));
// Catch accidentally missing vendored preview assets before publishing.
await readFile(".vercel/output/static/static/vendor/pdf.worker.mjs");
console.log("Frontend ready; API, authentication, previews and downloads proxy to", origin);
