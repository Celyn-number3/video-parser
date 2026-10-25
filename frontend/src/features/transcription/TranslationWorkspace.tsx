import { useEffect, useState } from 'react';
import { request, type ArchivedSubtitles, type Configuration, type SubtitleVersion, type TranscriptionJob } from '../../lib/api';
import SubtitleTranslation from './SubtitleTranslation';
import { subtitleGroups, subtitleLabel, subtitleRepresentative } from './subtitlePresentation';

type Props = { originals: SubtitleVersion[]; preferredSource?: string; projectId: string; video: string;
  archive: ArchivedSubtitles | null; tasks: TranscriptionJob[]; restored: TranscriptionJob | null;
  config?: Configuration | null; onOpenSettings?: (button: HTMLButtonElement) => void;
  onCompleted: (job: TranscriptionJob) => void };

/** Source reads are independent of the displayed translation and never submit a job. */
export default function TranslationWorkspace({ originals, preferredSource, projectId, video, archive, tasks, restored, config, onOpenSettings, onCompleted }: Props) {
  const choices = [...subtitleGroups(originals).values()].map(subtitleRepresentative);
  const [keepOpen, setKeepOpen] = useState(false);
  const [resource, setResource] = useState(preferredSource || '');
  const selected = originals.find(row => row.resource === resource) || originals.find(row => row.resource === preferredSource) || choices[0];
  const selectedChoice = selected && (choices.find(row => (row.version_id || row.resource) === (selected.version_id || selected.resource)) || selected);
  const key = selected?.resource || '';
  const task = tasks.find(row => (key === 'task:' + row.id || key.startsWith('task:' + row.id + ':')) && row.operation !== 'translation');
  const direct = task?.text ?? (archive?.selected?.resource === key ? archive.text : null);
  const [loaded, setLoaded] = useState<{ key: string; text: string; error: string } | null>(null);
  useEffect(() => {
    if (!key) return;
    if (direct !== null) { setLoaded({ key, text: direct, error: '' }); return; }
    const controller = new AbortController();
    const params = new URLSearchParams({ video_resource: video, subtitle_resource: key });
    request<ArchivedSubtitles>(`/projects/${projectId}/subtitles?${params}`, controller.signal).then(data => {
      if (data.selected?.resource !== key) throw new Error('原字幕版本已变化，请重新选择。');
      if (!controller.signal.aborted) setLoaded({ key, text: data.text, error: '' });
    }).catch(error => { if (!controller.signal.aborted) setLoaded({ key, text: '', error: error instanceof Error ? error.message : '读取原字幕失败。' }); });
    return () => controller.abort();
  }, [key, projectId, video, direct]);
  if (!selected || !selectedChoice) return <div className="translation-workspace"><p className="subtitle-note">暂无可翻译的原字幕，请先下载平台字幕或生成本地字幕。</p></div>;
  const text = direct ?? (loaded?.key === key ? loaded.text : '');
  const error = direct === null && loaded?.key === key ? loaded.error : '';
  const ready = direct !== null || loaded?.key === key && !error;
  const matching = restored && (restored.translation_source === key || !!restored.translation_source_sha256 && restored.translation_source_sha256 === selected.sha256) ? restored : null;
  return <div className="translation-workspace">
    <label className="subtitle-version-label">翻译原字幕<select aria-label="翻译原字幕" value={selectedChoice.resource} onChange={event => setResource(event.target.value)}>
      {choices.map(row => <option key={row.resource} value={row.resource}>{subtitleLabel(row, choices, true)}</option>)}
    </select></label>
    {error ? <p role="alert" className="error-text">{error}</p> : !ready && <p role="status">正在读取翻译原字幕…</p>}
    {ready && <SubtitleTranslation key={key} unified source={task ? { job_id: task.id } : { project_id: projectId, resource: key, video_resource: video }}
      text={ready ? text : ''} language={selected.language} config={config} onOpenSettings={onOpenSettings}
      initialOpen={keepOpen} onOpenChange={setKeepOpen} restoredJob={matching} onCompleted={onCompleted} />}
  </div>;
}
