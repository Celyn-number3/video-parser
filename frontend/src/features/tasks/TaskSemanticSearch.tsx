import { useEffect, useState } from 'react';
import Panel from '../../components/Panel';
import { request } from '../../lib/api';
import type { VideoProjectSummary } from '../../lib/api';
import SemanticSearch from '../learning/SemanticSearch';

type Props = { visible: boolean; currentProjectId?: string; onSeek: (projectId: string, time: number) => Promise<void> };
export default function TaskSemanticSearch({ visible, currentProjectId, onSeek }: Props) {
  const [projects, setProjects] = useState<VideoProjectSummary[]>([]);
  const [selected, setSelected] = useState('');
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController(); setLoading(true); setError('');
    request<{ projects: VideoProjectSummary[] }>('/projects', controller.signal).then(data => {
      if (controller.signal.aborted) return;
      const available = data.projects.filter(item => item.archived);
      setProjects(available);
      setSelected(old => available.some(item => item.id === old) ? old : available.some(item => item.id === currentProjectId) ? currentProjectId! : '');
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取项目列表。'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [visible, reload, currentProjectId]);
  return <Panel className="task-semantic-search" aria-label="字幕语义检索">
    <h2>字幕语义检索（Embedding）</h2>
    <div className="semantic-project-controls"><label>检索项目<select aria-label="检索项目" value={selected} disabled={loading || opening} onChange={event => { setSelected(event.target.value); setError(''); }}>
      <option value="">选择已归档视频…</option>
      {projects.map(item => <option key={item.id} value={item.id}>{[item.episode_title || item.title, item.part ? `P${item.part}` : ''].filter(Boolean).join(' · ')}</option>)}
    </select></label><button type="button" disabled={loading || opening} onClick={() => setReload(value => value + 1)}>刷新项目列表</button></div>
    {loading && <p role="status">正在读取项目列表…</p>}
    {error && <p role="alert" className="error-text">{error}</p>}
    {selected ? <SemanticSearch key={selected} projectId={selected} onSeek={time => {
      if (opening) return;
      setOpening(true); setError('');
      void onSeek(selected, time).catch(reason => setError(reason instanceof Error ? reason.message : '无法打开视频。')).finally(() => setOpening(false));
    }} /> : <p>请选择要检索字幕的已归档视频，再建立索引或输入问题。</p>}
  </Panel>;
}
