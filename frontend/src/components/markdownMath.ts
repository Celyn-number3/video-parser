/** Protect complete math expressions before Markdown handles stars, pipes and timestamps.
 * Code and unfinished expressions remain untouched; the stored source is never rewritten.
 */
export type MathExpression = { source: string; tex: string; display: boolean };
export type MathDocument = { text: string; prefix: string; expressions: Map<string, MathExpression> };

function escaped(text: string, at: number): boolean {
  let count = 0;
  while (at > 0 && text[--at] === '\\') count++;
  return count % 2 === 1;
}

export function protectMath(text: string): MathDocument {
  let prefix = '\uE000M';
  while (text.includes(prefix)) prefix += 'M';
  const expressions = new Map<string, MathExpression>();
  const chunks: string[] = [];
  const missingClosers = new Set<string>();
  let copied = 0;
  for (let at = 0; at < text.length;) {
    // Skip whole fenced code blocks, including an unfinished streaming block.
    if (at === 0 || text[at - 1] === '\n') {
      const fence = /^[ \t]*(`{3,}|~{3,})[^\n]*(?:\n|$)/.exec(text.slice(at));
      if (fence) {
        const start = at + fence[0].length;
        const end = new RegExp('^[ \\t]*' + fence[1][0] + '{' + fence[1].length + ',}[ \\t]*(?:\\n|$)', 'm').exec(text.slice(start));
        at = end ? start + end.index + end[0].length : text.length;
        continue;
      }
    }
    if (text[at] === '`' && !escaped(text, at)) {
      const ticks = /^`+/.exec(text.slice(at))![0];
      const end = text.indexOf(ticks, at + ticks.length);
      if (end >= 0) { at = end + ticks.length; continue; }
      at += ticks.length; continue;
    }
    // URLs are not TeX; preserve existing Markdown links verbatim.
    if (text[at] === '[') {
      const link = /^\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)/.exec(text.slice(at));
      if (link) { at += link[0].length; continue; }
    }
    const opening = text.startsWith('\\[', at) ? '\\[' : text.startsWith('\\(', at) ? '\\(' : text.startsWith('$$', at) ? '$$' : text[at] === '$' ? '$' : '';
    if (!opening || escaped(text, at)) { at++; continue; }
    const closing = opening === '\\[' ? '\\]' : opening === '\\(' ? '\\)' : opening;
    if (missingClosers.has(closing)) { at += opening.length; continue; }
    const start = at + opening.length;
    const display = opening === '\\[' || opening === '$$';
    let end = text.indexOf(closing, start);
    while (end >= 0 && escaped(text, end)) end = text.indexOf(closing, end + closing.length);
    if (end < 0) missingClosers.add(closing);
    // A dollar sign is also currency: no opening/closing whitespace, newline,
    // adjacent dollar, or digit immediately following a single-dollar closing.
    const dollarInvalid = opening === '$' && (/[\s$]/.test(text[start] || ' ') ||
      end < 0 || /\s/.test(text[end - 1]) || /[\d$]/.test(text[end + 1] || '') || /[\n`]/.test(text.slice(start, end)) || /https?:\/\//i.test(text.slice(start, end)));
    if (end < 0 || dollarInvalid) { at += opening.length; continue; }
    const stop = end + closing.length;
    const token = `${prefix}${expressions.size}\uE001`;
    let tex = text.slice(start, end);
    // Markdown quote markers on continuation lines are outside the formula.
    const lineStart = text.lastIndexOf('\n', at - 1) + 1;
    const quote = /^[ \t]*(?:>[ \t]*)+/.exec(text.slice(lineStart, at));
    if (quote) {
      const depth = (quote[0].match(/>/g) || []).length;
      tex = tex.replace(new RegExp('\\n[ \\t]*(?:>[ \\t]*){' + depth + '}', 'g'), '\n');
    }
    expressions.set(token, { source: text.slice(at, stop), tex, display });
    chunks.push(text.slice(copied, at), token);
    copied = stop; at = stop;
  }
  chunks.push(text.slice(copied));
  return { text: chunks.join(''), prefix, expressions };
}
