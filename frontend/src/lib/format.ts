// Preserve the existing task/cache size display; shared by model feedback and views.
export const formatMegabytes = (value: number) => (value / 1024 / 1024).toFixed(1) + ' MB';

export const formatBytes = (value: number): string => {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  const size = value / Math.pow(1024, i);
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
};

// A position on a media timeline, e.g. 7:05 or 1:02:05.
export const formatClock = (seconds: number): string => {
  const s = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), rest = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(rest)}` : `${m}:${pad(rest)}`;
};

export const formatRate = (bytesPerSecond: number): string => {
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return '';
  return `${formatBytes(bytesPerSecond)}/s`;
};

export const formatEta = (seconds: number): string => {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  if (seconds === 0) return '0 秒';
  const s = Math.ceil(seconds);
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m} 分 ${rem} 秒`;
  const h = Math.floor(m / 60);
  return `${h} 时 ${m % 60} 分`;
};
