import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import { isActive, pollJob, remember, remembered, cancelTask } from '../../lib/jobs';
import type { Media, ProjectSummary, TranscriptionJob, TranscriptionSource } from '../../lib/api';

export type SourceMode = 'upload' | 'video';
// platform = download Bilibili's own subtitles; transcribe = local Whisper.
export type Method = 'platform' | 'transcribe';
// source = the video's own project; default = outputs/transcriptions; project = another project; folder = a picked folder.
export type Destination = 'source' | 'default' | 'project' | 'folder';
// The workbench video when it is a Bilibili video that has not been archived yet: platform subtitles still work.
export type PendingSource = { source_url: string; title: string; platform: string; part: number | null; project_id: string };
export const PENDING_PREFIX = 'pending|';
export type ForcedLanguage = 'zh' | 'en';
// What was last submitted, so a wrongly detected language can be retried on the same input.
type Submission = { kind: 'upload'; file: File } | { kind: 'video'; project_id: string; resource: string; title: string };
export const sourceKey = (source: { project_id: string; resource: string }) => source.project_id + '|' + source.resource;

export type TranscriptionOptions = { projectId?: string; media: Media | null; uploadLimit?: number; reuseModel?: boolean;
  pending?: PendingSource | null; focusRequest?: number };
export default function useTranscription({ projectId, media, uploadLimit, reuseModel: reusePreference = false, pending = null, focusRequest = 0 }: TranscriptionOptions) {
  const [mode, setModeState] = useState<SourceMode>('upload');
  const [method, setMethod] = useState<Method>('transcribe');
  const [destination, setDestination] = useState<Destination>('default');
  const [targetProject, setTargetProject] = useState('');
  const [folder, setFolder] = useState('');
  const [picking, setPicking] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [saveNotice, setSaveNotice] = useState('');
  // Archived videos: null = not loaded yet. The current workbench video is preselected when it is in the list.
  const [sources, setSources] = useState<TranscriptionSource[] | null>(null);
  const [sourcesError, setSourcesError] = useState('');
  const [selectedKey, setSelectedKey] = useState('');
  const lastSubmission = useRef<Submission | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  // Language actually requested for the shown job; when forced, Whisper reports that language back instead of detecting.
  const [requested, setRequested] = useState<'auto' | ForcedLanguage>('auto');
  const [batchFiles,setBatchFiles]=useState<File[]>([]);
  // Preference lives in Settings; a multi-file batch always reuses the loaded model.
  const reuseModel = reusePreference || batchFiles.length > 1;
  const [batchNotice,setBatchNotice]=useState('');
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const cancellation = useRef<AbortController | null>(null);
  const active = useRef<AbortController | null>(null);
  const lastId = useRef<string | null>(null);
  const limit = uploadLimit ?? 512 * 1024 * 1024;
  const running = isActive(job?.state);

  useEffect(() => {
    function resume(identifier: string) {
      active.current?.abort();
      const controller=new AbortController();active.current=controller;lastId.current=identifier;
      // A task restored from the task center has no local input to resubmit.
      lastSubmission.current=null;setCanRetry(false);setRequested('auto');syncToJob.current=true;restoring.current=true;
      remember('transcriptions',identifier);setBusy(true);setError('');void poll(identifier,controller);
    }
    const previous=remembered('transcriptions');if (previous) resume(previous);
    const listener=(event: Event) => { const detail=(event as CustomEvent<{kind:string;id:string}>).detail;if (detail?.kind==='transcriptions') resume(detail.id); };
    window.addEventListener('video-parser:restore-task',listener);
    return () => { active.current?.abort();cancellation.current?.abort();window.removeEventListener('video-parser:restore-task',listener); };
  }, []);

  async function poll(identifier: string, controller: AbortController) {
    try {
      await pollJob<TranscriptionJob>('/transcriptions/'+identifier,controller.signal,value => { restoring.current=false;setJob(value); });
      if (!controller.signal.aborted) { active.current=null;setBusy(false); }
    } catch (reason) {
      if (controller.signal.aborted) return;
      active.current=null;setBusy(false);
      // A remembered task whose record was cleaned up is simply forgotten, not reported as an error.
      if (restoring.current) { restoring.current=false;lastId.current=null;try { localStorage.removeItem('video-parser:task:transcriptions'); } catch { /* optional */ } return; }
      setError(reason instanceof Error ? reason.message : '无法读取任务状态，请重试连接。');
    }
  }

  // A restored task (page reload or task center) switches the page to that task's own source,
  // so its result is never shown under an unrelated selection.
  const syncToJob = useRef(false);
  const restoring = useRef(false);
  useEffect(() => {
    if (!syncToJob.current || !job) return;
    if (!job.source_project_id) { syncToJob.current = false; setMode('upload'); return; }
    setMode('video');
    if (!sources) return;
    syncToJob.current = false;
    const match = sources.find(item => item.project_id === job.source_project_id && item.resource === job.source_resource);
    if (match) {
      chooseSource(sourceKey(match));
      lastSubmission.current = { kind: 'video', project_id: match.project_id, resource: match.resource, title: match.title };
      setCanRetry(true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job, sources]);

  const sourcesLoaded = useRef(false);
  const [sourcesVersion, setSourcesVersion] = useState(0);
  useEffect(() => {
    // Load once up front (for the tab count), then refresh each time the archived tab is opened.
    if (mode !== 'video' && sourcesLoaded.current) return;
    sourcesLoaded.current = true;
    const controller = new AbortController();
    setSourcesError('');
    request<{ sources: TranscriptionSource[] }>('/transcriptions/sources', controller.signal).then(data => {
      setSources(data.sources);
      setSelectedKey(current => data.sources.some(item => sourceKey(item) === current) ? current
        : projectId && media && data.sources.some(item => item.project_id === projectId && item.resource === media.resource) ? projectId + '|' + media.resource : '');
    }).catch((reason: unknown) => { if (!controller.signal.aborted) { setSources([]); setSourcesError(reason instanceof Error ? reason.message : '服务没有响应'); } });
    return () => controller.abort();
  }, [mode, projectId, media, sourcesVersion]);
  const reloadSources = () => { setSources(null); setSourcesVersion(value => value + 1); };
  const pendingKey = pending ? PENDING_PREFIX + pending.source_url : '';
  // An archived copy wins over the not-yet-archived workbench entry.
  const showPending = !!pending && !(sources || []).some(item => item.project_id === pending.project_id);
  const pendingSource: TranscriptionSource | null = pending && showPending ? { project_id: '', resource: '', title: pending.title, platform: pending.platform,
    source_url: pending.source_url, part: pending.part, quality: '', duration_seconds: null, size_bytes: 0, archived_at: '' } : null;
  const selectedSource = selectedKey === pendingKey && pendingSource ? pendingSource : sources?.find(item => sourceKey(item) === selectedKey) || null;
  const isBilibili = mode === 'video' && selectedSource?.platform === '哔哩哔哩' && !!selectedSource.source_url;
  const archived = !!selectedSource?.project_id;

  function setMode(next: SourceMode) {
    setModeState(next);
    setDestination(current => next === 'video' ? (current === 'default' ? 'source' : current) : (current === 'source' ? 'default' : current));
  }
  // Each new selection starts from its natural method: Bilibili → platform subtitles first.
  // A platform-subtitle task restored from the task center keeps showing until the user picks a source.
  const keepPlatform = useRef(false);
  useEffect(() => {
    if (!keepPlatform.current) setMethod(isBilibili ? 'platform' : 'transcribe');
  }, [selectedKey, isBilibili]);
  function chooseSource(key: string) { keepPlatform.current = false; setSelectedKey(key); }
  useEffect(() => { if (!archived && method === 'transcribe' && selectedKey === pendingKey && pendingSource) setMethod('platform'); }, [archived, method, selectedKey, pendingKey, pendingSource]);
  // Workbench "生成字幕": open the video tab with the current video selected.
  useEffect(() => {
    if (!focusRequest) return;
    setMode('video'); keepPlatform.current = false;
    if (!sources) return;
    const exact = projectId && media ? sources.find(item => item.project_id === projectId && item.resource === media.resource) : undefined;
    const sameProject = projectId ? sources.find(item => item.project_id === projectId) : undefined;
    const match = exact || sameProject;
    setSelectedKey(match ? sourceKey(match) : pendingKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest, sources === null]);
  useEffect(() => {
    // A restored platform-subtitle task is shown in the video tab.
    const listener=(event: Event) => { const detail=(event as CustomEvent<{kind:string}>).detail;if (detail?.kind==='subtitles') { keepPlatform.current=true;setMode('video');setMethod('platform'); } };
    window.addEventListener('video-parser:restore-task',listener);
    return () => window.removeEventListener('video-parser:restore-task',listener);
  }, []);

  // Projects (for "其他项目") and the last picked folder are loaded once.
  const [projectsVersion, setProjectsVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    request<{ projects: ProjectSummary[] }>('/projects', controller.signal).then(data => setProjects(data.projects)).catch(() => { if (!controller.signal.aborted) setProjects([]); });
    return () => controller.abort();
  }, [projectsVersion, sourcesVersion]);
  useEffect(() => {
    const controller = new AbortController();
    request<{ folders: { path: string; exists: boolean }[] }>('/folders', controller.signal)
      .then(data => setFolder(current => current || data.folders.find(item => item.exists)?.path || '')).catch(() => {});
    return () => controller.abort();
  }, []);
  async function pickFolder() {
    if (picking) return;
    setPicking(true); setSaveNotice('已在电脑上打开“选择文件夹”窗口，请在窗口里选择；如果没看到，看看任务栏。');
    try {
      const result = await request<{ path: string | null }>('/folders/pick', new AbortController().signal, {});
      if (result.path) { setFolder(result.path); setDestination('folder'); setSaveNotice(''); }
      else setSaveNotice(folder ? '' : '没有选择文件夹。');
    } catch (reason) { setSaveNotice(reason instanceof Error ? reason.message : '无法打开选择文件夹窗口。'); }
    finally { setPicking(false); }
  }
  const destinationReady = destination === 'project' ? !!targetProject : destination === 'folder' ? !!folder : true;
  function destinationParams(): Record<string, string> {
    if (destination === 'project') return { destination, target_project_id: targetProject };
    if (destination === 'folder') return { destination, folder };
    return { destination };
  }
  async function openSaved() {
    if (!job) return;
    try { const result = await request<{ message: string }>(`/transcriptions/${job.id}/open`, new AbortController().signal, {}); setSaveNotice(result.message); }
    catch (reason) { setSaveNotice(reason instanceof Error ? reason.message : '无法打开保存文件夹。'); }
  }

  function selectFiles(items: File[]) {
    const supported = /\.(wav|mp3|m4a|flac|ogg|opus|aac|wma|mp4|mkv|webm|mov|avi|m4v)$/i;
    const selected = items.slice(0,32).filter(item => item.size > 0 && item.size <= limit && (item.type.startsWith('audio/') || item.type.startsWith('video/') || supported.test(item.name)));
    setBatchFiles(selected);setFile(selected[0] || null);
    setBatchNotice(selected.length > 1 ? `已选择 ${selected.length} 个文件，将分别排队；单个失败不影响后续。` : '');
    setError(items.length > 32 ? '最多32个文件，已保留前32项中的有效素材。' : selected.length !== items.length ? '已过滤空文件、超限文件或非音视频素材。' : '');
  }

  // language: 'auto' by default; zh/en only when retrying a wrongly detected result.
  async function start(language: 'auto' | ForcedLanguage = 'auto', retry?: Submission) {
    if (active.current) return;
    if (!retry && mode === 'upload' && (!file || !file.size || file.size > limit)) {
      setError('请选择非空音视频文件，大小不能超过 ' + Math.round(limit / 1024 / 1024) + ' MB。');
      return;
    }
    if (!retry && mode === 'video' && !selectedSource?.project_id) return;
    if (!retry && !destinationReady) { setError(destination === 'project' ? '请选择要保存到的项目。' : '请先选择保存文件夹。'); return; }
    const output = destinationParams();
    const submission: Submission | null = retry || (mode === 'video' && selectedSource
      ? { kind: 'video', project_id: selectedSource.project_id, resource: selectedSource.resource, title: selectedSource.title }
      : batchFiles.length > 1 ? null : { kind: 'upload', file: file! });
    lastSubmission.current = submission; setCanRetry(!!submission); setRequested(language);
    const controller = new AbortController();
    active.current = controller;
    lastId.current = null;
    setBusy(true);
    setError('');
    setJob(null);
    try {
      if (!submission) {
        const submitted:TranscriptionJob[]=[];const rejected:string[]=[];
        for (const item of batchFiles.slice(0,32)) {
          if (controller.signal.aborted) return;
          try {
            if (!item.size || item.size>limit) throw new Error('大小不符合要求');
            const next=await request<TranscriptionJob>('/transcriptions/upload?'+new URLSearchParams({filename:item.name,language,reuse_model:String(reuseModel),...output}),controller.signal,item);submitted.push(next);
          } catch (reason) { if (controller.signal.aborted) return;rejected.push(item.name+': '+String(reason)); }
        }
        setBatchNotice(`批量提交 ${submitted.length} 个任务；失败 ${rejected.length} 个。所有任务和结果可在任务中心查看。`+(rejected.length?' '+rejected.join('；'):''));
        const last=submitted.at(-1);
        if (last) { lastId.current=last.id;remember('transcriptions',last.id);setJob(last);await poll(last.id,controller); }
        else { active.current=null;setBusy(false); }
        return;
      }
      const path = submission.kind === 'upload'
        ? '/transcriptions/upload?' + new URLSearchParams({ filename: submission.file.name, language, reuse_model:String(reuseModel), ...output })
        : '/transcriptions';
      const body = submission.kind === 'upload' ? submission.file : { project_id: submission.project_id, resource: submission.resource, language, reuse_model:reuseModel, ...output };
      const result = await request<TranscriptionJob>(path, controller.signal, body);
      if (controller.signal.aborted) return;
      lastId.current = result.id;remember('transcriptions',result.id);
      setJob(result);
      await poll(result.id, controller);
    } catch (reason) {
      if (controller.signal.aborted) return;
      active.current = null;
      setBusy(false);
      setError(reason instanceof Error ? reason.message : '无法启动转录任务。');
    }
  }

  function retryAs(language: ForcedLanguage) {
    if (lastSubmission.current) void start(language, lastSubmission.current);
  }

  async function cancel() {
    if (!job || cancellation.current) return;
    const controller = new AbortController();
    cancellation.current = controller;
    setCancelling(true);
    try { await cancelTask('transcriptions', job.id, controller.signal); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '取消请求失败，请重试。'); }
    finally {
      if (!controller.signal.aborted) { cancellation.current = null; setCancelling(false); }
    }
  }

  function refresh() {
    if (!lastId.current || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setError('');
    setBusy(true);
    void poll(lastId.current, controller);
  }

  return { method, setMethod, destination, setDestination, targetProject, setTargetProject, folder, picking, pickFolder, projects,
    reloadProjects: () => setProjectsVersion(value => value + 1), saveNotice, destinationReady, openSaved,
    pendingSource, pendingKey, isBilibili, archived, chooseSource,
    effectiveMethod: (mode === 'upload' ? 'transcribe' : method) as Method,
    mode, setMode, sources, sourcesError, selectedKey, setSelectedKey, selectedSource, reloadSources, canRetry, requested, retryAs, batchFiles,
    batchNotice, file, job, busy, error, cancelling, limit, running, hasJob: !!lastId.current,
    selectFiles, start, cancel, refresh };
}
