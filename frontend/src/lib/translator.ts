// Pure UI-text translator: exact phrase lookup, then anchored patterns, then a few safe splits.
// No imports so it can be checked outside the browser. Keys are trimmed with whitespace collapsed.
// Patterns are strict unless marked 'lenient': every $N group must translate fully, otherwise the
// pattern is skipped, so user content (titles, notes) is never half-translated.
/** patterns: [source, target] or [source, target, 'lenient'] (the shape JSON imports give us). */
export type Dictionary = { exact: Record<string, string>; patterns: string[][] };

const CHINESE = /[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]/;
const HAN = /[\u3400-\u9fff\uf900-\ufaff]/;
const PLACEHOLDER = /\{(\d)\|(raw|wan)\}|\{(\d):([^|{}]*)\|([^{}]*)\}|\$(\d)/g;
const MAX_DEPTH = 6;

/** True when text holds Han characters or full-width punctuation, i.e. may need translating. */
export const hasChinese = (text: string) => CHINESE.test(text);
const normalize = (text: string) => text.replace(/\s+/g, ' ').trim();

export function createTranslator(dictionary: Dictionary): (text: string) => string {
  const exact = new Map(Object.entries(dictionary.exact).map(([key, value]) => [normalize(key), value]));
  const patterns = dictionary.patterns.map(([source, target, mode]) => ({ pattern: new RegExp(`^(?:${source})$`), target, lenient: mode === 'lenient' }));
  const cache = new Map<string, string>();

  // Replacement syntax: $N translated group, {N|raw} untouched group, {N|wan} "1.5 万" -> "15k", {N:one|many} plural.
  function fill(target: string, groups: RegExpExecArray, depth: number, lenient: boolean) {
    let complete = true;
    const result = target.replace(PLACEHOLDER, (_all, rawIndex?: string, kind?: string, pluralIndex?: string, one?: string, many?: string, index?: string) => {
      if (rawIndex) {
        const value = groups[Number(rawIndex)] ?? '';
        if (kind === 'raw') return value;
        const thousands = Math.round(parseFloat(value) * 100) / 10;
        return Number.isFinite(thousands) ? `${thousands}k` : value;
      }
      if (pluralIndex) return Number(groups[Number(pluralIndex)]) === 1 ? one ?? '' : many ?? '';
      const value = translatePart(groups[Number(index)] ?? '', depth + 1);
      if (HAN.test(value)) complete = false;
      return value;
    });
    return complete || lenient ? result : undefined;
  }

  function translatePart(source: string, depth: number) {
    if (!hasChinese(source)) return source;
    const found = lookup(normalize(source), depth);
    return found === undefined ? source : keepSpacing(source, found);
  }

  function lookup(core: string, depth: number): string | undefined {
    const hit = exact.get(core);
    if (hit !== undefined) return hit;
    if (depth > MAX_DEPTH) return undefined;
    for (const { pattern, target, lenient } of patterns) {
      const match = pattern.exec(core);
      const result = match ? fill(target, match, depth, lenient) : undefined;
      if (result !== undefined) return result;
    }
    return split(core, depth);
  }

  // All pieces must translate (or hold no Chinese); otherwise the caller keeps the original text.
  function translateAll(pieces: string[], depth: number) {
    const out: string[] = [];
    for (const piece of pieces) {
      const core = normalize(piece);
      if (!hasChinese(core)) { out.push(core); continue; }
      const found = lookup(core, depth + 1);
      if (found === undefined) return undefined;
      out.push(found.trim());
    }
    return out;
  }

  function split(core: string, depth: number): string | undefined {
    let parts: string[] | undefined;
    if (core.includes(' · ') && (parts = translateAll(core.split(' · '), depth))) return parts.join(' · ');
    if (core.includes('、') && (parts = translateAll(core.split('、'), depth))) return parts.join(', ');
    let edge = /^(.+) ·$/.exec(core);
    if (edge && (parts = translateAll([edge[1]], depth))) return `${parts[0]} · `;
    edge = /^· (.+)$/.exec(core);
    if (edge && (parts = translateAll([edge[1]], depth))) return ` · ${parts[0]}`;
    const bracket = /^([^（）]*)（([^（）]+)）$/.exec(core);
    if (bracket && (parts = translateAll([bracket[1], bracket[2]], depth))) return parts[0] ? `${parts[0]} (${parts[1]})` : ` (${parts[1]})`;
    const sentences = core.match(/[^。！？…]+[。！？…]+|[^。！？…]+$/g);
    if (sentences && sentences.length > 1 && (parts = translateAll(sentences, depth))) return parts.join(' ');
    const tail = /^(.+?)([：:…。])$/.exec(core);
    if (tail && (parts = translateAll([tail[1]], depth))) return parts[0] + ({ '：': ': ', ':': ': ', '…': '…', '。': '.' } as Record<string, string>)[tail[2]];
    return undefined;
  }

  return function translate(text: string) {
    if (!hasChinese(text)) return text;
    const cached = cache.get(text);
    if (cached !== undefined) return cached;
    const result = translatePart(text, 0);
    if (cache.size > 5000) cache.clear();
    cache.set(text, result);
    return result;
  };
}

// Keep the source's outer whitespace unless the translation brings its own (e.g. " · archived").
function keepSpacing(source: string, found: string) {
  const lead = /^\s*/.exec(source)![0];
  const tail = /\s*$/.exec(source)![0];
  return (/^\s/.test(found) ? '' : lead) + found + (/\s$/.test(found) ? '' : tail);
}
