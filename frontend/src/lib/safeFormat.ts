// Client-side mirror of `backend/campaigns/rendering.py::SafeFormatter`.
//
// Used by the campaign confirmation modal to preview the rendered body
// against the first sample customer before the staff member hits Send.
// Unknown keys produce a visible `{unknown}` token in the preview so
// the user spots them — the backend would raise KeyError at send time.

export type SafeFormatContext = Record<string, unknown>;

const PLACEHOLDER_RE = /\{([a-zA-Z_][\w.]*)\}/g;

function lookup(path: string, ctx: SafeFormatContext): unknown {
  const [first, ...rest] = path.split(".");
  let obj: unknown = ctx[first];
  if (obj === undefined) return undefined;
  for (const part of rest) {
    if (obj === null || typeof obj !== "object") return undefined;
    obj = (obj as Record<string, unknown>)[part];
    if (obj === undefined) return undefined;
  }
  return obj;
}

export function safeFormat(template: string, ctx: SafeFormatContext): string {
  return template.replace(PLACEHOLDER_RE, (_match, key: string) => {
    const value = lookup(key, ctx);
    if (value === undefined || value === null) return `{${key}}`;
    return String(value);
  });
}
