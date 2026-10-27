import { copyFile, mkdir } from "node:fs/promises";

await mkdir("dist", { recursive: true });
for (const file of ["estimate.js", "main.js"]) {
  await copyFile(`.build/${file}`, `dist/${file}`);
}
await copyFile("index.html", "dist/index.html");
console.log("Built static web application in dist/");
