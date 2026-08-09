/**
 * Expo `export --platform web` (single) often ignores app/+html.tsx.
 * Inject PWA meta/links into dist/index.html after export.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const indexPath = path.join(root, "..", "dist", "index.html");

if (!fs.existsSync(indexPath)) {
  console.warn("[patch-web-html] dist/index.html not found, skip");
  process.exit(0);
}

let html = fs.readFileSync(indexPath, "utf8");
let changed = false;

const inject = `
    <meta name="theme-color" content="#0b1220" />
    <meta name="mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-title" content="Mail Manager" />
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
    <link rel="manifest" href="/manifest.webmanifest" />
    <link rel="icon" href="/favicon.ico" sizes="any" />
    <link rel="icon" type="image/png" href="/favicon.png" sizes="128x128" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
    <script>
      if ('serviceWorker' in navigator) {
        window.addEventListener('load', function () {
          navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
        });
      }
    </script>
`;

const hasManifest = html.includes('rel="manifest"');
const hasIco = html.includes("favicon.ico");

if (!/<html[^>]*lang=/i.test(html)) {
  html = html.replace(/<html[^>]*>/i, '<html lang="it">');
  changed = true;
}

if (!/<title>/i.test(html)) {
  html = html.replace(/<head[^>]*>/i, (m) => `${m}\n    <title>Mail Manager</title>`);
  changed = true;
} else if (!/Mail Manager/i.test(html.match(/<title>[^<]*<\/title>/i)?.[0] || "")) {
  html = html.replace(/<title>[^<]*<\/title>/i, "<title>Mail Manager</title>");
  changed = true;
}

if (!hasManifest) {
  html = html.replace(/<title>[^<]*<\/title>/i, (m) => `${m}${inject}`);
  changed = true;
} else if (!hasIco) {
  if (/<link[^>]*rel="icon"[^>]*>/i.test(html)) {
    html = html.replace(/<link[^>]*rel="icon"[^>]*>/gi, "");
    html = html.replace(
      /<\/head>/i,
      `    <link rel="icon" href="/favicon.ico" sizes="any" />\n    <link rel="icon" type="image/png" href="/favicon.png" sizes="128x128" />\n    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />\n  </head>`,
    );
  } else {
    html = html.replace(/<title>[^<]*<\/title>/i, (m) => `${m}${inject}`);
  }
  changed = true;
}

if (!changed) {
  console.log("[patch-web-html] manifest/favicon already present");
  process.exit(0);
}

fs.writeFileSync(indexPath, html);
console.log("[patch-web-html] injected PWA tags into dist/index.html");
