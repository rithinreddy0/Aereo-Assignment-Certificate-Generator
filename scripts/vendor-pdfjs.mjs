// These checked-in browser assets make the Python application self-contained at runtime.
import { copyFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = resolve(root, "app/static/vendor");
await mkdir(target, { recursive: true });
for (const file of ["pdf.mjs", "pdf.worker.mjs"]) {
  await copyFile(
    resolve(root, "node_modules/pdfjs-dist/build", file),
    resolve(target, file),
  );
}
await copyFile(
  resolve(root, "node_modules/pdfjs-dist/LICENSE"),
  resolve(target, "PDFJS-LICENSE.txt"),
);
for (const file of [
  "swagger-ui.css",
  "swagger-ui-bundle.js",
  "swagger-ui-standalone-preset.js",
]) {
  await copyFile(
    resolve(root, "node_modules/swagger-ui-dist", file),
    resolve(target, file),
  );
}
await copyFile(
  resolve(root, "node_modules/swagger-ui-dist/LICENSE"),
  resolve(target, "SWAGGER-LICENSE.txt"),
);
console.log(
  "PDF.js and Swagger UI assets copied. No npm server is needed at runtime.",
);
