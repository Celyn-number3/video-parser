import { useEffect, useState } from 'react';
import { request } from '../../lib/api';
import type { VideoProject, VideoProjectSummary } from '../../lib/api';
import './learning-project-picker.css';

type Props = { current: VideoProject | null; version?: number; compact?: boolean; disabled: boolean; loading: boolean; onSelect: (id: string) => void };
type LearningOption = VideoProject | VideoProjectSummary;
const archived = (project: LearningOption) => 'resources' in project ? project.resources.some(item => item.kind === 'video') : project.archived === true;
const label = (project: LearningOption) => [project.episode_title || project.title, project.part ? `P${project.part}` : '', project.episode_title && project.episode_title !== project.title ? project.title : ''].filter(Boolean).join(' · ');

export default function LearningProjectPicker({ current, version = 0, compact = false, disabled, loading, onSelect }: Props) {
  const [projects, setProjects] = useState<VideoProjectSummary[]>([]);
  const [query, setQuery] = useState('');
  const [reload, setReload] = useState(0);
  const [reading, setReading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setReading(true); setError('');
    request<{ projects: VideoProjectSummary[] }>('/projects', controller.signal).then(result => {
      if (!controller.signal.aborted) setProjects(result.projects.filter(archived));
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取项目列表。'); })
      .finally(() => { if (!controller.signal.aborted) setReading(false); });
    return () => controller.abort();
  }, [reload, version]);
  const available: LearningOption[] = projects.map(item => current && item.id === current.id ? current : item);
  if (current && !available.some(item => item.id === current.id)) available.unshift(current);
  const matching = available.filter(item => label(item).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const options = current && !matching.some(item => item.id === current.id) ? [current, ...matching] : matching;
  return <div className={'learning-project-picker' + (compact ? ' is-compact' : '')} role="group" aria-label="学习项目切换" aria-busy={reading || loading}>
    <label className="learning-project-select"><span className={compact ? 'sr-only' : undefined}>学习项目</span><select aria-label="学习项目" value={current?.id || ''}
      disabled={disabled || reading || options.length === 0} onChange={event => { if (event.target.value) onSelect(event.target.value); }}>
      <option value="">选择已归档视频…</option>
      {options.map(item => <option key={item.id} value={item.id} disabled={!archived(item)}>{label(item)}{!archived(item) ? '（尚未归档）' : ''}</option>)}
    </select></label>
    <details className="learning-project-tools" onKeyDown={event => { if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus(); } }}><summary title="查找与刷新项目">{compact ? '查找' : '查找与刷新项目'}</summary><div>
    <input className="learning-project-search" type="search" aria-label="搜索学习项目" placeholder="搜索课程、分集或标题" value={query}
      onChange={event => setQuery(event.target.value)} />
    <button type="button" disabled={reading || loading} onClick={() => setReload(value => value + 1)}>刷新项目列表</button>
    </div></details>
    {loading ? <p role="status">正在从本地归档切换视频…</p> : reading ? <p role="status">正在读取项目列表…</p>
      : error ? <p className="error-text" role="alert">{error}</p> : projects.length === 0 ? <p>暂无已归档项目。先在视频工作台准备视频，再来这里学习。</p>
      : query && matching.length === 0 ? <p>没有匹配的已归档项目；当前视频保持不变。</p> : null}
  </div>;
}
