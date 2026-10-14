import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import { isActive, pollJob, remember, remembered, cancelTask } from '../../lib/jobs';
import type { SubtitleJob } from '../../lib/api';

export default function useSubtitles(source: string) {
  const [loginOpen, setLoginOpen] = useState(false);
  const [checkingLogin, setCheckingLogin] = useState(false);
  const pendingSelection = useRef<{ text: string; scope: string; episodes: string } | null>(null);
  const [scope, setScope] = useState<'current' | 'all' | 'custom'>('current');
  const [episodes, setEpisodes] = useState('');
  const [jobSource, setJobSource] = useState<string | null>(null);
  const downloadButton = useRef<HTMLButtonElement>(null);
  const [job, setJob] = useState<SubtitleJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const cancellation = useRef<AbortController | null>(null);
  const active = useRef<AbortController | null>(null);
  const lastJob = useRef<string | null>(null);

  useEffect(() => {
    function resume(identifier: string) {
      active.current?.abort();
      const controller=new AbortController();active.current=controller;lastJob.current=identifier;
      setJobSource(null);remember('subtitles',identifier);setBusy(true);setError('');void poll(identifier,controller);
    }
    const previous=remembered('subtitles');if (previous) resume(previous);
    const listener=(event: Event) => { const detail=(event as CustomEvent<{kind:string;id:string}>).detail;if (detail?.kind==='subtitles') resume(detail.id); };
    window.addEventListener('video-parser:restore-task',listener);
    return () => { active.current?.abort();cancellation.current?.abort();window.removeEventListener('video-parser:restore-task',listener); };
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
    if (selection.scope === 'custom' && !/^\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*$/.test(selection.episodes.trim())) { setError('请填写有效集数，例如 1-5,8。');return; }
    if (selection.scope === 'custom' && selection.episodes.split(',').some(part => { const [first,last] = part.split('-').map(Number);return first < 1 || last !== undefined && last < first; })) { setError('集数从1开始，结束集数不能小于开始集数。');return; }
    setJobSource(selection.text);
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

  async function cancel() {
    if (!job || cancellation.current) return;
    const controller = new AbortController();
    cancellation.current = controller;
    setCancelling(true);
    try { await cancelTask('subtitles', job.id, controller.signal); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '取消请求失败，请重试。'); }
    finally {
      if (!controller.signal.aborted) { cancellation.current = null; setCancelling(false); }
    }
  }

  function refresh() {
    if (!lastJob.current || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setError('');
    setBusy(true);
    void poll(lastJob.current, controller);
  }

  const detached = jobSource !== null && jobSource !== source;
  function closeLogin() {
    setLoginOpen(false); pendingSelection.current = null;
    requestAnimationFrame(() => downloadButton.current?.focus());
  }
  function completeLogin() {
    setLoginOpen(false); requestAnimationFrame(() => downloadButton.current?.focus());
    void start(true);
  }
  return { loginOpen, checkingLogin, scope, setScope, episodes, setEpisodes, job,
    busy, error, cancelling, downloadButton, detached, hasJob: !!lastJob.current,
    matchesCurrentSource: jobSource !== null && jobSource === source,
    start, retryFailed, cancel, refresh, closeLogin, completeLogin };
}
