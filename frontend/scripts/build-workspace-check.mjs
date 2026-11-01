import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

if (!process.argv[2]) throw Error("Pass a new probe output directory");
const output = resolve(process.argv[2]);
await mkdir(dirname(output), { recursive: true });
await mkdir(output); // Never empty or replace an existing directory.
await build({
  configFile: false,
  root: fileURLToPath(new URL(".", import.meta.url)),
  base: "./",
  build: {
    outDir: output,
    emptyOutDir: false,
    rollupOptions: {
      input: fileURLToPath(new URL("workspace_check.html", import.meta.url)),
    },
  },
});
