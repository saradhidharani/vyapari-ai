import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../frontend/dist/", import.meta.url));
const upstream = new URL(process.env.VYAPARI_API_URL || "http://127.0.0.1:8000");
if (!["https:", "http:"].includes(upstream.protocol) || upstream.pathname !== "/" ||
    upstream.username || upstream.password || upstream.search || upstream.hash) {
  throw new Error("VYAPARI_API_URL must be an HTTP(S) origin");
}
const contentTypes = {
  ".css": "text/css", ".html": "text/html; charset=utf-8", ".js": "text/javascript",
  ".ico": "image/x-icon", ".png": "image/png", ".jpg": "image/jpeg",
  ".svg": "image/svg+xml", ".webp": "image/webp", ".woff2": "font/woff2",
};

function reply(res, status, detail) {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify({ detail }));
}

const proxyKey = process.env.VYAPARI_PROXY_KEY || "";
if (proxyKey && proxyKey.length < 32) throw new Error("VYAPARI_PROXY_KEY must be at least 32 characters");

// The visitor's address for the API's rate limits. The hosting platform's own
// proxy appends the real address as the last X-Forwarded-For entry, so earlier
// entries (which a visitor could set) are ignored.
function visitorAddress(req) {
  const forwarded = String(req.headers["x-forwarded-for"] || "").split(",").map((part) => part.trim()).filter(Boolean);
  const address = forwarded.at(-1) || req.socket.remoteAddress || "";
  return address.replace(/^::ffff:/, "");
}

function proxy(req, res, path) {
  const headers = {};
  for (const name of ["accept", "authorization", "content-type", "content-length", "x-business-id"]) {
    if (req.headers[name] !== undefined) headers[name] = req.headers[name];
  }
  if (proxyKey) {
    headers["x-vyapari-proxy-key"] = proxyKey;
    headers["x-vyapari-client-ip"] = visitorAddress(req);
  }
  const transport = upstream.protocol === "https:" ? https : http;
  const outgoing = transport.request(upstream, { method: req.method, path, headers, timeout: 15000 }, (result) => {
    const responseHeaders = { "Cache-Control": "no-store" };
    for (const name of ["content-type", "content-length", "content-disposition", "retry-after"]) {
      if (result.headers[name] !== undefined) responseHeaders[name] = result.headers[name];
    }
    result.on("error", () => res.destroy());
    res.writeHead(result.statusCode, responseHeaders);
    result.pipe(res);
  });
  outgoing.on("timeout", () => outgoing.destroy());
  outgoing.on("error", () => {
    if (res.headersSent) res.destroy();
    else reply(res, 502, "The Vyapari API is unavailable.");
  });
  res.on("close", () => outgoing.destroy());
  req.pipe(outgoing);
}

http.createServer(async (req, res) => {
  let url;
  let pathname;
  try {
    url = new URL(req.url, "http://vyapari.local");
    pathname = decodeURIComponent(url.pathname);
  } catch {
    return reply(res, 400, "Invalid request path.");
  }
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  if (url.pathname.startsWith("/api/") || url.pathname === "/health") {
    return proxy(req, res, url.pathname + url.search);
  }
  if (!["GET", "HEAD"].includes(req.method)) return reply(res, 405, "Method not allowed.");
  const asset = pathname.startsWith("/assets/") || Boolean(extname(pathname));
  const file = resolve(root, asset ? "." + pathname : "index.html");
  if (!file.startsWith(resolve(root) + sep)) return reply(res, 404, "Not found.");
  try {
    const info = await stat(file);
    if (!info.isFile()) return reply(res, 404, "Not found.");
    res.writeHead(200, {
      "Content-Type": contentTypes[extname(file)] || "application/octet-stream",
      "Content-Length": info.size,
      "Cache-Control": pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache",
    });
    if (req.method === "HEAD") return res.end();
    createReadStream(file).on("error", () => res.destroy()).pipe(res);
  } catch {
    reply(res, 404, "Not found.");
  }
}).listen(Number(process.env.PORT || 3000), "0.0.0.0");
