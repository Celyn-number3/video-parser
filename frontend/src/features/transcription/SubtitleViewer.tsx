import { useState } from 'react';
import type { ArchivedSubtitles, Configuration, SubtitleVersion, TranscriptionJob } from '../../lib/api';
import SubtitleTranslation from './SubtitleTranslation';

const labels: Record<string, string> = { platform: '平台字幕', local: '本地转写字幕', translation: 'AI 译文', unknown: '来源未确认' };
const languages: Record<string, string> = { zh: '中文', 'zh-CN': '中文', en: '英文', ja: '日语', yue: '粤语' };
const lang = (code?: string) => code ? languages[code] || code : '语言未标注';
// Only typed manifest metadata establishes provenance. Never inspect the text or filename.
const origin = (row: SubtitleVersion) => row.origin || (row.kind === 'transcription' ? 'local' : row.kind === 'translation' ? 'translation' : 'unknown');
type Props = { archive: ArchivedSubtitles | null; job: TranscriptionJob | null; restored: TranscriptionJob | null; resource: string;
  projectId: string; video: string; onSelect: (resource: string) => void; config?: Configuration | null; onOpenSettings?: (button: HTMLButtonElement) => void };
export default function SubtitleViewer({ archive, job, restored, resource, projectId, video, onSelect, config, onOpenSettings }: Props) {
  const [translation, setTranslation] = useState<TranscriptionJob | null>(null);
  const versions = [...(archive?.versions || archive?.files || [])];
  const tasks = [job, translation, restored].filter((item): item is TranscriptionJob => !!item && item.state === 'completed' && !!item.text);
  const taskVersions = new Map<string, TranscriptionJob>();
  const matches = (task: TranscriptionJob, item: SubtitleVersion) => task.files.some(file =>
    !!file.sha256 && file.sha256 === item.sha256 && origin(item) === (task.operation === 'translation' ? 'translation' : 'local')
    && (!file.project_id || file.project_id === projectId));
  for (const task of tasks) {
    if (versions.some(item => matches(task, item))) continue;
    const key = 'task:' + task.id;
    if (taskVersions.has(key)) continue;
    taskVersions.set(key, task);
    versions.push({ resource: key, filename: task.files[0]?.name || task.title, url: '', language: task.language || task.translation_target || '',
      origin: task.operation === 'translation' ? 'translation' : 'local', kind: task.operation === 'translation' ? 'translation' : 'transcription',
      source_resource: task.translation_source || undefined,
      source_origin: origin(versions.find(item => item.resource === task.translation_source) || { resource: '', filename: '', language: '', url: '' }) });
  }
  // A completed task may have just appeared in the archive. Resolve its virtual
  // selection to that file rather than jumping back to the platform version.
  const selectedTask = tasks.find(item => resource === 'task:' + item.id);
  const selected = versions.find(item => item.resource === resource)
    || (selectedTask && versions.find(item => matches(selectedTask, item)))
    || versions.find(item => item.resource === archive?.selected?.resource) || versions[0];
  if (!selected) return null;
  const task = taskVersions.get(selected.resource) || selectedTask;
  const translated = origin(selected) === 'translation';
  const ready = !!task || archive?.selected?.resource === selected.resource;
  const text = task?.text || (ready ? archive?.text || '' : '');
  const label = translated ? '译文' : '字幕原文';
  const source = task ? { job_id: task.id } : { project_id: projectId, resource: selected.resource, video_resource: video };
  const sameGroup = versions.filter(item => origin(item) === origin(selected));
  return <div className="subtitle-viewer">
    <div className="subtitle-view-sources" role="group" aria-label="查看字幕来源">
      <span className="option-label">查看来源</span>
      {Object.entries(labels).filter(([key]) => versions.some(item => origin(item) === key)).map(([key, title]) =>
        <button type="button" key={key} aria-pressed={origin(selected) === key} onClick={() => onSelect(versions.find(item => origin(item) === key)!.resource)}>{title}</button>)}
    </div>
    <label className="subtitle-version-label">字幕版本<select aria-label="字幕版本" value={selected.resource} onChange={event => onSelect(event.target.value)}>
      {sameGroup.map(item => <option key={item.resource} value={item.resource}>{lang(item.language)} · {item.filename}</option>)}
    </select></label>
    <p className="subtitle-provenance"><strong>{labels[origin(selected)]}</strong> · {lang(selected.language)}
      {translated && <> · 原字幕：{labels[selected.source_origin || 'unknown'] || labels.unknown}{selected.source_language ? ' · ' + lang(selected.source_language) : ''}</>}
    </p>
    {translated ? <label htmlFor="subtitle-viewer-text">译文</label> : <SubtitleTranslation key={selected.resource} unified
      source={source} text={text} language={selected.language} config={config} onOpenSettings={onOpenSettings} onCompleted={setTranslation}
      label="字幕原文" textId="subtitle-viewer-text" restoredJob={restored && (restored.translation_source === selected.resource || !!restored.translation_source_sha256 && restored.translation_source_sha256 === selected.sha256) ? restored : null} />}
    {translated && ready && <textarea id="subtitle-viewer-text" aria-label={label} readOnly rows={8} value={text} />}
    {!ready && <p role="status">正在读取字幕版本…</p>}
    <p className="subtitle-note subtitle-version-file">实际文件：<span translate="no">{selected.filename}</span></p>
  </div>;
}
