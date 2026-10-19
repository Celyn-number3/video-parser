import type { AnalysisRecord, Media } from '../../lib/api';
import { extractChapters } from './chapters';

export function matchesLearningMedia(record: AnalysisRecord, media: Media | null, episodeCount: number) {
  return !!media && (record.video_resource ? record.video_resource === media.resource : episodeCount <= 1);
}
const key = (project: string, resource: string) => `video-parser:learning-material:${project}:${resource}`;
export function readMaterialChoice(project: string, resource: string): string | null {
  try { return localStorage.getItem(key(project, resource)); } catch { return null; }
}
export function saveMaterialChoice(project: string, resource: string, record: string) {
  try { localStorage.setItem(key(project, resource), record); } catch { /* Optional browser preference; data stays on the server. */ }
}

// The chapter source belongs to the media, not to the currently displayed summary.
export function chapterMaterial(records: AnalysisRecord[], media: Media | null, episodeCount: number, duration: number, preferred: string | null) {
  const candidates = records.filter(record => matchesLearningMedia(record, media, episodeCount))
    .map(record => ({ record, chapters: extractChapters(record.text, duration) })).filter(item => item.chapters.length > 0);
  return candidates.find(item => item.record.id === preferred) || candidates.find(item => (item.record.template === 'chapters' || item.record.template === 'timeline')) || candidates[0] || null;
}
export function readChapterChoice(project: string, resource: string): string | null {
  try { return localStorage.getItem(key(project, resource) + ':chapters'); } catch { return null; }
}
export function saveChapterChoice(project: string, resource: string, record: string) {
  try { localStorage.setItem(key(project, resource) + ':chapters', record); } catch { /* Optional preference. */ }
}
