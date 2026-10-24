import type { VideoQuality } from '../../lib/api';

export type Settings = {
  qualityPreference: 'best' | '1080p' | '720p' | '480p' | '360p';
  completionReminder: boolean;
  reuseTranscriptionModel: boolean;
};

export const SETTINGS_KEY = 'video-parser:settings';
export const DEFAULT_SETTINGS: Settings = { qualityPreference: 'best', completionReminder: false, reuseTranscriptionModel: false };

export function normalizeSettings(value: unknown): Settings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { ...DEFAULT_SETTINGS };
  const input = value as Record<string, unknown>;
  return {
    qualityPreference: input.qualityPreference === '1080p' || input.qualityPreference === '720p'
      || input.qualityPreference === '480p' || input.qualityPreference === '360p' ? input.qualityPreference : 'best',
    completionReminder: typeof input.completionReminder === 'boolean' ? input.completionReminder : false,
    reuseTranscriptionModel: typeof input.reuseTranscriptionModel === 'boolean' ? input.reuseTranscriptionModel : false,
  };
}

export function preferredQualityId(qualities: readonly VideoQuality[], defaultId: string | null,
  preference: Settings['qualityPreference']): string {
  if (!qualities.length) return '';
  if (preference === 'best') return qualities.some(item => item.id === defaultId) ? defaultId! : qualities[0].id;
  const known = qualities.map((item, index) => ({ item, index, height: item.height }))
    .filter((entry): entry is typeof entry & { height: number } => typeof entry.height === 'number' && Number.isFinite(entry.height) && entry.height > 0);
  if (!known.length) return qualities.some(item => item.id === defaultId) ? defaultId! : qualities[0].id;
  const target = Number(preference.slice(0, -1));
  const below = known.filter(entry => entry.height <= target).sort((a, b) => b.height - a.height || a.index - b.index);
  return (below[0] || known.slice().sort((a, b) => a.height - b.height || a.index - b.index)[0]).item.id;
}
