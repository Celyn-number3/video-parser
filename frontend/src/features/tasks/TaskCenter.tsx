import Panel from '../../components/Panel';
import ProgressBar from '../../components/ProgressBar';
import useTaskCenter from './useTaskCenter';
import { formatMegabytes as bytes } from '../../lib/format';
import { useState } from 'react';
import { isActive, phases, type TaskInfo } from '../../lib/jobs';
import './tasks.css';
import { templates, sources, engines, taskDescription } from './taskDetails';

const names: Record<string,string> = { video:'视频', subtitles:'平台字幕', transcriptions:'本地转写', analysis:'AI 分析', naming:'文件重命名' };
const fileRoles: Record<string, string> = { video: '源视频', audio: '源音频', source_subtitle: '原字幕', subtitle: '平台字幕', transcription: '转写字幕', translation: '译文', file: '文件' };
const withResult = ['subtitles','transcriptions','video','analysis'];
const retryable = ['failed','cancelled','interrupted'];
const duration = (seconds: number) => seconds < 60 ? `${Math.max(1, Math.round(seconds))} 秒` : `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
const progressText = (job: TaskInfo) => {
  const { done = 0, total = 0 } = job.progress || {};
  if (!total) return '';
  if (job.operation === 'translation') return ` · ${done}/${total} 批`;
  if (job.kind === 'transcriptions') {
    const clock = (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`;
    return ` · ${clock(done)} / ${clock(total)}`;
  }
  if (job.kind === 'naming' && job.phase === 'validating') return ` · ${done}/${total} 个文件`;
  if (job.kind === 'subtitles' || job.kind === 'naming') return ` · ${done}/${total} 集`;
  return ` · ${done}/${total}`;
};
const restore = (detail: { kind?: string; id?: string; projectId?: string }) => window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail}));
export default function TaskCenter({ onActivityChange }: { onActivityChange?: (count: number | null) => void }) {
  const { jobs, error, notice, facets, setFacets, resetFilters, filter, setFilter, kind, setKind, query, setQuery, statusCounts, kindCount, retrying,
    pendingCancels, visible, cancel, retry, deadCount, clearing, clearDead } = useTaskCenter(onActivityChange);
  const [confirmClear, setConfirmClear] = useState(false);
  // Keep an emptied selected type visible so clearing records cannot strand the filter.
  const kinds = Object.keys(names).filter(key => key === kind || jobs.some(job => job.kind === key));
  const narrowed = !!query.trim() || filter !== 'all' || kind !== 'all' || Object.values(facets).some(Boolean);
  return <Panel className="task-center" aria-labelledby="page-title-tasks">
    {error && <p className="error-text" role="status">{error}</p>}
    {jobs.length > 0 && <div className="task-search"><input type="search" aria-label="搜索任务" placeholder="搜索文件名、分集（如 P3）或任务 ID" maxLength={100}
      value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Escape' && query) { event.preventDefault(); setQuery(''); } }} />
      {narrowed && <span className="task-result-count" role="status" aria-live="polite">{`显示 ${visible.length} / ${jobs.length} 项`}</span>}</div>}
    <div className="task-filters" role="group" aria-label="任务筛选">{[['all','全部任务'],['active','进行中'],['completed','已完成'],['unfinished','未完成']].map(([key,label]) => <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}<span className="chip-count">{statusCounts[key]}</span></button>)}
      {deadCount > 0 && !confirmClear && <button type="button" className="task-clear" onClick={() => setConfirmClear(true)}>清理失败记录<span className="chip-count">{deadCount}</span></button>}</div>
    {confirmClear && deadCount > 0 && <div className="task-clear-confirm" role="alert">
      <p>删除 {deadCount} 条失败、已取消或重启中断的任务记录？已生成的文件和归档不受影响。</p>
      <button type="button" className="primary" disabled={clearing} aria-busy={clearing} onClick={() => { void clearDead().then(() => setConfirmClear(false)); }}>{clearing ? '清理中…' : '确认清理'}</button>
      <button type="button" disabled={clearing} onClick={() => setConfirmClear(false)}>取消</button>
    </div>}
    {(kinds.length > 1 || kind !== 'all') && <div className="task-kinds" role="group" aria-label="按类型筛选">
      {[['all', '全部类型'] as const, ...kinds.map(key => [key, names[key]] as const)].map(([key, label]) => [key, label, kindCount(key)] as const).map(([key, label, count]) =>
        <button key={key} type="button" className="chip" aria-pressed={kind === key} onClick={() => setKind(key)}>{label}<span className="chip-count">{count}</span></button>)}
    </div>}
    <div className="task-advanced-filters">
      {([['template', '分析类型', templates], ['engine', '执行工具', engines], ['source', '分析依据', sources], ['model', '模型', {}]] as const).map(([key, label, labels]) =>
        <label key={key}>{label}<select aria-label={label} value={facets[key]} onChange={e => setFacets(old => ({ ...old, [key]: e.target.value }))}>
          <option value="">全部</option>{Array.from(new Set(jobs.map(job => job.details?.[key]).filter((v): v is string => !!v))).sort().map(value =>
            <option key={value} value={value}>{(labels as Record<string, string>)[value] || value}</option>)}
        </select></label>)}
      <label>开始日期<input type="date" aria-label="开始日期" value={facets.after} onChange={e => setFacets(old => ({ ...old, after: e.target.value }))} /></label>
      <label>结束日期<input type="date" aria-label="结束日期" value={facets.before} onChange={e => setFacets(old => ({ ...old, before: e.target.value }))} /></label>
      <button type="button" onClick={resetFilters}>重置筛选</button>
    </div>
    <ul className="task-list">{visible.map(job => {
      const active = isActive(job.state);
      const showBar = job.kind === 'video' && active && job.phase === 'downloading' && !!job.progress;
      // One navigation action per row: results when they exist, retry when the project can rerun, otherwise the project.
      const viewResult = job.kind === 'naming' || !active && withResult.includes(job.kind || '') && ['completed','empty','partial','login_required'].includes(job.state);
      const projectRetry = !active && ['video','analysis'].includes(job.kind || '') && !!job.project_id && retryable.includes(job.state);
      const openProject = !active && !!job.project_id && !viewResult && !projectRetry;
      // The ID and error code stay reachable (hover, and the search box accepts IDs) without a details fold per row.
      const subjects = job.subjects;
      const batch = (subjects?.length || 0) > 1;
      const headlineFiles = job.video_names?.length ? job.video_names : job.file_names || [];
      const allFiles = [...(job.video_names || [])];
      const overlaps = [...allFiles];
      for (const name of job.file_names || []) { const index = overlaps.indexOf(name); if (index >= 0) overlaps.splice(index, 1); else allFiles.push(name); }
      const files = job.file_details ?? allFiles.map(name => ({ name, role: 'file', part: job.part || null, project_id: job.project_id || null }));
      const parts = subjects?.filter(item => item.part).map(item => 'P' + item.part) || [];
    return <li key={job.id} title={`任务 ID：${job.id}${job.error_code ? `\n错误码：${job.error_code}` : ''}`}>
      <div className="task-description"><strong>{job.operation?.startsWith('folder_') ? '项目文件夹重命名' : job.operation === 'translation' ? 'AI 翻译' : names[job.kind || ''] || '任务'} · {subjects !== undefined ? batch ? <>{parts.length ? <span translate="no" title={parts.join('、')}>{parts.slice(0, 6).join('、')}{parts.length > 6 ? '…' : ''}</span> : <span>分集名称暂不可用</span>}<span>{` · 共 ${subjects.length} 集`}</span></> : <>{subjects[0]?.part ? <span translate="no">P{subjects[0].part} · </span> : null}{subjects[0]?.title ? <span translate="no">{subjects[0].title}</span> : <span>分集名称暂不可用</span>}</> : <>{headlineFiles.length ? <span translate="no">{headlineFiles[0]}{headlineFiles.length > 1 && <span className="task-file-count"> +{headlineFiles.length - 1}</span>}</span> : <span>文件名暂不可用 · <span translate="no">{job.id.slice(0,8)}</span></span>}{job.part ? <span className="task-part">P{job.part}</span> : null}</>}</strong><p>{phases[job.phase || job.state] || job.state}{job.queue_position ? ` · 队列第 ${job.queue_position} 项` : ''}{progressText(job)}{active && !showBar && job.progress?.bytes ? ` · ${bytes(job.progress.bytes)}${job.progress.total_bytes ? ' / ' + bytes(job.progress.total_bytes) : ''}` : ''}{!active && job.elapsed_seconds ? ` · ${duration(job.elapsed_seconds)}` : ''}</p>
        {(files.length > 0 && (subjects !== undefined || files.length > 1) || batch) && <details className="task-files"><summary>{files.length ? <>全部文件（{files.length}）</> : '分集明细'}</summary>
          {batch && <ul className="task-subjects">{subjects!.map((item, index) => <li key={item.project_id || index}>{item.part ? <span translate="no">P{item.part} · </span> : null}{item.title ? <span translate="no">{item.title}</span> : <span>分集名称暂不可用</span>}</li>)}</ul>}
          <ul>{files.map((item, index) => <li key={index}><span className="task-file-role">{batch && item.part ? <span translate="no">P{item.part} · </span> : null}{fileRoles[item.role] || fileRoles.file}：</span><span translate="no">{item.name}</span></li>)}</ul>
        </details>}
        {taskDescription(job) && <p className="task-detail" translate="no">{taskDescription(job)}</p>}
        {job.created && <small>创建于 {new Date(job.created * 1000).toLocaleString()}</small>}
        {/* A completed row needs no extra sentence; progress, failures and partial results keep their explanation. */}
        {job.state !== 'completed' && job.message && job.message !== (phases[job.phase || job.state] || job.state) && <small>{job.message}</small>}
        {showBar && <ProgressBar progress={job.progress!} />}
        {job.kind === 'transcriptions' && !job.project_id && ['failed','cancelled','interrupted'].includes(job.state) && <p className="task-file-retry-note">本地文件请回到“字幕与转写”重新选择后提交。</p>}</div>
      <div className="task-actions">{active && <button type="button" disabled={pendingCancels.includes(job.id) || job.state === 'cancelling' || (job.kind === 'naming' && job.phase === 'archiving')} aria-busy={pendingCancels.includes(job.id)} onClick={() => { void cancel(job); }}>取消任务</button>}
        {viewResult && <button type="button" onClick={() => restore({ kind: job.kind, id: job.id })}>{job.kind === 'naming' ? active ? '查看命名进度' : '查看命名记录' : '查看结果'}</button>}
        {projectRetry && <button type="button" onClick={() => restore({ projectId: job.project_id })}>返回项目重试</button>}
        {openProject && <button type="button" onClick={() => restore({ projectId: job.project_id })}>打开项目</button>}
        {job.kind === 'subtitles' && ['partial', ...retryable].includes(job.state) && <button type="button" disabled={retrying.includes(job.id)} onClick={() => { void retry(job); }}>重试未完成分集</button>}
      </div>
    </li>;
    })}</ul>
    {!jobs.length && !error && <p className="notice">暂无任务。</p>}
    {!visible.length && jobs.length > 0 && <p className="notice">{query.trim() ? '没有匹配的任务。' : '此筛选下暂无任务。'}</p>}
    {jobs.length >= 100 && <p className="task-catalog-note">最多展示最近100项。</p>}
    {notice && <p role="status">{notice}</p>}
  </Panel>;
}
