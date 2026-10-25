import { protectMath } from '../../components/markdownMath';
export interface Chapter { time: number; title: string; description?: string }
export interface AnalysisTimeline { projectId: string; videoResource: string | null; recordId: string; label: string; chapters: Chapter[] }
const timestamp = /(?:\[)?(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:\])?(?![\d:])/;
const plain = (text: string) => text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/(\*\*|__|`)(.*?)\1/g, '$2').trim();


/** Read existing analysis text only: no invented chapters, descriptions or model calls. */
export function extractChapters(text: string, duration = 0): Chapter[] {
  const math = protectMath(text.replace(/\r\n/g, '\n'));
  const originals = new Map([...math.expressions].map(([token, expression]) => [token, expression.source]));
  // Code is opaque too: stripping its backticks would turn a literal TeX example into math.
  let inlineFence = '';
  const closesFence = (line: string, fence: string) => new RegExp('^\\s*' + fence[0] + '{' + fence.length + ',}\\s*$').test(line);
  const protectedText = math.text.split('\n').map(line => {
    if (inlineFence) { if (closesFence(line, inlineFence)) inlineFence = ''; return line; }
    const opening = /^\s*(`{3,}|~{3,})/.exec(line);
    if (opening) { inlineFence = opening[1]; return line; }
    return line.replace(/(`+)[^\n]*?\1/g, code => {
      const token = `${math.prefix}C${originals.size}\uE001`; originals.set(token, code); return token;
    });
  }).join('\n');
  const pattern = new RegExp(math.prefix + '(?:C)?\\d+\uE001', 'g');
  // Soft limits may include one whole formula, but never cut its token or closing delimiter.
  const limit = (value: string, size: number) => {
    let kept = '', last = 0, remaining = size;
    for (const match of value.matchAll(pattern)) {
      const at = match.index!, plainText = value.slice(last, at);
      if (plainText.length >= remaining) return kept + plainText.slice(0, Math.max(0, remaining));
      kept += plainText + match[0]; remaining -= plainText.length + (originals.get(match[0])?.length || match[0].length);
      last = at + match[0].length;
      if (remaining <= 0) return kept;
    }
    return kept + value.slice(last, last + remaining);
  };
  const restore = (value: string) => value.replace(pattern, token => originals.get(token) || token);
  const clean = (value: string) => limit(plain(value).replace(/[*#]/g, '').replace(/^\s*[-–—:：|.、\s]+/, '').replace(/[|\s]+$/g, '').trim(), 160);
  const result = new Map<number, Chapter>();
  let codeFence = '', current: Chapter | undefined, titleLine = -1;
  const lines = protectedText.split('\n');
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trim();
    if (codeFence) { if (closesFence(line, codeFence)) codeFence = ''; continue; }
    const opening = /^(`{3,}|~{3,})/.exec(line);
    if (opening) { codeFence = opening[1]; continue; }
    if (!line || /https?:\/\//i.test(line) || index === titleLine) continue;
    const match = timestamp.exec(line);
    const prefix = match ? line.slice(0, match.index).replace(/[*_`]/g, '').trim() : '';
    const chapterLine = match && /^(?:#{1,6}\s*)?(?:[-+•]\s*|\d+[.)、]\s*|\|\s*)?(?:第\s*\d+\s*[章节段]\s*[:：]?\s*)?$/.test(prefix);
    if (!chapterLine || !match) {
      // A new section ends the description. Other plain lines/bullets belong to the current chapter.
      if (/^#{1,6}\s|^\s*\||^(?:[-*_]\s*){3,}$/.test(line)) { current = undefined; continue; }
      if (current) {
        const detail = plain(line);
        if (detail) current.description = limit([current.description, detail].filter(Boolean).join('\n'), 2000);
      }
      continue;
    }
    // Even an invalid, duplicate or out-of-range chapter starts a boundary, never leaks into the previous chapter.
    current = undefined;
    const hours = Number(match[1] || 0), minutes = Number(match[2]), seconds = Number(match[3]);
    if (seconds >= 60 || (match[1] && minutes >= 60)) continue;
    const time = hours * 3600 + minutes * 60 + seconds;
    if (!Number.isFinite(time) || (duration > 0 && time >= duration) || result.has(time) || result.size >= 128) continue;
    const tail = line.slice(match.index + match[0].length).replace(/^\s*[-–—~～至到]\s*\[?(?:(?:\d{1,2}):)?\d{1,3}:\d{2}\]?/, '');
    const cells = tail.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(value => value.trim());
    const heading = cells[0] || '';
    const divider = /\s*[—–]{1,2}\s*|\s+-\s+|[:：]\s*/.exec(heading);
    let title = clean(divider ? heading.slice(0, divider.index) : heading);
    const description = limit(plain([divider ? heading.slice(divider.index + divider[0].length) : '', ...cells.slice(1)]
      .filter(Boolean).join('\n')), 2000);
    if (!title && /^\s*#{1,6}\s/.test(line)) {
      const next = lines[index + 1]?.trim() || '';
      if (next && !timestamp.test(next) && !/^(```|~~~)/.test(next)) { title = clean(next); titleLine = index + 1; }
    }
    if (!title) title = `章节 ${result.size + 1}`;
    current = { time, title, ...(description ? { description } : {}) };
    result.set(time, current);
  }
  return [...result.values()].map(chapter => ({ ...chapter, title: restore(chapter.title), ...(chapter.description ? { description: restore(chapter.description) } : {}) })).sort((a, b) => a.time - b.time);
}

export function chapterTime(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600), minutes = Math.floor(value % 3600 / 60), remainder = value % 60;
  return (hours ? hours + ':' + String(minutes).padStart(2, '0') : String(minutes).padStart(2, '0')) + ':' + String(remainder).padStart(2, '0');
}
