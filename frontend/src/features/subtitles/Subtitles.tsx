import { useEffect, useRef, useState } from 'react';
import Icon from '../../components/Icon';
import BiliLogin from './BiliLogin';
import ProjectPanel from '../library/ProjectPanel';
import { request } from '../../lib/api';
import { isActive, pollJob, remember, remembered, cancelTask } from '../../lib/jobs';
import type { SubtitleJob } from '../../lib/api';

export default function Subtitles({ source, ready }: { source: string; ready: boolean | undefined }) {
  const [loginOpen, setLoginOpen] = useState(false);
  const [checkingLogin, setCheckingLogin] = useState(false);
  const pendingSelection = useRef<{ text: string; scope: string; episodes: string } | null>(null);
  const [scope, setScope] = useState<'current' | 'all' | 'custom'>('current');
  const [episodes, setEpisodes] = useState('');
  const [job, setJob] = useState<SubtitleJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const lastJob = useRef<string | null>(null);

  useEffect(() => {
    function resume(identifier: string) {
      active.current?.abort();
      const controller=new AbortController();active.current=controller;lastJob.current=identifier;
      remember('subtitles',identifier);setBusy(true);setError('');void poll(identifier,controller);
    }
    const previous=remembered('subtitles');if (previous) resume(previous);
    const listener=(event: Event) => { const detail=(event as CustomEvent<{kind:string;id:string}>).detail;if (detail?.kind==='subtitles') resume(detail.id); };
    window.addEventListener('video-parser:restore-task',listener);
    return () => { active.current?.abort();window.removeEventListener('video-parser:restore-task',listener); };
  }, []);

  async function poll(identifier: string, controller: AbortController) {
    try {
      await pollJob<SubtitleJob>('/subtitles/'+identifier,controller.signal,setJob);
      if (!controller.signal.aborted) { active.current=null;setBusy(false); }
    } catch (reason) {
      if (controller.signal.aborted) return;
      active.current=null;setBusy(false);setError(reason instanceof Error ? reason.message : '无法读取任务状态，请重试连接。');
    }
  }

  async function start(resume = false) {
    if (active.current || !source.trim()) return;
    if (!resume) pendingSelection.current = { text: source, scope, episodes };
    const selection = pendingSelection.current;
    if (!selection) return;
    const controller = new AbortController();
    active.current = controller;
    lastJob.current = null;
    setBusy(true);
    setError('');
    setJob(null);
    try {
      setCheckingLogin(true);
      const login = await request<{ authenticated: boolean }>('/bili-login/status', controller.signal);
      if (controller.signal.aborted) return;
      setCheckingLogin(false);
      if (!login.authenticated) { active.current = null; setBusy(false); setLoginOpen(true); return; }
      const result = await request<SubtitleJob>('/subtitles', controller.signal, selection);
      if (controller.signal.aborted) return;
      lastJob.current = result.id;remember('subtitles',result.id);
      setJob(result);
      if (isActive(result.state)) await poll(result.id, controller);
      else { active.current = null; setBusy(false); }
    } catch (reason) {
      if (controller.signal.aborted) return;
      active.current = null;
      setBusy(false);
      setCheckingLogin(false);
      setError(reason instanceof Error ? reason.message : '无法启动字幕任务。');
    }
  }

  async function retryFailed() {
    if (!job || active.current) return;
    const controller=new AbortController();active.current=controller;setBusy(true);setError('');
    try {
      const next=await request<SubtitleJob>(`/tasks/subtitles/${job.id}/retry`,controller.signal,{});
      lastJob.current=next.id;remember('subtitles',next.id);setJob(next);await poll(next.id,controller);
    } catch (reason) { if (!controller.signal.aborted) { active.current=null;setBusy(false);setError(reason instanceof Error ? reason.message : '重试失败'); } }
  }

  function refresh() {
    if (!lastJob.current || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setError('');
    setBusy(true);
    void poll(lastJob.current, controller);
  }

  return <section className="panel subtitle-panel" aria-labelledby="subtitle-heading">
    <h2 id="subtitle-heading">B站字幕下载</h2>
    <p className="notice">使用上方的视频链接；仅下载平台字幕，不做音频转写。</p>
    {ready === false && <p className="error-text">未找到本机 B站字幕工具或校验脚本，请检查安装路径。</p>}
    <div className="subtitle-controls">
      <div><label htmlFor="subtitle-scope">下载范围</label><select id="subtitle-scope" value={scope} disabled={busy} onChange={event => setScope(event.target.value as typeof scope)}>
        <option value="current">当前分集</option><option value="all">全部分集</option><option value="custom">指定分集</option>
      </select></div>
      {scope === 'custom' && <div className="subtitle-episodes"><label htmlFor="subtitle-episodes">指定集数</label>
        <input id="subtitle-episodes" type="text" maxLength={500} value={episodes} placeholder="例如 1-5,8" disabled={busy} onChange={event => setEpisodes(event.target.value)} /></div>}
      <button type="button" className="primary" disabled={!source.trim() || ready === false || loginOpen || busy || isActive(job?.state) || (scope === 'custom' && !episodes.trim())} onClick={() => { void start(); }}>
        <Icon name={busy ? 'loader-circle' : 'download'} className={busy ? 'spinner' : ''} />{checkingLogin ? '检查登录状态…' : busy ? '下载字幕中…' : '下载字幕'}</button>
    </div>
    <div className={`inset subtitle-status ${error || job?.state === 'failed' || job?.state === 'login_required' ? 'status-error' : ''}`} role="status" aria-live="polite" aria-atomic="true">
      {error || (checkingLogin ? '正在检查 B站登录状态…' : loginOpen ? '等待扫码登录，尚未开始下载字幕。' : '') || job?.message || (busy ? '正在启动本机字幕工具…' : '等待下载字幕')}
    </div>
    <div className="task-inline-actions">{job && isActive(job.state) && <button type="button" onClick={() => { void cancelTask('subtitles',job.id).catch(reason=>setError(String(reason))); }}>取消字幕任务</button>}
      {job && ['partial','failed','cancelled','interrupted'].includes(job.state) && <button type="button" disabled={busy} onClick={() => { void retryFailed(); }}>重试未完成分集</button>}</div>
    {error && lastJob.current && <button type="button" className="subtitle-refresh" onClick={refresh}>刷新字幕任务状态</button>}
    {job?.title && <p className="subtitle-title">{job.title}</p>}
    {job?.results.length ? <ul className="subtitle-results">{job.results.map(item => <li key={item.episode}>
      <div className="subtitle-result-label"><strong>P{item.episode}</strong><span className={item.status === 'failed' ? 'error-text' : ''}>{item.message}</span></div>
      {item.project && <ProjectPanel project={item.project} />}
    </li>)}</ul> : null}
    {job?.results.some(item => item.project) && <p className="subtitle-note">字幕已保存到项目文件夹，无需再次下载。可点击“打开项目文件夹”查看。</p>}
    {job?.state === 'login_required' && <p className="subtitle-note">请点击下载字幕，在工作台弹出的二维码中完成登录后重试。</p>}
    {loginOpen && <BiliLogin onClose={() => { setLoginOpen(false); pendingSelection.current = null; }} onSuccess={() => { setLoginOpen(false); void start(true); }} />}
    {isActive(job?.state) && <p className="subtitle-note">切换链接或清空不会停止已开始的字幕任务。</p>}
  </section>;
}
