import type { SubtitleVersion } from '../../lib/api';

export const subtitleFunctions: Record<string, string> = { platform: '平台下载字幕', local: '本地生成字幕', translation: 'AI翻译字幕', unknown: '来源未确认' };
const languages: Record<string, string> = { zh: '中文', 'zh-CN': '中文', en: '英文', ja: '日语', yue: '粤语' };
export const subtitleLanguage = (code?: string) => code ? languages[code] || code : '语言未标注';
export const subtitleOrigin = (row: SubtitleVersion) => row.origin || (row.kind === 'transcription' ? 'local' : row.kind === 'translation' ? 'translation' : 'unknown');
export const subtitleGroup = (row: SubtitleVersion) => row.version_id || row.resource;
export const subtitleFormat = (row: SubtitleVersion) => row.format || row.filename.split('.').pop()?.toUpperCase() || '字幕';
export function subtitleGroups(rows: SubtitleVersion[]) {
  const groups = new Map<string, SubtitleVersion[]>();
  for (const row of rows) groups.set(subtitleGroup(row), [...(groups.get(subtitleGroup(row)) || []), row]);
  return groups;
}
export const subtitleRepresentative = (items: SubtitleVersion[]) => items.find(item => subtitleFormat(item) === 'SRT') || items[0];
export function subtitleLabel(item: SubtitleVersion, peers: SubtitleVersion[], includeSource = false) {
  const base = (row: SubtitleVersion) => {
    if (subtitleOrigin(row) !== 'translation') return `${includeSource ? subtitleFunctions[subtitleOrigin(row)] + '　' : ''}${subtitleLanguage(row.language)}原文`;
    const from = row.source_origin === 'local' ? `本地${row.source_language ? subtitleLanguage(row.source_language) : ''}转写`
      : row.source_origin === 'platform' ? 'B站平台字幕' : '来源待核对';
    return `${from} → ${subtitleLanguage(row.language)}译文`;
  };
  const date = (row: SubtitleVersion) => {
    if (!row.generated_at) return '时间未记录';
    const value = new Date(row.generated_at * 1000);
    return value.toLocaleDateString('zh-CN', { ...(value.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' as const } : {}), month: 'long', day: 'numeric' });
  };
  const similar = peers.filter(row => base(row) === base(item));
  if (subtitleOrigin(item) !== 'translation' && similar.length === 1) return base(item);
  const sameDay = similar.filter(row => date(row) === date(item));
  const time = sameDay.length > 1 && item.generated_at ? ' ' + new Date(item.generated_at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '';
  // Resource identity provides deterministic ordering even if file mtimes/poll order change.
  const ordered = [...sameDay].sort((a, b) => subtitleGroup(a).localeCompare(subtitleGroup(b)));
  const suffix = sameDay.length > 1 ? `（版本${ordered.findIndex(row => subtitleGroup(row) === subtitleGroup(item)) + 1}）` : '';
  return `${base(item)}　${date(item)}${time}${suffix}`;
}
