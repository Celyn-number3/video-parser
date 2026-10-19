export interface Chapter { time: number; title: string; description?: string }
export interface AnalysisTimeline { projectId: string; videoResource: string | null; recordId: string; label: string; chapters: Chapter[] }
const timestamp = /(?:\[)?(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:\])?(?![\d:])/;
const plain = (text: string) => text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/(\*\*|__|`)(.*?)\1/g, '$2').trim();
const clean = (text: string) => plain(text).replace(/[*_`#]/g, '').replace(/^\s*[-–—:：|.、\s]+/, '').replace(/[|\s]+$/g, '').trim().slice(0, 160);

/** Read existing analysis text only: no invented chapters, descriptions or model calls. */
export function extractChapters(text: string, duration = 0): Chapter[] {
  const result = new Map<number, Chapter>();
  let code = false, current: Chapter | undefined, titleLine = -1;
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trim();
    if (/^(```|~~~)/.test(line)) { code = !code; continue; }
    if (code || !line || /https?:\/\//i.test(line) || index === titleLine) continue;
    const match = timestamp.exec(line);
    const prefix = match ? line.slice(0, match.index).replace(/[*_`]/g, '').trim() : '';
    const chapterLine = match && /^(?:#{1,6}\s*)?(?:[-+•]\s*|\d+[.)、]\s*|\|\s*)?(?:第\s*\d+\s*[章节段]\s*[:：]?\s*)?$/.test(prefix);
    if (!chapterLine || !match) {
      // A new section ends the description. Other plain lines/bullets belong to the current chapter.
      if (/^#{1,6}\s|^\s*\||^(?:[-*_]\s*){3,}$/.test(line)) { current = undefined; continue; }
      if (current) {
        const detail = plain(line);
        if (detail) current.description = [current.description, detail].filter(Boolean).join('\n').slice(0, 2000);
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
    const description = plain([divider ? heading.slice(divider.index + divider[0].length) : '', ...cells.slice(1)]
      .filter(Boolean).join('\n')).slice(0, 2000);
    if (!title && /^\s*#{1,6}\s/.test(line)) {
      const next = lines[index + 1]?.trim() || '';
      if (next && !timestamp.test(next) && !/^(```|~~~)/.test(next)) { title = clean(next); titleLine = index + 1; }
    }
    if (!title) title = `章节 ${result.size + 1}`;
    current = { time, title, ...(description ? { description } : {}) };
    result.set(time, current);
  }
  return [...result.values()].sort((a, b) => a.time - b.time);
}

export function chapterTime(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(value / 3600), minutes = Math.floor(value % 3600 / 60), remainder = value % 60;
  return (hours ? hours + ':' + String(minutes).padStart(2, '0') : String(minutes).padStart(2, '0')) + ':' + String(remainder).padStart(2, '0');
}
