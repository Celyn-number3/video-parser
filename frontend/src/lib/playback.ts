/** Playback speed and auto-advance preferences. Browser-local only; nothing is sent to the server. */

const RATE_KEY = 'video-parser:playback-rate';
const AUTO_NEXT_KEY = 'video-parser:auto-next';

export const SPEED_PRESETS = [0.75, 1, 1.25, 1.5, 1.75, 2];
export const MIN_RATE = 0.25;
export const MAX_RATE = 4;

/** Keeps an arbitrary typed value inside the range browsers actually honour. */
export function normalizeRate(value: number) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(MAX_RATE, Math.max(MIN_RATE, Math.round(value * 100) / 100));
}

export function readRate() {
  try { const saved = Number(localStorage.getItem(RATE_KEY)); return saved ? normalizeRate(saved) : 1; } catch { return 1; }
}

export function saveRate(rate: number) {
  try { localStorage.setItem(RATE_KEY, String(normalizeRate(rate))); } catch { /* Optional browser preference. */ }
}

/** Auto-advance is on unless the learner turned it off. */
export function readAutoNext() {
  try { return localStorage.getItem(AUTO_NEXT_KEY) !== 'off'; } catch { return true; }
}

export function saveAutoNext(enabled: boolean) {
  try { localStorage.setItem(AUTO_NEXT_KEY, enabled ? 'on' : 'off'); } catch { /* Optional browser preference. */ }
}
