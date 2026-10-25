/** Display-only edge citations. Never rewrite saved Markdown or search inside math/code/links. */
const CLOCK = String.raw`(?:\d{1,2}:)?\d{1,2}:\d{2}`;
const RANGE = new RegExp(String.raw`([（(]?)\s*(\[?${CLOCK}\]?)\s*[-–—~～至]\s*(\[?${CLOCK}\]?)\s*([）)]?)`, 'g');
const LITERAL = /`+[^`]*`+|\[[^\]]*\]\(https?:\/\/[^)\s]+\)/g;
type Point = { label: string; seconds: number };
export type EdgeTimeRange = { body: string; start: Point; end: Point };

export function edgeTimeRange(text: string, parse: (value: string) => number | null, maxSeconds?: number): EdgeTimeRange | null {
  const protectedSpans = Array.from(text.matchAll(new RegExp(LITERAL)), m => [m.index!, m.index! + m[0].length]);
  for (const match of text.matchAll(new RegExp(RANGE))) {
    const at = match.index!, stop = at + match[0].length;
    if (protectedSpans.some(([start, end]) => at < end && stop > start)) continue;
    const before = text.slice(0, at), after = text.slice(stop);
    const leading = !before.trim();
    if (!leading && !/^[\s。.!！?？;；,，]*$/.test(after)) continue;
    // Do not extract a substring from a longer number or malformed citation.
    if (/[\d:[（(]$/.test(before) || /^[\d:\]）)]/.test(after)) continue;
    if (!((match[1] === '(' && match[4] === ')') || (match[1] === '（' && match[4] === '）') || (!match[1] && !match[4]))) continue;
    if ((match[0].match(/\[/g)?.length ?? 0) !== (match[0].match(/\]/g)?.length ?? 0)) continue;
    // Permit separate endpoint brackets or one pair around the whole range, not ]–[.
    if ((match[2].endsWith(']') && !match[2].startsWith('[')) || (match[3].startsWith('[') && !match[3].endsWith(']'))) continue;
    const startLabel = match[2].replace(/[\[\]]/g, ''), endLabel = match[3].replace(/[\[\]]/g, '');
    const start = parse(startLabel), end = parse(endLabel);
    if (start === null || end === null || end < start || (maxSeconds !== undefined && maxSeconds > 0 && end > maxSeconds + 1)) continue;
    const body = leading ? after.trimStart() : before.trimEnd() + after.trimStart();
    return { body, start: { label: startLabel, seconds: start }, end: { label: endLabel, seconds: end } };
  }
  return null;
}
