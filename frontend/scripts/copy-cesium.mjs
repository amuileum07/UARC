import { cp, mkdir } from "node:fs/promises";

await mkdir("dist/cesium", { recursive: true });
for (const directory of ["Assets", "ThirdParty", "Widgets", "Workers"]) {
  await cp(
    `node_modules/cesium/Build/Cesium/${directory}`,
    `dist/cesium/${directory}`,
    { recursive: true },
  );
}
