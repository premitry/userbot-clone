const fs = require("fs");
const path = require("path");

const distDir = path.join(process.cwd(), "dist");
const indexFile = path.join(distDir, "index.html");

fs.mkdirSync(distDir, { recursive: true });
fs.writeFileSync(
  indexFile,
  '<!doctype html><html><head><meta charset="utf-8"><title>userbot</title></head><body>Python project</body></html>\n',
  "utf8",
);

if (!fs.existsSync(indexFile)) {
  throw new Error("dist/index.html was not created");
}

console.log("dist/index.html ready");