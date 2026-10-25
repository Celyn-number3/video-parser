import MathTextArea from '../../components/MathTextArea';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { ArchivedSubtitles, Configuration, SubtitleVersion, TranscriptionJob } from '../../lib/api';
import TranslationWorkspace from './TranslationWorkspace';
import { subtitleFunctions as labels, subtitleLanguage as lang, subtitleOrigin as origin,
  subtitleGroup as groupId, subtitleFormat as format, subtitleGroups, subtitleRepresentative as representative, subtitleLabel } from './subtitlePresentation';

type Props = { acquireContent?: ReactNode; readError?: string; archive: ArchivedSubtitles | null; job: TranscriptionJob | null; restored: TranscriptionJob | null; resource: string;
  onAcquire?: (method: 'platform' | 'transcribe') => void; onFunctionChange?: () => void; acquireOpen?: boolean; acquireDisabled?: boolean; canDownload?: boolean; fileDetails?: ReactNode; projectId: string; video: string; onSelect: (resource: string) => void; config?: Configuration | null; onOpenSettings?: (button: HTMLButtonElement) => void };
export default function SubtitleViewer({ acquireContent, readError = '', archive, job, restored, resource, projectId, video, onSelect, config, onOpenSettings, fileDetails, onAcquire, onFunctionChange, acquireOpen, acquireDisabled, canDownload }: Props) {
  const reader = useRef<HTMLDivElement>(null);
  const [viewOverride, setViewOverride] = useState<string | null>(null);
  const [preferredSource, setPreferredSource] = useState('');
  const [visitedTranslation, setVisitedTranslation] = useState(false);
  const [translation, setTranslation] = useState<TranscriptionJob | null>(null);
  const versions = [...(archive?.versions || archive?.files || [])];
  const tasks = [job, translation, restored].filter((item): item is TranscriptionJob => !!item && item.state === 'completed' && !!item.text);
  const taskVersions = new Map<string, TranscriptionJob>();
  const matches = (task: TranscriptionJob, item: SubtitleVersion) => task.files.some(file =>
    !!file.sha256 && file.sha256 === item.sha256 && origin(item) === (task.operation === 'translation' ? 'translation' : 'local')
    && (!file.project_id || file.project_id === projectId));
  for (const task of tasks) {
    if (versions.some(item => matches(task, item))) continue;
    const group = 'task:' + task.id;
    if (taskVersions.has(group)) continue;
    const outputs = task.files.length ? task.files : [{ name: task.title, format: 'txt', url: '' }];
    outputs.forEach((file, index) => {
      const key = group + (index ? ':' + file.format : '');
      taskVersions.set(key, task);
      versions.push({ resource: key, version_id: group, format: file.format.toUpperCase(), filename: file.name, url: file.url, language: task.language || task.translation_target || '',
        origin: task.operation === 'translation' ? 'translation' : 'local', kind: task.operation === 'translation' ? 'translation' : 'transcription',
        source_resource: task.translation_source || undefined, generated_at: task.created || null,
        source_language: versions.find(item => item.resource === task.translation_source)?.language,
        source_origin: origin(versions.find(item => item.resource === task.translation_source) || { resource: '', filename: '', language: '', url: '' }) });
    });
  }
  // A completed task may have just appeared in the archive. Resolve its virtual
  // selection to that file rather than jumping back to the platform version.
  const selectedTask = tasks.find(item => resource === 'task:' + item.id || resource.startsWith('task:' + item.id + ':'));
  const selectedFormat = selectedTask ? resource.split(':')[2] || selectedTask.files[0]?.format : '';
  const resolved = versions.find(item => item.resource === resource)
    || (selectedTask && (versions.find(item => matches(selectedTask, item) && format(item).toLowerCase() === selectedFormat) || versions.find(item => matches(selectedTask, item))))
    || versions.find(item => item.resource === archive?.selected?.resource) || versions[0];
  const view = viewOverride || (resolved ? origin(resolved) : 'local');
  const selected = resolved && origin(resolved) === view ? resolved : versions.find(item => origin(item) === view);
  const task = selected && (taskVersions.get(selected.resource) || (selectedTask && matches(selectedTask, selected) ? selectedTask : undefined));
  const translated = view === 'translation';
  const ready = !!selected && (!!task || archive?.selected?.resource === selected.resource);
  useEffect(() => {
    reader.current?.querySelectorAll('textarea, .math-reading-body').forEach(node => { node.scrollTop = 0; });
  }, [selected?.resource]);
  const [slowRead, setSlowRead] = useState(false);
  useEffect(() => {
    setSlowRead(false);
    if (ready || readError || !selected) return;
    const timer = window.setTimeout(() => setSlowRead(true), 300);
    return () => window.clearTimeout(timer);
  }, [ready, selected?.resource, readError]);
  const text = task?.text || (ready ? archive?.text || '' : '');
  const label = translated ? '译文' : '字幕原文';
  const originals = versions.filter(item => origin(item) !== 'translation');
  const groups = subtitleGroups(versions.filter(item => origin(item) === view));
  const results = [...groups.values()].map(representative);
  const chooseFunction = (next: string) => {
    if (selected && origin(selected) !== 'translation') setPreferredSource(selected.resource);
    setViewOverride(next); onFunctionChange?.();
    if (next === 'translation') setVisitedTranslation(true);
    const row = versions.find(item => origin(item) === next);
    if (row) onSelect(row.resource);
  };
  const acquireAction = onAcquire && (view === 'local' || view === 'platform') ? <button type="button" aria-expanded={!!acquireOpen} aria-controls="subtitle-acquire"
    disabled={acquireDisabled || view === 'platform' && !canDownload} onClick={() => onAcquire(view === 'platform' ? 'platform' : 'transcribe')}>
    {acquireOpen ? '收起获取选项' : view === 'platform' ? '重新下载字幕' : '重新生成字幕'}</button> : null;
  // This information belongs to the selected saved result, NOT the translation input.
  const provenance = selected && view !== 'platform' && view !== 'local' ? <p className="subtitle-provenance"><strong>{labels[view]}</strong><span>{lang(selected.language)}</span>
      <span className="subtitle-selected-format">{format(selected)}</span>
      {translated && <span>原字幕：{labels[selected.source_origin || 'unknown'] || labels.unknown}{selected.source_language ? '（' + lang(selected.source_language) + '）' : ''}</span>}
      {translated && selected.generated_at && <span>生成于 {new Date(selected.generated_at * 1000).toLocaleString('zh-CN')}</span>}
    </p> : null;
  if (!versions.length) return null;
  return <div className="subtitle-viewer">
    <div className="subtitle-view-sources" role="group" aria-label="字幕功能">
      <span className="option-label">功能</span>
      {Object.entries(labels).filter(([key]) => versions.some(item => origin(item) === key) || key === 'translation' || key === 'local' && !!onAcquire || key === 'platform' && canDownload).map(([key, title]) =>
        <button type="button" key={key} aria-pressed={view === key} onClick={() => chooseFunction(key)}>{title}</button>)}
    </div>
    {(visitedTranslation || translated) && <div hidden={!translated}>
      <TranslationWorkspace originals={originals} preferredSource={preferredSource || selected?.source_resource} projectId={projectId} video={video}
        archive={archive} tasks={tasks} restored={restored} config={config} onOpenSettings={onOpenSettings}
        onCompleted={result => { setTranslation(result); if (translated) onSelect('task:' + result.id); }} />
    </div>}
    {selected ? <>
    {translated && provenance}
    <label className="subtitle-version-label">{!translated && '字幕版本'}<select aria-label="字幕版本" value={selected.resource} onChange={event => onSelect(event.target.value)}>
      {results.flatMap(result => {
        const files = groups.get(groupId(result)) || [result];
        return files.map((item, index) => <option key={item.resource} value={item.resource}>
          {subtitleLabel(result, results)}（{format(item)}）{files.filter(row => format(row) === format(item)).length > 1 ? `（文件${index + 1}）` : ''}
        </option>);
      })}
    </select></label>
    {!translated && provenance}
    {!translated && acquireAction && <div className="subtitle-result-actions">{acquireAction}</div>}
    {!translated && acquireContent}
    <span className="subtitle-body-label">{label}</span>
    <div ref={reader} className="subtitle-reader" aria-busy={!ready && !readError}>
      <MathTextArea id="subtitle-viewer-text" aria-label={label} rows={8} value={ready && !readError ? text : ''} />
      {readError ? <p className="subtitle-reader-message error-text" role="alert">{readError}</p>
        : !ready && slowRead && <p className="subtitle-reader-message" role="status">正在读取字幕…</p>}
    </div>
    <details className="subtitle-file-details">
      <summary>文件信息</summary>
      {selected.generated_at && <p className="subtitle-note">生成时间：{new Date(selected.generated_at * 1000).toLocaleString('zh-CN')}</p>}
      {selected.source_resolution === 'verified_hash' && <p className="subtitle-note">原字幕来源已按内容校验确认；实际文件名保留历史标识。</p>}
      <p className="subtitle-note subtitle-version-file">实际文件：<span translate="no">{selected.filename}</span></p>
      {fileDetails}
    </details>
    </> : <p className="subtitle-note">{translated ? '暂无已保存译文，请选择上方原字幕后开始翻译。' : `暂无${labels[view]}。`}</p>}
    {!selected && !translated && acquireAction && <><div className="subtitle-result-actions">{acquireAction}</div>{acquireContent}</>}
  </div>;
}
