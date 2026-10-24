import type { ReactNode } from 'react';
import { t } from '../lib/i18n';

// A small, safe Markdown renderer for model output: builds React elements only (no raw HTML).
// Time stamps such as [03:15] or 1:02:03 become buttons that jump the video to that moment.
const TIME = String.raw`\[?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\s*[-–~～]\s*(?:\d{1,2}:)?\d{1,2}:\d{2})?\]?`;
const INLINE = new RegExp(String.raw`(\x60[^\x60]+\x60)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\(https?:\/\/[^)\s]+\))|(${TIME.replace(/\((?!\?)/g, '(?:')})|(\*[^*\s][^*]*\*)`, 'g');

export function parseTime(text: string): number | null {
  const match = new RegExp('^' + TIME).exec(text.trim());
  if (!match) return null;
  const [hours, minutes, seconds] = [Number(match[1] || 0), Number(match[2]), Number(match[3])];
  if (seconds >= 60 || (match[1] && minutes >= 60)) return null;
  return hours * 3600 + minutes * 60 + seconds;
}

type Seek = ((seconds: number) => void) | undefined;

function inline(text: string, onSeek: Seek, maxSeconds: number | undefined, key = ''): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0, index = 0;
  for (const match of text.matchAll(INLINE)) {
    const [token] = match;
    const at = match.index ?? 0;
    if (at > last) nodes.push(text.slice(last, at));
    const id = `${key}-${index++}`;
    if (match[1]) nodes.push(<code key={id}>{token.slice(1, -1)}</code>);
    else if (match[2]) nodes.push(<strong key={id}>{inline(token.slice(2, -2), onSeek, maxSeconds, id)}</strong>);
    else if (match[3]) {
      const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(token)!;
      nodes.push(<a key={id} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>);
    } else if (match[4]) {
      const seconds = parseTime(token);
      // Bare "12:30" without brackets is only a time stamp when it has two-digit minutes.
      const bare = !token.startsWith('[');
      const plausible = seconds !== null && (!bare || /^\d{2}:\d{2}|^\d:\d{2}:\d{2}/.test(token)) && (maxSeconds === undefined || maxSeconds <= 0 || seconds <= maxSeconds + 1);
      if (plausible && onSeek) nodes.push(<button key={id} type="button" className="md-time" title={t('跳到视频这一刻')} onClick={() => onSeek(seconds!)}>{token.replace(/^\[|\]$/g, '')}</button>);
      else nodes.push(token);
    } else if (match[5]) nodes.push(<em key={id}>{token.slice(1, -1)}</em>);
    last = at + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function cells(row: string) {
  return row.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());
}

export default function Markdown({ text, onSeek, maxSeconds, className = '' }: { text: string; onSeek?: (seconds: number) => void; maxSeconds?: number; className?: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let index = 0;
  const say = (value: string, key: string) => inline(value, onSeek, maxSeconds, key);
  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    const key = 'b' + index;
    if (!trimmed) { index++; continue; }
    if (trimmed.startsWith('```')) {
      const body: string[] = [];
      index++;
      while (index < lines.length && !lines[index].trim().startsWith('```')) body.push(lines[index++]);
      index++;
      blocks.push(<pre key={key}><code>{body.join('\n')}</code></pre>);
      continue;
    }
    if (trimmed.startsWith('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[index + 1])) {
      const head = cells(trimmed);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith('|')) rows.push(cells(lines[index++]));
      blocks.push(<div className="md-table" key={key}><table><thead><tr>{head.map((cell, column) => <th key={column}>{say(cell, key + 'h' + column)}</th>)}</tr></thead>
        <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{head.map((_, column) => <td key={column}>{say(row[column] || '', `${key}r${rowIndex}c${column}`)}</td>)}</tr>)}</tbody></table></div>);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      const Tag = `h${level}` as 'h3';
      blocks.push(<Tag key={key}>{say(heading[2].replace(/\s+#+$/, ''), key)}</Tag>);
      index++; continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { blocks.push(<hr key={key} />); index++; continue; }
    if (trimmed.startsWith('>')) {
      const body: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith('>')) body.push(lines[index++].trim().replace(/^>\s?/, ''));
      blocks.push(<blockquote key={key}>{body.map((item, row) => <p key={row}>{say(item, key + row)}</p>)}</blockquote>);
      continue;
    }
    const listItem = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
    if (listItem.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: { text: string; nested: string[] }[] = [];
      const base = listItem.exec(line)![1].length;
      while (index < lines.length) {
        if (!lines[index].trim()) {
          let next = index + 1;
          while (next < lines.length && !lines[next].trim()) next++;
          const following = next < lines.length ? listItem.exec(lines[next]) : null;
          if (following && /^\d/.test(following[2]) === ordered) { index = next; continue; }
          break;
        }
        const current = listItem.exec(lines[index]);
        if (current && current[1].length <= base + 1 && /^\d/.test(current[2]) !== ordered) break;
        if (current && current[1].length <= base + 1) items.push({ text: current[3], nested: [] });
        else if (current && items.length) items[items.length - 1].nested.push(current[3]);
        else if (lines[index].trim() && /^\s{2,}/.test(lines[index]) && items.length) items[items.length - 1].text += ' ' + lines[index].trim();
        else break;
        index++;
      }
      const List = ordered ? 'ol' : 'ul';
      blocks.push(<List key={key}>{items.map((item, row) => <li key={row}>{say(item.text, `${key}i${row}`)}
        {item.nested.length > 0 && <ul>{item.nested.map((nested, inner) => <li key={inner}>{say(nested, `${key}i${row}n${inner}`)}</li>)}</ul>}</li>)}</List>);
      continue;
    }
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && !/^(#{1,6}\s|```|>|\||\s*([-*+]|\d+[.)])\s)/.test(lines[index].trim())) paragraph.push(lines[index++].trim());
    if (!paragraph.length) paragraph.push(lines[index++].trim());
    blocks.push(<p key={key}>{paragraph.flatMap((item, row) => row ? [<br key={'br' + row} />, ...say(item, key + row)] : say(item, key + row))}</p>);
  }
  return <div className={'markdown ' + className} translate="no">{blocks}</div>;
}
