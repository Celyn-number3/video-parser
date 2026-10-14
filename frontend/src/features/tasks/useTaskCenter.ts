import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import { cancelTask, isActive, type TaskInfo } from '../../lib/jobs';
import useTaskHistory from './useTaskHistory';

export default function useTaskCenter(onActivityChange?: (count: number | null) => void) {
  const { jobs: polled, error, loaded } = useTaskHistory(onActivityChange);
  // Records removed by "清理" are hidden at once instead of waiting for the next 2 s poll.
  const [cleared,setCleared] = useState<string[]>([]);
  const jobs = cleared.length ? polled.filter(job => !cleared.includes(job.id)) : polled;
  const dead = jobs.filter(job => ['failed','cancelled','interrupted'].includes(job.state));
  const [clearing,setClearing] = useState(false);
  const [notice,setNotice] = useState('');
  const [filter,setFilter] = useState('all');
  // Type filter (video / subtitles / transcriptions / analysis), combined with the status filter.
  const [kind,setKind] = useState('all');
  const [retrying,setRetrying] = useState<string[]>([]);
  const retries = useRef(new Set<string>());
  const [pendingCancels, setPendingCancels] = useState<string[]>([]);
  const cancellations = useRef(new Map<string, AbortController>());
  useEffect(() => () => { for (const controller of cancellations.current.values()) controller.abort(); }, []);
  async function cancel(job:TaskInfo) {
    if (cancellations.current.has(job.id)) return;
    const controller = new AbortController();
    cancellations.current.set(job.id, controller);
    setPendingCancels(current => [...current, job.id]);
    try {
      await cancelTask(job.kind!, job.id, controller.signal);
      if (!controller.signal.aborted) setNotice('已请求停止本任务；等待进程退出后状态会更新。');
    } catch (reason) {
      if (!controller.signal.aborted) setNotice(reason instanceof Error ? reason.message : '取消请求失败，请重试。');
    } finally {
      cancellations.current.delete(job.id);
      if (!controller.signal.aborted) setPendingCancels(current => current.filter(id => id !== job.id));
    }
  }
  const visible = jobs.filter(job => kind === 'all' || job.kind === kind).filter(job => filter === 'all' || filter === 'active' && isActive(job.state) || filter === 'completed' && ['completed','empty'].includes(job.state) || filter === 'unfinished' && ['failed','cancelled','interrupted','partial','login_required'].includes(job.state));
  async function clearDead() {
    if (clearing) return;
    const ids = dead.map(job => job.id);
    setClearing(true);
    try {
      const result = await request<{ removed: number }>('/tasks/clear', new AbortController().signal, { confirm: true });
      setCleared(current => [...current, ...ids]);
      setNotice(`已清理 ${result.removed} 条任务记录。`);
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '清理失败，请重试。'); }
    finally { setClearing(false); }
  }
  async function retry(job: TaskInfo) {
    if (retries.current.has(job.id)) return;
    retries.current.add(job.id);setRetrying(current => [...current,job.id]);
    try {
      const result = await request<TaskInfo>(`/tasks/subtitles/${job.id}/retry`,new AbortController().signal,{});
      window.dispatchEvent(new CustomEvent('video-parser:restore-task',{detail:{kind:'subtitles',id:result.id}}));
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '重试失败，请检查后再试。'); }
    finally { retries.current.delete(job.id);setRetrying(current => current.filter(id => id !== job.id)); }
  }
  return { jobs, error, loaded, notice, filter, setFilter, kind, setKind, retrying,
    pendingCancels, visible, cancel, retry, deadCount: dead.length, clearing, clearDead };
}
