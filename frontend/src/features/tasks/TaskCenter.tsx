import { useEffect, useState } from 'react';
import { request } from '../../lib/api';
import { cancelTask, isActive, phases, type TaskInfo } from '../../lib/jobs';
import './tasks.css';

type Preview = { plan_id: string; size_bytes: number; note: string; protected: string[]; usage: Record<string,number|null>; entries: { id:string; kind:string; size_bytes:number; age_hours:number }[] };
const bytes = (value: number) => (value / 1024 / 1024).toFixed(1) + ' MB';
const names: Record<string,string> = { subtitles:'字幕', transcriptions:'转录', video:'视频', analysis:'AI 分析' };
export default function TaskCenter() {
  const [jobs,setJobs] = useState<TaskInfo[]>([]);
  const [error,setError] = useState('');
  const [preview,setPreview] = useState<Preview|null>(null);
  const [notice,setNotice] = useState('');
  const [busy,setBusy] = useState(false);
  const [expanded,setExpanded] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try { const data = await request<{ jobs:TaskInfo[] }>('/tasks',controller.signal);setJobs(data.jobs);setError(''); }
      catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '无法读取任务记录'); }
      finally { if (!controller.signal.aborted) timer=setTimeout(() => { void load(); },document.hidden ? 8000 : 2000); }
    };
    void load(); return () => { controller.abort();clearTimeout(timer); };
  },[]);
  async function cancel(job:TaskInfo) {
    try { await cancelTask(job.kind!,job.id);setNotice('已请求停止本任务；等待进程退出后状态会更新。'); }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : '取消失败'); }
  }
  async function cachePreview() {
    setBusy(true);setNotice('');
    try { setPreview(await request<Preview>('/cache/preview',new AbortController().signal,{})); }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : '预览失败'); }
    finally { setBusy(false); }
  }
  async function clean() {
    if (!preview) return;setBusy(true);
    try { const result = await request<{size_bytes:number;skipped:string[]}>('/cache/clean',new AbortController().signal,{plan_id:preview.plan_id,confirm:true});setPreview(null);setNotice(`清理完成：${bytes(result.size_bytes)}，跳过 ${result.skipped.length} 项变化或不可清理的缓存。`); }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : '清理失败'); }
    finally { setBusy(false); }
  }
  const active = jobs.filter(job => isActive(job.state));
  const visible = expanded ? jobs : [...active,...jobs.filter(job=>!isActive(job.state)).slice(0,5)];
  return <section className="panel task-center" aria-labelledby="task-heading">
    <div className="task-heading"><h2 id="task-heading">任务中心 <span>{active.length} 项进行中</span></h2><button type="button" disabled={busy} onClick={() => { void cachePreview(); }}>缓存管理</button></div>
    <p className="notice">刷新页面可重连。服务重启会标记中断，不会假装续传或自动重放 AI 请求。取消 AI 只停止本机工作，无法撤销服务方已产生的费用。</p>
    {error && <p className="error-text" role="status">{error}</p>}
    <ul className="task-list">{visible.map(job => <li key={job.id}>
      <div><strong>{names[job.kind || ''] || '任务'} · {job.title || job.id.slice(0,8)}</strong><p>{phases[job.phase || job.state] || job.state}{job.queue_position ? ` · 队列第 ${job.queue_position} 项` : ''}{job.progress?.total ? ` · ${job.progress.done || 0}/${job.progress.total} 集` : ''}{job.progress?.bytes ? ` · ${bytes(job.progress.bytes)}${job.progress.total_bytes ? ' / ' + bytes(job.progress.total_bytes) : ''}` : ''}</p><small>{job.message} {job.error_code ? `[${job.error_code}]` : ''}</small><small>任务 {job.id.slice(0,12)}{job.elapsed_seconds ? ` · ${job.elapsed_seconds.toFixed(1)} 秒` : ''}</small></div>
      <div className="task-actions">{isActive(job.state) && <button type="button" onClick={() => { void cancel(job); }}>取消任务</button>}
        {['subtitles','transcriptions'].includes(job.kind || '') && <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail:{kind:job.kind,id:job.id}}))}>查看结果</button>}
        {job.project_id && !isActive(job.state) && <a className="button" href={'?project='+job.project_id}>打开项目</a>}
      </div>
    </li>)}</ul>
    {!jobs.length && !error && <p className="notice">暂无任务。结果文件始终保留在项目目录。</p>}
    {jobs.length > 5 && <button type="button" onClick={() => setExpanded(!expanded)}>{expanded?'收起历史':'查看最近任务'}</button>}
    {notice && <p role="status">{notice}</p>}
    {preview && <div className="cache-preview"><h3>清理预览</h3><p>{preview.note}</p><p>临时字幕副本：{bytes(preview.usage.subtitle_scratch || 0)} · 视频/分析临时副本：{bytes(preview.usage.workflow_scratch || 0)} · 可复用字幕缓存：{bytes(preview.usage.subtitle_reuse_cache || 0)}</p><p>不会删除：{preview.protected.join('、')}。</p>
      <ul>{preview.entries.map(item=><li key={item.id}>{item.id.slice(0,12)} · {bytes(item.size_bytes)} · {item.age_hours} 小时前</li>)}</ul>
      <p>可清理 {preview.entries.length} 项，共 {bytes(preview.size_bytes)}。确认有效期 10 分钟。</p>
      <button type="button" disabled={busy || !!active.length || !preview.entries.length} onClick={() => { void clean(); }}>确认清理上述临时缓存</button> <button type="button" disabled={busy} onClick={()=>setPreview(null)}>不清理</button>
    </div>}
  </section>;
}
