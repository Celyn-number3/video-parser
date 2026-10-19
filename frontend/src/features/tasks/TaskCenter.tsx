import Panel from '../../components/Panel';
import ProgressBar from '../../components/ProgressBar';
import useTaskCenter from './useTaskCenter';
import { formatMegabytes as bytes } from '../../lib/format';
import { useState } from 'react';
import { isActive, phases } from '../../lib/jobs';
import './tasks.css';

const names: Record<string,string> = { video:'视频', subtitles:'平台字幕', transcriptions:'本地转写', analysis:'AI 分析', naming:'字幕命名' };
const withResult = ['subtitles','transcriptions','video','analysis'];
const retryable = ['failed','cancelled','interrupted'];
const duration = (seconds: number) => seconds < 60 ? `${Math.max(1, Math.round(seconds))} 秒` : `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
const restore = (detail: { kind?: string; id?: string; projectId?: string }) => window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail}));
export default function TaskCenter({ onActivityChange }: { onActivityChange?: (count: number | null) => void }) {
  const { jobs, error, notice, filter, setFilter, kind, setKind, query, setQuery, statusCounts, kindCount, retrying,
    pendingCancels, visible, cancel, retry, deadCount, clearing, clearDead } = useTaskCenter(onActivityChange);
  const [confirmClear, setConfirmClear] = useState(false);
  // Keep an emptied selected type visible so clearing records cannot strand the filter.
  const kinds = Object.keys(names).filter(key => key === kind || jobs.some(job => job.kind === key));
  const narrowed = !!query.trim() || filter !== 'all' || kind !== 'all';
  return <Panel className="task-center" aria-labelledby="page-title-tasks">
    {error && <p className="error-text" role="status">{error}</p>}
    {jobs.length > 0 && <div className="task-search"><input type="search" aria-label="搜索任务" placeholder="搜索标题、分集（如 P3）或任务 ID" maxLength={100}
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
    <ul className="task-list">{visible.map(job => {
      const active = isActive(job.state);
      const showBar = job.kind === 'video' && active && job.phase === 'downloading' && !!job.progress;
      // One navigation action per row: results when they exist, retry when the project can rerun, otherwise the project.
      const viewResult = job.kind === 'naming' || !active && withResult.includes(job.kind || '') && ['completed','empty','partial','login_required'].includes(job.state);
      const projectRetry = !active && ['video','analysis'].includes(job.kind || '') && !!job.project_id && retryable.includes(job.state);
      const openProject = !active && !!job.project_id && !viewResult && !projectRetry;
      // The ID and error code stay reachable (hover, and the search box accepts IDs) without a details fold per row.
      return <li key={job.id} title={`任务 ID：${job.id}${job.error_code ? `\n错误码：${job.error_code}` : ''}`}>
      <div className="task-description"><strong>{job.operation === 'translation' ? 'AI 翻译' : names[job.kind || ''] || '任务'} · <span translate="no">{job.project_title || job.title || job.id.slice(0,8)}</span>{job.part ? <span className="task-part">P{job.part}</span> : null}</strong><p>{phases[job.phase || job.state] || job.state}{job.queue_position ? ` · 队列第 ${job.queue_position} 项` : ''}{job.progress?.total ? ` · ${job.progress.done || 0}/${job.progress.total} 集` : ''}{active && !showBar && job.progress?.bytes ? ` · ${bytes(job.progress.bytes)}${job.progress.total_bytes ? ' / ' + bytes(job.progress.total_bytes) : ''}` : ''}{!active && job.elapsed_seconds ? ` · ${duration(job.elapsed_seconds)}` : ''}</p>
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
