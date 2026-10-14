import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { request } from './lib/api';
import { cancelTask, isActive, pollJob, remember, remembered, runWorkflow } from './lib/jobs';
import type { TaskInfo, WorkflowJob } from './lib/jobs';
import TaskCenter from './features/tasks/TaskCenter';
import Icon from './components/Icon';
import BiliLogin from './features/subtitles/BiliLogin';
import Transcription from './features/transcription/Transcription';
import Accounts from './features/accounts/Accounts';
import ProjectPanel from './features/library/ProjectPanel';
import SettingsDialog from './features/settings/PreferencesDialog';
import { preferredQualityId } from './features/settings/settings';
import usePreferences from './features/settings/usePreferences';
import WorkbenchLayout from './components/WorkbenchLayout';
import WorkbenchPage from './components/WorkbenchPage';
import Panel, { PanelTitle } from './components/Panel';
import FormField from './components/FormField';
import ProgressBar from './components/ProgressBar';
import type { Page } from './features/navigation/navigation';
import type { Configuration, Media, ParsedVideo } from './lib/api';

// Re-tested 2026-10-14 (docs/mcp-platform-probe-20261014.md). 小红书 needs a login, so it has no example.
const examples: Record<string, string> = {
  "哔哩哔哩": "https://www.bilibili.com/video/BV1kKWA6uEyr",
  "抖音": "https://www.douyin.com/video/7696088077957090575",
  "YouTube": "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
};
const tabs = [
  { name: '封面图片', id: 0, icon: 'image' },
  { name: '视频预览', id: 1, icon: 'circle-play' },
  { name: 'AI 分析', id: 2, icon: 'scan-eye' },
] as const;
type Tab = typeof tabs[number]['name'];
type Operation = 'prepare' | 'analyze';
type ProjectState = { parsed: ParsedVideo; quality: string; status: string; error: boolean; busy: Operation | null; analysis: string; task?: TaskInfo };
// Routine states already shown by the stage, button or quality select; the inspector stays quiet for these.
const QUIET_STATUS = new Set(['等待解析', '解析完成，请选择画质后归档', '已复用归档视频', '已选择归档视频', '所选画质尚未归档', '所选视频已归档', '画面分析完成']);
const validId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
const loginPlatforms: [RegExp, string][] = [[/小红书|xiaohongshu|xhslink/, 'xiaohongshu'], [/抖音|douyin/, 'douyin'], [/B站|bilibili|b23\.tv/, 'bilibili']];
function parseLoginPlatform(message: string, source: string) {
  return loginPlatforms.find(([pattern]) => pattern.test(message) || pattern.test(source))?.[1] || null;
}
function formatDuration(seconds: number) {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export default function App() {
  const [page, setPage] = useState<Page>('workspace');
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobile, setMobile] = useState(() => matchMedia('(max-width:760px)').matches);
  const [source, setSource] = useState('');
  const [projectStates, setProjectStates] = useState<Record<string, ProjectState>>({});
  const projects = useRef(projectStates);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const selected = selectedId ? projectStates[selectedId] : undefined;
  const parsed = selected?.parsed || null;
  const quality = selected?.quality || '';
  const media = parsed?.qualities.find(item => item.id === quality)?.media || null;
  const busy = selected?.busy || null;
  const [parsing, setParsing] = useState(false);
  const [parseStatus, setParseStatus] = useState('等待解析');
  const [parseError, setParseError] = useState(false);
  const [tab, setTab] = useState<Tab>('封面图片');
  // 生成字幕 → 字幕与转写 with the current video selected; B站 login from the quality notice.
  const [subtitleFocus, setSubtitleFocus] = useState(0);
  const [qualityLogin, setQualityLogin] = useState<'closed' | 'open' | 'done'>('closed');
  const [accountFocus, setAccountFocus] = useState<string | null>(null);
  function openAccounts(platform: string | null = null) { setAccountFocus(platform); navigate('accounts', true); }
  const [config, setConfig] = useState<Configuration | null>(null);
  const [configError, setConfigError] = useState('');
  const { settings, saveStatus: settingsSaveStatus, saveSettings } = usePreferences();
  const settingsRef = useRef(settings); settingsRef.current = settings;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsReturn = useRef<HTMLButtonElement | null>(null);
  const [archiveReminder, setArchiveReminder] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [count, setCount] = useState('6');
  const [consent, setConsent] = useState(false);
  const [coverError, setCoverError] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [activeCount, setActiveCount] = useState<number | null>(null);
  const [cancellingTask, setCancellingTask] = useState<string | null>(null);
  const parseEpoch = useRef(0);
  const parsingRequest = useRef<AbortController | null>(null);
  const workflowRequests = useRef(new Map<string, AbortController>());
  const restoreRequests = useRef(new Set<AbortController>());
  const projectNavigation = useRef(0);
  const tabButtons = useRef<(HTMLButtonElement | null)[]>([]);
  const sourceInput = useRef<HTMLTextAreaElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const pageRef = useRef(page); pageRef.current = page;

  function updateProject(id: string, update: (value: ProjectState) => ProjectState) {
    const value = projects.current[id];
    if (!value) return;
    const next = { ...projects.current, [id]: update(value) };
    projects.current = next; setProjectStates(next);
  }
  function installProject(result: ParsedVideo, restoredAnalysis = '', restoring = false) {
    const id = result.project.id;
    const previous = projects.current[id];
    const chosen = previous?.busy ? previous.quality : restoring ? result.default_quality_id || '' : preferredQualityId(result.qualities, result.default_quality_id, settingsRef.current.qualityPreference);
    const next: ProjectState = {
      parsed: result, quality: chosen, status: previous?.busy ? previous.status : result.warning || (result.qualities.find(item => item.id === chosen)?.media ? '已复用归档视频' : '解析完成，请选择画质后归档'),
      error: false, busy: previous?.busy || null, analysis: restoredAnalysis || previous?.analysis || '',
    };
    projects.current = { ...projects.current, [id]: next }; setProjectStates(projects.current);
    return id;
  }
  function selectProject(id: string) {
    const value = projects.current[id]; if (!value) return;
    selectedRef.current = id; setSelectedId(id); setSource(value.parsed.source_url);
    setConsent(false); setCoverError(false); setVideoError(false); setParseError(false); setArchiveReminder(false);
    const url = new URL(location.href); url.searchParams.set('project', id); history.replaceState(null, '', url);
    try { localStorage.setItem('video-parser:last-project', id); localStorage.setItem('video-parser:last-quality', value.parsed.qualities.find(item => item.id === value.quality)?.media?.resource || ''); } catch { /* Optional restore. */ }
  }
  function navigate(next: Page, focus = false) {
    const changed = next !== pageRef.current;
    setPage(next); setMenuOpen(false);
    if (changed || focus) requestAnimationFrame(() => {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
      if (focus) document.getElementById('page-title-' + next)?.focus({ preventScroll: true });
    });
  }
  function openSettings(button: HTMLButtonElement) { settingsReturn.current = button; setMenuOpen(false); setSettingsOpen(true); }
  function closeSettings() {
    setSettingsOpen(false);
    requestAnimationFrame(() => {
      if (settingsReturn.current?.getClientRects().length && !settingsReturn.current.closest('[inert]')) settingsReturn.current.focus();
      else menuButton.current?.focus();
    });
  }
  async function restoreProject(id: string, qualityResource = '', focus = true) {
    if (!validId(id)) return;
    const version = ++projectNavigation.current;
    const parseVersion = parseEpoch.current;
    const controller = new AbortController(); restoreRequests.current.add(controller);
    try {
      const result = await request<ParsedVideo & { analysis: string }>(`/projects/${id}/resume?quality_id=${encodeURIComponent(qualityResource)}`, controller.signal);
      if (controller.signal.aborted) return;
      const restoredId = installProject(result, result.analysis, true);
      if (version !== projectNavigation.current || parseVersion !== parseEpoch.current) return;
      // Archived projects open on the playable video; un-archived ones on the cover. Callers may still override the tab.
      const restoredMedia = result.qualities.find(item => item.id === (result.default_quality_id || ''))?.media;
      selectProject(restoredId); setTab(restoredMedia ? '视频预览' : '封面图片'); if (focus) navigate('workspace', true);
    } catch (reason) {
      if (!controller.signal.aborted && focus && version === projectNavigation.current && parseVersion === parseEpoch.current) { setParseStatus(reason instanceof Error ? reason.message : '无法恢复视频项目。'); setParseError(true); navigate('workspace', true); }
    } finally { restoreRequests.current.delete(controller); }
  }

  // Workflow controllers belong to projects, not to the currently displayed page/link.
  function watchWorkflow(job: WorkflowJob<Media | { text: string }>, controller: AbortController) {
    const id = job.project_id;
    if (!id || !projects.current[id]) return;
    const operation: Operation = job.kind === 'analysis' ? 'analyze' : 'prepare';
    workflowRequests.current.set(id, controller);
    updateProject(id, value => ({ ...value, busy: operation, status: job.message, task: job, error: false }));
    void (async () => {
      try {
        const final = isActive(job.state) ? await pollJob<WorkflowJob<Media | { text: string }>>('/tasks/' + job.id, controller.signal,
          item => updateProject(id, value => ({ ...value, status: item.message, task: item }))) : job;
        if (controller.signal.aborted) return;
        if (final.state !== 'completed') throw new Error(final.message);
        applyWorkflowResult(id, final.result);
      } catch (reason) {
        if (!controller.signal.aborted) updateProject(id, value => ({ ...value, error: true, status: reason instanceof Error ? reason.message : '任务状态读取失败，请在任务中心重试查看。' }));
      } finally {
        if (workflowRequests.current.get(id) === controller) { workflowRequests.current.delete(id); updateProject(id, value => ({ ...value, busy: null })); }
      }
    })();
  }
  function applyWorkflowResult(id: string, result: Media | { text: string }) {
    if ('text' in result) updateProject(id, value => ({ ...value, analysis: result.text, status: '画面分析完成', error: false }));
    else {
      updateProject(id, value => ({ ...value, parsed: { ...value.parsed, qualities: value.parsed.qualities.map(item => item.id === result.quality_id ? { ...item, media: result } : item) }, status: '所选视频已归档', error: false }));
      // Once the archive is ready, move from the cover to the playable video.
      if (selectedRef.current === id) setTab(current => current === '封面图片' ? '视频预览' : current);
    }
  }
  async function restoreWorkflow(identifier: string, explicit: boolean) {
    const controller = new AbortController(); restoreRequests.current.add(controller);
    const version = projectNavigation.current;
    const parseVersion = parseEpoch.current;
    try {
      const job = await request<WorkflowJob<Media | { text: string }>>('/tasks/' + identifier, controller.signal);
      if (!validId(job.project_id) || !['video', 'analysis'].includes(job.kind || '')) return;
      const id = job.project_id;
      if (!projects.current[id]) {
        const resumed = await request<ParsedVideo & { analysis: string }>(`/projects/${id}/resume`, controller.signal);
        if (controller.signal.aborted) return;
        installProject(resumed, resumed.analysis, true);
      }
      if (explicit && version === projectNavigation.current && parseVersion === parseEpoch.current) {
        // Resumed projects key archived files as saved-*, so match the finished task by its archived resource first.
        if (job.state === 'completed' && job.result && 'quality_id' in job.result) {
          const result = job.result as Media;
          updateProject(id, value => {
            const match = value.parsed.qualities.find(item => item.media?.resource === result.resource) || value.parsed.qualities.find(item => item.id === result.quality_id);
            return match ? { ...value, quality: match.id } : value;
          });
        }
        selectProject(id); setTab(job.kind === 'analysis' ? 'AI 分析' : '视频预览'); navigate('workspace', true);
      }
      if (isActive(job.state)) {
        if (workflowRequests.current.has(id)) return;
        watchWorkflow(job, controller);
      }
      else if (job.state === 'completed' && explicit) applyWorkflowResult(id, job.result);
      else if (explicit) updateProject(id, value => ({ ...value, error: true, status: job.message }));
    } catch (reason) {
      if (!controller.signal.aborted && explicit) { setParseStatus(reason instanceof Error ? reason.message : '无法读取任务结果。'); setParseError(true); }
    } finally { restoreRequests.current.delete(controller); }
  }
  useEffect(() => {
    const controller = new AbortController();
    request<Configuration>('/config', controller.signal).then(setConfig).catch((reason: unknown) => {
      if (!controller.signal.aborted) setConfigError(reason instanceof Error ? reason.message : '无法读取服务配置。');
    });
    try {
      const last = new URLSearchParams(location.search).get('project') || localStorage.getItem('video-parser:last-project');
      if (last) void restoreProject(last, localStorage.getItem('video-parser:last-quality') || '', false);
    } catch { /* Restore cannot block a fresh start. */ }
    for (const kind of ['video', 'analysis']) { const id = remembered(kind); if (id) void restoreWorkflow(id, false); }
    const restore = (event: Event) => {
      const detail = (event as CustomEvent<{ kind?: string; id?: string; projectId?: string }>).detail;
      if (validId(detail?.projectId)) { void restoreProject(detail.projectId); return; }
      if (!validId(detail?.id)) return;
      if (detail.kind === 'transcriptions') navigate('transcription', true);
      else if (detail.kind === 'subtitles') navigate('transcription', true);
      else if (['video', 'analysis'].includes(detail.kind || '')) { ++projectNavigation.current; void restoreWorkflow(detail.id, true); }
    };
    window.addEventListener('video-parser:restore-task', restore);
    return () => {
      controller.abort(); parsingRequest.current?.abort();
      for (const request of workflowRequests.current.values()) request.abort();
      for (const request of restoreRequests.current) request.abort();
      window.removeEventListener('video-parser:restore-task', restore);
    };
  }, []);
  useEffect(() => {
    const query = matchMedia('(max-width:760px)');
    const change = () => { setMobile(query.matches); if (!query.matches) setMenuOpen(false); };
    query.addEventListener('change', change); return () => query.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (!menuOpen) return;
    sidebar.current?.querySelector<HTMLButtonElement>('[aria-current="page"]')?.focus();
    const key = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setMenuOpen(false); requestAnimationFrame(() => menuButton.current?.focus()); }
      if (event.key !== 'Tab') return;
      const buttons = Array.from(sidebar.current?.querySelectorAll<HTMLButtonElement>('button') || []);
      if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
    };
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key);
  }, [menuOpen]);

  // Grow the link box with its content (CSS max-height caps it) so long share text is never clipped.
  useLayoutEffect(() => {
    const element = sourceInput.current; if (!element) return;
    element.style.height = 'auto';
    element.style.height = element.scrollHeight + (element.offsetHeight - element.clientHeight) + 'px';
  }, [source, mobile]);
  function clearSource(next = '') {
    ++parseEpoch.current; ++projectNavigation.current; parsingRequest.current?.abort(); parsingRequest.current = null;
    setParsing(false); setSource(next); setSelectedId(null); selectedRef.current = null;
    setConsent(false); setParseError(false); setParseStatus('等待解析'); setArchiveReminder(false); setCoverError(false); setVideoError(false);
    const url = new URL(location.href); url.searchParams.delete('project'); history.replaceState(null, '', url);
    try { localStorage.removeItem('video-parser:last-project'); localStorage.removeItem('video-parser:last-quality'); } catch { /* Optional restore. */ }
  }
  async function parse() {
    if (!source.trim() || parsingRequest.current) return;
    ++projectNavigation.current; const epoch = ++parseEpoch.current;
    const controller = new AbortController(); parsingRequest.current = controller;
    setParsing(true); setParseError(false); setParseStatus('正在解析链接…');
    try {
      const result = await request<ParsedVideo>('/parse', controller.signal, { text: source });
      if (controller.signal.aborted || epoch !== parseEpoch.current) return;
      const id = installProject(result); selectProject(id); setTab('封面图片'); setParseStatus('');
    } catch (reason) {
      if (!controller.signal.aborted && epoch === parseEpoch.current) { setParseError(true); setParseStatus(reason instanceof Error ? reason.message : '解析失败，请检查链接后重试。'); }
    } finally { if (epoch === parseEpoch.current) { parsingRequest.current = null; setParsing(false); } }
  }
  function chooseQuality(key: string) {
    if (!selectedId || busy) return;
    updateProject(selectedId, value => ({ ...value, quality: key, analysis: '', error: false, status: value.parsed.qualities.find(item => item.id === key)?.media ? '已选择归档视频' : '所选画质尚未归档' }));
    setConsent(false); setVideoError(false);
  }
  async function run(operation: Operation) {
    if (!selectedId || !selected || workflowRequests.current.has(selectedId) || !quality) return;
    if (operation === 'prepare' && media) return;
    if (operation === 'analyze' && (!media || !config?.ai_configured || !consent || !validCount)) return;
    const id = selectedId, parsedId = selected.parsed.id, selectedQuality = quality;
    const controller = new AbortController(); workflowRequests.current.set(id, controller);
    // Download progress is drawn in the video stage, so leave the cover when archiving starts there.
    if (operation === 'prepare') setTab(current => current === '封面图片' ? '视频预览' : current);
    updateProject(id, value => ({ ...value, busy: operation, task: undefined, error: false, status: operation === 'prepare' ? '正在下载所选画质并归档…' : '正在提取画面并分析…' }));
    try {
      const result = await runWorkflow<Media | { text: string }>(`/videos/${parsedId}/${operation === 'prepare' ? 'prepare-task' : 'analyze-task'}`,
        operation === 'prepare' ? { quality_id: selectedQuality } : { consent: true, count: Number(count), prompt, quality_id: selectedQuality }, controller.signal,
        job => { if (!controller.signal.aborted) { remember(operation === 'prepare' ? 'video' : 'analysis', job.id); updateProject(id, value => ({ ...value, status: job.message, task: job })); } });
      if (controller.signal.aborted) return;
      applyWorkflowResult(id, result);
      if (selectedRef.current === id) {
        setVideoError(false);
        if (operation === 'prepare') {
          if (settingsRef.current.completionReminder) setArchiveReminder(true);
          try { if ('resource' in result) localStorage.setItem('video-parser:last-quality', result.resource); } catch { /* Optional restore. */ }
        }
      }
    } catch (reason) {
      if (!controller.signal.aborted) updateProject(id, value => ({ ...value, error: true, status: reason instanceof Error ? reason.message : '操作失败，请重试。' }));
    } finally {
      if (workflowRequests.current.get(id) === controller) { workflowRequests.current.delete(id); updateProject(id, value => ({ ...value, busy: null })); }
    }
  }
  async function cancelWorkflow() {
    const id = selectedId, task = selected?.task;
    if (!id || !task || !isActive(task.state) || cancellingTask) return;
    setCancellingTask(task.id);
    try { await cancelTask(task.kind || (selected?.busy === 'analyze' ? 'analysis' : 'video'), task.id); }
    catch (reason) { updateProject(id, value => ({ ...value, error: true, status: reason instanceof Error ? reason.message : '取消请求失败，请重试。' })); }
    finally { setCancellingTask(null); }
  }
  const validCount = Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 16;
  const status = parsing || parseError ? parseStatus : selected?.status || parseStatus;
  // Parse progress/errors are shown once under the link box, not again in the inspector.
  const inspectorStatus = parsing || parseError ? '' : selected?.status || '';
  const showStatus = !!inspectorStatus && (!!selected?.error || busy !== null || !QUIET_STATUS.has(inspectorStatus));
  const cancelDisabled = !selected?.task || !isActive(selected.task.state) || selected.task.state === 'cancelling' || cancellingTask !== null;
  // Cover and video share the full inspector: quality choice and archiving live next to both.
  const fullInspector = tab === '封面图片' || tab === '视频预览';
  const aiPrerequisite = tab === 'AI 分析' && !media;
  const contextNote = aiPrerequisite && parsed ? '分析需要先归档所选视频。' : '';
  // Short side, so a 480x852 portrait stream also counts as limited.
  const maxShortSide = Math.max(0, ...(parsed?.qualities.map(item => item.width && item.height ? Math.min(item.width, item.height) : item.height || 0) || []));
  const qualityLimited = maxShortSide > 0 && maxShortSide < 720;
  const parseNeedsLogin = parseError && parseStatus.includes('账号与登录');
  const platformDuration = typeof parsed?.duration === 'number' && parsed.duration > 0 ? parsed.duration : null;
  function moveTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (next === null) return; event.preventDefault(); setTab(tabs[next].name); tabButtons.current[next]?.focus();
  }

  return <WorkbenchLayout page={page} mobile={mobile} menuOpen={menuOpen} activeCount={activeCount}
    sidebarRef={sidebar} menuButtonRef={menuButton} onNavigate={navigate} onSettings={openSettings}
    onOpenMenu={() => setMenuOpen(true)}
    onCloseMenu={() => { setMenuOpen(false); requestAnimationFrame(() => menuButton.current?.focus()); }}
    overlays={<>
      {settingsOpen && <SettingsDialog settings={settings} onChange={saveSettings} config={config} configError={configError} saveStatus={settingsSaveStatus} activeCount={activeCount} onClose={closeSettings} />}
      {archiveReminder && <div className="archive-reminder" role="status" aria-live="polite">视频已归档<button type="button" aria-label="关闭归档提醒" onClick={() => setArchiveReminder(false)}>×</button></div>}
    </>}>
        {configError && <p className="error-text configuration-error" role="alert">{configError}</p>}
        <WorkbenchPage page="workspace" activePage={page}>
        {page === 'workspace' && config && !config.media_ready && <p className="error-text media-setup-error" role="alert">未检测到 ffmpeg 或 ffprobe，请安装并加入 PATH 后重启服务。</p>}
          <Panel className="source-panel" aria-labelledby="source-label">
          <form onSubmit={event => { event.preventDefault(); void parse(); }}>
          <label id="source-label" htmlFor="source" className="sr-only">视频链接或分享文本</label>
          <div className="source-row">
          <Icon name="link-2" />
          <textarea ref={sourceInput} id="source" value={source} maxLength={8192} rows={1} placeholder="粘贴视频链接，或带链接的分享文本…" onChange={event => setSource(event.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); void parse(); } }} />
          {source && <button className="clear-button" type="button" aria-label="清空链接" onClick={() => { clearSource(); sourceInput.current?.focus(); }}>
          <Icon name="x" />
          </button>}
          <button className="primary parse-button" type="submit" aria-busy={parsing} disabled={!source.trim() || parsing}>{parsing ? <>
          <Icon name="loader-circle" className="spinner" />解析中…</> : <>
          <Icon name="link-2" />解析视频</>}
          </button>
          </div>
          </form>
          </Panel>
          {!source && !parsed && <div className="examples-row">
          <div className="examples">
          <span>试试示例</span>{Object.entries(examples).map(([name, url]) => <button key={name} className="chip" type="button" onClick={() => { setSource(url); sourceInput.current?.focus(); }}>{name}
          </button>)}
          </div>
          </div>}
          {(parsing || parseError) && <p className={parseError ? 'error-text' : 'notice'} role="status">{parseStatus}
          {parseNeedsLogin && <button type="button" className="link-button" onClick={() => openAccounts(parseLoginPlatform(parseStatus, source))}>去登录</button>}
          </p>}
              <div className="tabs" role="tablist" aria-label="内容类型">{tabs.map((item, index) => <button key={item.id} ref={element => { tabButtons.current[index] = element; }} id={'tab-' + item.id} role="tab" aria-selected={tab === item.name} aria-controls={'tabpanel-' + item.id} tabIndex={tab === item.name ? 0 : -1} onClick={() => setTab(item.name)} onKeyDown={event => moveTab(event, index)}>
          <Icon name={item.icon} />{item.name}
          </button>)}
          </div>
          <div className={'work-grid' + (!fullInspector ? ' compact-context' : '')}>
            <section className="preview-panel" aria-labelledby="content-heading">
          <h2 id="content-heading" className="sr-only">项目内容</h2>
              <div id="tabpanel-1" role="tabpanel" aria-labelledby="tab-1" hidden={tab !== '视频预览'}>
          <div className="media-stage" id="video-stage">{media ? <video key={media.preview_url} controls playsInline preload="metadata" poster={coverError ? undefined : parsed?.cover_url || undefined} src={media.preview_url} onError={() => setVideoError(true)} aria-label="视频播放器" /> : <div className={'empty-stage' + (busy === 'prepare' ? ' download-stage' : '')}>
          {busy === 'prepare' ? <div className="download-preview-feedback">
            <div className="download-preview-heading"><Icon name="loader-circle" className="spinner" /><span>视频下载与归档</span></div>
            <p className="download-preview-message" role="status" aria-live="polite" aria-atomic="true">{status}</p>
            {selected?.task?.phase === 'downloading' && selected.task.progress && <ProgressBar progress={selected.task.progress} />}
          </div> : <>
            <Icon name="circle-play" className="film-icon" />
            <p>{parsed ? '选择画质并下载归档后预览' : '先解析链接，再选择画质归档'}</p>
          </>}
          </div>}
          </div>{videoError && <p className="error-text" role="alert">浏览器无法播放，请在归档目录中用本地播放器打开。</p>}
          </div>
              <div id="tabpanel-0" role="tabpanel" aria-labelledby="tab-0" hidden={tab !== '封面图片'}>
          <div className="media-stage cover-stage">{parsed?.cover_url && !coverError ? <img src={parsed.cover_url} alt={`${parsed.title}的封面`} onError={() => setCoverError(true)} /> : <div className="empty-stage">
          <Icon name="image" className="empty-glyph" />
          <p>{parsed ? '暂无可用封面' : '解析后查看封面'}
          </p>
          </div>}
          </div>
          </div>
              <div id="tabpanel-2" role="tabpanel" aria-labelledby="tab-2" hidden={tab !== 'AI 分析'}>
          <Panel className="analysis-form">
          <PanelTitle>抽样画面分析</PanelTitle>
          {!config?.ai_configured && <p className="notice" role="note">{configError || (config ? '请先在本机 .env 配置 QWEN_API_KEY 并重启服务。' : '正在读取 AI 配置…')}
          </p>}
          <div className="analysis-fields">
          <FormField htmlFor="prompt" label={<>分析要求 <span className="optional">（选填）</span></>}>
          <textarea id="prompt" disabled={busy === 'analyze'} value={prompt} maxLength={4000} rows={3} placeholder="例如：描述场景与人物的动作" onChange={event => setPrompt(event.target.value)} />
          </FormField>
          <FormField className="count-field" htmlFor="frame-count" label="抽样帧数">
          <select id="frame-count" disabled={busy === 'analyze'} value={count} onChange={event => setCount(event.target.value)}>{[1, 2, 4, 6, 8, 12, 16].map(value => <option key={value} value={value}>{value} 帧</option>)}
          </select>
          </FormField>
          </div>
          <label className="consent">
          <input type="checkbox" disabled={busy === 'analyze'} checked={consent} onChange={event => setConsent(event.target.checked)} />
          <span>同意发送抽样画面给模型服务（不含音频和字幕，可能产生费用）</span>
          </label>
          <div className="analysis-actions">
          <button className="primary operation-button" type="button" aria-busy={busy === 'analyze'} disabled={!media || !config?.ai_configured || !consent || !validCount || busy !== null} onClick={() => { void run('analyze'); }}>
          <Icon name={busy === 'analyze' ? 'loader-circle' : 'scan-eye'} className={busy === 'analyze' ? 'spinner' : ''} />{busy === 'analyze' ? '分析中…' : '开始分析'}
          </button>
          {busy === 'analyze' && <button type="button" disabled={cancelDisabled} aria-busy={cancellingTask !== null} onClick={() => { void cancelWorkflow(); }}>取消分析</button>}
          </div>
          {(busy === 'analyze' || !!selected?.analysis) && <div className="analysis-result" aria-live="polite" aria-busy={busy === 'analyze'}>
          <label htmlFor="analysis-result">分析结果</label>
          <textarea id="analysis-result" readOnly value={selected?.analysis || ''} rows={9} placeholder={busy === 'analyze' ? '正在提取画面并分析…' : ''} />
          </div>}
          </Panel>
          </div>
            </section>
            <Panel as="aside" className={'details-panel' + (!fullInspector ? ' compact-inspector' : '')} aria-labelledby="details-heading">
          <PanelTitle secondary id="details-heading">{fullInspector ? '项目与归档' : '当前项目'}</PanelTitle>
          <div className="inspector-identity">
          <h3 className="info-title">{parsed?.title || '尚未选择视频'}
          </h3>{parsed && <div className="identity-meta"><span className="platform-mark">{parsed.platform}{!fullInspector && parsed.project.part ? ` · P${parsed.project.part}` : ''}
          </span><a className="source-link" href={parsed.source_url} target="_blank" rel="noreferrer" aria-label="打开原始链接" title="打开原始链接"><Icon name="external-link" /></a></div>}
          </div>
              {contextNote && <p className="context-note">{contextNote}
          </p>}
              {fullInspector && parsed && <>
          <dl className="media-meta">
          <div>
          <dt>视频时长</dt>
          <dd>{media ? formatDuration(media.duration) : platformDuration ? formatDuration(platformDuration) : '—'}
          </dd>
          </div>
          <div>
          <dt>分集</dt>
          <dd>{parsed?.project.part ? 'P' + parsed.project.part : '—'}
          </dd>
          </div>
          <div>
          <dt>分辨率</dt>
          <dd>{media?.width && media.height ? `${media.width} × ${media.height}` : '—'}
          </dd>
          </div>
          <div>
          <dt>实际大小</dt>
          <dd>{media ? (media.size_bytes / 1024 / 1024).toFixed(1) + ' MB' : '—'}
          </dd>
          </div>
          </dl>
          <FormField className="info-field quality-field" labelClassName="field-label" htmlFor="video-quality" label="归档画质">
          <select id="video-quality" disabled={!parsed || !parsed.qualities.length || busy !== null} value={quality} onChange={event => chooseQuality(event.target.value)}>{!parsed?.qualities.length && <option value="">解析后选择画质</option>}
          {parsed?.qualities.map(item => <option key={item.id} value={item.id}>{item.label}
          {item.media && !item.label.includes('已归档') ? ' · 已归档' : ''}
          </option>)}
          </select>
          </FormField>
          </>}
              {(fullInspector || aiPrerequisite) && <>
          {parsed && !media && <button className="primary download-button" type="button" aria-busy={busy === 'prepare'} disabled={!parsed || !quality || busy !== null} onClick={() => { void run('prepare'); }}>
          <Icon name={busy === 'prepare' ? 'loader-circle' : 'download'} className={busy === 'prepare' ? 'spinner' : ''} />{busy === 'prepare' ? '下载归档中…' : fullInspector ? '下载并归档' : '先归档视频'}
          </button>}
          {(busy !== 'prepare' || tab !== '视频预览') && <div className={`status inset ${selected?.error ? 'status-error' : ''}`} role="status" aria-live="polite" aria-atomic="true">{showStatus ? inspectorStatus : ''}</div>}
          {busy === 'prepare' && <button type="button" className="task-entry-link" disabled={cancelDisabled} aria-busy={cancellingTask !== null} onClick={() => { void cancelWorkflow(); }}>取消下载</button>}
          </>}
              {fullInspector && parsed && <>
          <ProjectPanel key={parsed.project.id} project={parsed.project} />
          <button type="button" className="subtitle-entry" onClick={() => { setSubtitleFocus(value => value + 1); navigate('transcription', true); }}><Icon name="captions" />生成字幕</button>
          {qualityLimited && ['missing', 'missing_session', 'expired', 'invalid'].includes(parsed.bilibili_cookie_status || '') && <p className="notice quality-login">{qualityLogin === 'done' ? '已登录 B站，请重新解析链接以获取更高画质。' : <>画质受限：没有登录 B站，最高只有 480p。<button type="button" className="link-button" onClick={() => setQualityLogin('open')}>扫码登录</button><button type="button" className="link-button" onClick={() => openAccounts('bilibili')}>账号与登录</button></>}</p>}
          {qualityLogin === 'open' && <BiliLogin onClose={() => setQualityLogin('closed')} onSuccess={() => setQualityLogin('done')} />}
          </>}
            </Panel>
          </div>
        </WorkbenchPage>
        <WorkbenchPage page="transcription" activePage={page}>
          <div className="transcription-layout">
          <Transcription projectId={parsed?.project.id} media={media} ready={config?.transcription_ready} subtitlesReady={config?.subtitles_ready}
            uploadLimit={config?.transcription_upload_limit} reuseModel={settings.reuseTranscriptionModel} focusRequest={subtitleFocus}
            pending={parsed && parsed.platform === '哔哩哔哩' ? { source_url: parsed.source_url, title: parsed.title, platform: parsed.platform, part: parsed.project.part ?? null, project_id: parsed.project.id } : null} />
          </div>
          </WorkbenchPage>
        <WorkbenchPage page="tasks" activePage={page}>
          <TaskCenter onActivityChange={setActiveCount} />
          </WorkbenchPage>
        <WorkbenchPage page="accounts" activePage={page}>
          <Accounts visible={page === 'accounts'} focusPlatform={accountFocus} />
          </WorkbenchPage>
  </WorkbenchLayout>;
}
