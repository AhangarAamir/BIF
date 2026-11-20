// Folder upload: walk folders recursively, keep relative paths, skip unsupported
// files, and send in batches so a 1,700-file folder neither hits the server's
// per-request file limit nor fails as one giant request.
import { api } from "./api.js";

export const SUPPORTED = [".pdf", ".md", ".markdown", ".txt"];
const BATCH_FILES = 20;
const BATCH_BYTES = 40 * 1024 * 1024;

const ext = (name) => {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i).toLowerCase() : "";
};

/** Files picked with <input type=file> (webkitdirectory gives webkitRelativePath). */
export function fromFileList(list) {
  return Array.from(list || []).map((file) => ({ file, path: file.webkitRelativePath || file.name }));
}

/** Files and folders dropped on the page, walked recursively. */
export async function fromDrop(dataTransfer) {
  // Entries must be taken synchronously, before any await.
  const entries = Array.from(dataTransfer.items || [])
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter(Boolean);
  if (!entries.length) return fromFileList(dataTransfer.files);
  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      out.push({ file, path: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      // readEntries returns at most ~100 entries per call; keep reading until empty.
      for (;;) {
        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!batch.length) break;
        for (const child of batch) await walk(child, `${prefix}${entry.name}/`);
      }
    }
  };
  for (const entry of entries) await walk(entry, "");
  return out;
}

/** Split into files to send and files to skip (hidden or unsupported). Paths are sent as picked. */
export function classify(items) {
  const accepted = [];
  const skipped = [];
  for (const item of items) {
    const path = item.path.replace(/\\/g, "/");
    const parts = path.split("/");
    if (parts.some((p) => p.startsWith("."))) skipped.push({ file: item.path, reason: "hidden file" });
    else if (!SUPPORTED.includes(ext(item.file.name))) skipped.push({ file: item.path, reason: `unsupported type ${ext(item.file.name) || "(none)"}` });
    else accepted.push({ ...item, path });
  }
  return { accepted, skipped };
}

/** Upload in batches. A failed batch is recorded and the upload continues. */
export async function uploadAll(items, options, onProgress) {
  const result = { saved: [], skipped: [], failed: [] };
  let batch = [];
  let bytes = 0;
  let sent = 0;
  const flush = async () => {
    if (!batch.length) return;
    const current = batch;
    batch = [];
    bytes = 0;
    try {
      const res = await api.upload(current, options, false);
      result.saved.push(...res.saved);
      result.skipped.push(...(res.skipped || []));
    } catch (err) {
      result.failed.push(...current.map((i) => ({ file: i.path, reason: err.message })));
    }
    sent += current.length;
    onProgress?.({ sent, total: items.length, ...result });
  };
  for (const item of items) {
    if (batch.length && (batch.length >= BATCH_FILES || bytes + item.file.size > BATCH_BYTES)) await flush();
    batch.push(item);
    bytes += item.file.size;
  }
  await flush();
  return result;
}
