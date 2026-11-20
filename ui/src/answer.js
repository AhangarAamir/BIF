// Split a verified answer into body / references / verification and number its citations.

const TAG = /\[\s*C\d+(?:\s*[,;]\s*C?\d+)*\s*\]/g;
const MARK = "<!-- bif:verified -->";

export function stripThinking(text) {
  if (!text) return { text: "", thinking: "" };
  let thinking = "";
  let out = text.replace(/<think>([\s\S]*?)<\/think>/g, (_, t) => {
    thinking += t;
    return "";
  });
  const open = out.indexOf("<think>");
  if (open >= 0) {
    thinking += out.slice(open + 7);
    out = out.slice(0, open);
  }
  return { text: out.trimStart(), thinking: thinking.trim() };
}

export function parseAnswer(raw) {
  const { text, thinking } = stripThinking(raw || "");
  const verified = text.includes(MARK);
  let body = text.replace(MARK, "").trim();
  let verification = "";
  const vIdx = body.search(/\n>\s*\*\*Verification:\*\*/);
  if (vIdx >= 0) {
    verification = body.slice(vIdx).replace(/^\s*>\s*\*\*Verification:\*\*\s*/m, "").trim();
    body = body.slice(0, vIdx).trim();
  }
  const rIdx = body.search(/\n##\s*References\s*\n/);
  if (rIdx >= 0) body = body.slice(0, rIdx).trim();

  const order = [];
  body = body.replace(TAG, (tag) => {
    const ids = (tag.match(/\d+/g) || []).map(Number);
    return ids
      .map((id) => {
        if (!order.includes(id)) order.push(id);
        return `[${order.indexOf(id) + 1}](#cite-${id})`;
      })
      .join("");
  });
  return { body, order, verification, verified, thinking };
}

export function idsInText(text) {
  const ids = [];
  for (const tag of (text || "").match(TAG) || []) {
    for (const n of tag.match(/\d+/g) || []) if (!ids.includes(+n)) ids.push(+n);
  }
  return ids;
}

export function pages(hit) {
  return hit.page_start === hit.page_end ? `p. ${hit.page_start}` : `pp. ${hit.page_start}–${hit.page_end}`;
}

export function where(hit) {
  if (hit.kind === "definition" && hit.defined_term) return `Definition “${hit.defined_term}”`;
  const parts = [];
  if (hit.clause_id) parts.push(`Clause ${hit.clause_id}${hit.heading ? ` · ${hit.heading}` : ""}`);
  else if (hit.article) parts.push(/^\d+$/.test(hit.article) ? `Article ${hit.article}` : hit.article);
  else if (hit.kind === "toc") parts.push("Table of contents");
  else parts.push(hit.kind === "preamble" ? "Preamble" : "Text");
  return parts.join(" ");
}
