import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { request } from './lib/api';
import { runWorkflow } from './lib/jobs';
import TaskCenter from './features/tasks/TaskCenter';
import Icon from './components/Icon';
import Subtitles from './features/subtitles/Subtitles';
import Transcription from './features/transcription/Transcription';
import ProjectPanel from './features/library/ProjectPanel';
import SettingsDialog from './features/settings/PreferencesDialog';
import { DEFAULT_SETTINGS, normalizeSettings, preferredQualityId, SETTINGS_KEY } from './features/settings/settings';
import type { Settings } from './features/settings/settings';
import type { IconName } from './components/Icon';
import type { Configuration, Media, ParsedVideo } from './lib/api';

const examples: Record<string, string> = {
  "抖音": "https://www.douyin.com/note/7580598241298069157",
  "哔哩哔哩": "https://www.bilibili.com/video/BV1TaqYBcEJc",
  "小红书": "https://www.xiaohongshu.com/explore/68ab2dd1000000001c0045d0?app_platform=android&ignoreEngage=true&app_version=9.13.1&share_from_user_hidden=true&xsec_source=app_share&type=video&xsec_token=CBLONm9tab3493BJUXCtvU8ScDzfYqa3cGwJstW8eSF3Y=&author_share=1&xhsshare=&shareRedId=OD04RDk1PUw2NzUyOTgwNjc7OThISj5O&apptime=1766754031&share_id=46cc1edc70704cd1ae467afb90d0e8e6&share_channel=wechat&wechatWid=94270060b457f72e6e3a2df13090e1d6&wechatOrigin=menu",
  "快手": "https://www.kuaishou.com/short-video/3x8zha3ipq6bg8q?authorId=3xcyp2v85enrv7w&streamSource=find&area=homexxbrilliant",
  "好看视频": "https://haokan.baidu.com/v?vid=13766973483433940333&tab=recommend"
};
const tabs = ['封面图片', '视频预览', 'AI 分析'] as const;
const tabIcons: IconName[] = ['image', 'circle-play', 'scan-eye'];
type Tab = typeof tabs[number];
type Operation = 'parse' | 'prepare' | 'analyze';

function formatDuration(seconds: number) {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export default function App() {
  const [source, setSource] = useState('');
  const [parsed, setParsed] = useState<ParsedVideo | null>(null);
  const [media, setMedia] = useState<Media | null>(null);
  const [quality, setQuality] = useState('');
  const [tab, setTab] = useState<Tab>('封面图片');
  const [busy, setBusy] = useState<Operation | null>(null);
  const [status, setStatus] = useState('等待解析');
  const [error, setError] = useState(false);
  const [config, setConfig] = useState<Configuration | null>(null);
  const [configError, setConfigError] = useState('');
  const [settings, setSettings] = useState<Settings>(() => { try { return normalizeSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY) || 'null')); } catch { return { ...DEFAULT_SETTINGS }; } });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const [settingsSaveStatus, setSettingsSaveStatus] = useState('偏好保存在此浏览器。');
  const [archiveReminder, setArchiveReminder] = useState(false);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const [prompt, setPrompt] = useState('');
  const [count, setCount] = useState('6');
  const [consent, setConsent] = useState(false);
  const [analysis, setAnalysis] = useState('');
  const [coverError, setCoverError] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const epoch = useRef(0);
  const active = useRef<AbortController | null>(null);
  const tabButtons = useRef<(HTMLButtonElement | null)[]>([]);
  const sourceInput = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    request<Configuration>('/config', controller.signal).then(setConfig).catch((reason: unknown) => {
      if (!controller.signal.aborted) setConfigError(reason instanceof Error ? reason.message : '无法读取服务配置。');
    });
    const initialEpoch = epoch.current;
    let remembered: string | null = null;
    let rememberedQuality = '';
    try { remembered = new URLSearchParams(location.search).get('project') || localStorage.getItem('video-parser:last-project'); rememberedQuality = localStorage.getItem('video-parser:last-quality') || ''; } catch { /* Storage can be unavailable in private contexts. */ }
    if (remembered && /^[a-f0-9]{32}$/.test(remembered)) {
      request<ParsedVideo & { analysis: string }>(`/projects/${remembered}/resume?quality_id=${encodeURIComponent(rememberedQuality)}`, controller.signal).then(result => {
        if (epoch.current !== initialEpoch || controller.signal.aborted) return;
        setParsed(result);
        setSource(result.source_url);
        setMedia(result.media);
        setQuality(result.default_quality_id || '');
        setAnalysis(result.analysis);
        setStatus('已恢复视频项目');
      }).catch(() => { /* A removed project must not prevent starting a new one. */ });
    }
    return () => { controller.abort(); active.current?.abort(); };
  }, []);

  function saveSettings(next: Settings) {
    setSettings(next);
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(next)); setSettingsSaveStatus('设置已保存。'); }
    catch { setSettingsSaveStatus('当前页已生效，关闭或刷新后可能丢失。'); }
  }

  function closeSettings() { setSettingsOpen(false); requestAnimationFrame(() => settingsButton.current?.focus()); }

  function reset(nextSource: string) {
    epoch.current += 1;
    active.current?.abort();
    active.current = null;
    const url = new URL(location.href);
    url.searchParams.delete('project');
    history.replaceState(null, '', url);
    try { localStorage.removeItem('video-parser:last-project'); localStorage.removeItem('video-parser:last-quality'); } catch { /* Optional local restore only. */ }
    setArchiveReminder(false);
    setSource(nextSource);
    setParsed(null);
    setMedia(null);
    setQuality('');
    setAnalysis('');
    setBusy(null);
    setError(false);
    setCoverError(false);
    setVideoError(false);
    setConsent(false);
    setPrompt('');
    setCount('6');
    setTab('封面图片');
    setStatus('等待解析');
  }

  async function run(operation: Operation, task: (signal: AbortSignal, current: () => boolean) => Promise<void>) {
    if (active.current) return;
    const controller = new AbortController();
    const version = epoch.current;
    active.current = controller;
    setBusy(operation);
    setError(false);
    const current = () => version === epoch.current && !controller.signal.aborted;
    try {
      await task(controller.signal, current);
    } catch (reason) {
      if (current()) {
        setError(true);
        setStatus(reason instanceof Error ? reason.message : '操作失败，请重试。');
      }
    } finally {
      if (current()) { active.current = null; setBusy(null); }
    }
  }

  function parse() {
    if (!source.trim() || active.current) return;
    reset(source);
    setStatus('正在解析链接…');
    void run('parse', async (signal, current) => {
      const result = await request<ParsedVideo>('/parse', signal, { text: source });
      if (!current()) return;
      const selectedId = preferredQualityId(result.qualities, result.default_quality_id, settings.qualityPreference);
      const selected = result.qualities.find(item => item.id === selectedId);
      setParsed(result);
      setMedia(selected?.media || null);
      setQuality(selectedId);
      setArchiveReminder(false);
      try { localStorage.setItem('video-parser:last-project', result.project.id); } catch { /* Optional local restore only. */ }
      setStatus(result.warning || (selected?.media ? '已复用归档视频' : '解析完成，请选择清晰度后下载归档'));
    });
  }

  function chooseQuality(key: string) {
    epoch.current += 1;
    active.current?.abort();
    active.current = null;
    setBusy(null);
    const choice = parsed?.qualities.find(item => item.id === key);
    setQuality(key);
    setMedia(choice?.media || null);
    setAnalysis('');
    setVideoError(false);
    setError(false);
    setStatus(choice?.media ? '已选择归档视频' : '所选清晰度尚未下载');
    try { localStorage.setItem('video-parser:last-quality', choice?.media?.resource || ''); } catch { /* Optional restore. */ }
  }

  function prepare() {
    if (!parsed || !quality || active.current) return;
    if (media) { setStatus('所选视频已归档'); return; }
    setStatus('正在下载所选清晰度并归档…');
    void run('prepare', async (signal, current) => {
      const result = await runWorkflow<Media>(`/videos/${parsed.id}/prepare-task`, { quality_id: quality }, signal, job => { if (current()) setStatus(job.message); });
      if (!current()) return;
      setMedia(result);
      setParsed(previous => previous && ({ ...previous, qualities: previous.qualities.map(item =>
        item.id === quality ? { ...item, media: result } : item) }));
      setVideoError(false);
      setStatus('所选视频已归档');
      if (settingsRef.current.completionReminder) setArchiveReminder(true);
      try { localStorage.setItem('video-parser:last-quality', result.resource); } catch { /* Optional restore. */ }
    });
  }

  const validCount = Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 16;
  function analyze() {
    if (!parsed || !media || !config?.ai_configured || !consent || !validCount || active.current) return;
    setAnalysis('');
    setStatus('正在提取画面并分析…');
    void run('analyze', async (signal, current) => {
      const result = await runWorkflow<{ text: string }>(`/videos/${parsed.id}/analyze-task`,
        { consent, count: Number(count), prompt, quality_id: quality }, signal, job => { if (current()) setStatus(job.message); });
      if (!current()) return;
      setAnalysis(result.text);
      setStatus('画面分析完成');
    });
  }

  function moveTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    setTab(tabs[next]);
    tabButtons.current[next]?.focus();
  }

  return <main className="workspace">
    <header className="app-header">
      <span className="brand-mark" aria-hidden="true"><Icon name="clapperboard" /></span>
      <h1>Video Parser</h1><span className="header-divider" aria-hidden="true">/</span><span className="header-label">视频工作台</span>
      <button ref={settingsButton} className="settings-button" type="button" onClick={() => setSettingsOpen(true)}><Icon name="settings" />设置</button>
    </header>
    {settingsOpen && <SettingsDialog settings={settings} onChange={saveSettings} config={config} configError={configError} saveStatus={settingsSaveStatus} onReset={() => saveSettings({ ...DEFAULT_SETTINGS })} onClose={closeSettings} />}
    {archiveReminder && <div className="archive-reminder" role="status" aria-live="polite">视频已归档<button type="button" aria-label="关闭归档提醒" onClick={() => setArchiveReminder(false)}>×</button></div>}

    <section className="panel source-panel" aria-labelledby="source-label">
      <form onSubmit={(event) => { event.preventDefault(); parse(); }}>
        <label id="source-label" htmlFor="source">添加视频链接</label>
        <div className="source-row">
          <textarea ref={sourceInput} id="source" value={source} maxLength={8192} rows={3}
            placeholder="粘贴视频链接，或带链接的分享文本…" onChange={(event) => reset(event.target.value)}
            onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); parse(); } }} />
          <button className="primary parse-button" type="submit" disabled={!source.trim() || busy !== null}>
            {busy === 'parse' ? <><Icon name="loader-circle" className="spinner" />解析中…</> : <><Icon name="link-2" />解析视频</>}
          </button>
        </div>
      </form>
      <div className="examples-row"><div className="examples"><span>示例</span>
        {Object.entries(examples).map(([name, url]) => <button key={name} className="chip" type="button"
          onClick={() => { reset(url); sourceInput.current?.focus(); }}>{name}</button>)}
      </div><button className="clear-button" type="button" onClick={() => { reset(''); sourceInput.current?.focus(); }}><Icon name="eraser" />清空内容</button></div>
    </section>

    <div className="work-grid">
      <section className="panel preview-panel" aria-labelledby="content-heading">
        <h2 id="content-heading">内容工作区</h2>
        <div className="tabs" role="tablist" aria-label="内容类型">
          {tabs.map((name, index) => <button key={name} ref={(element) => { tabButtons.current[index] = element; }}
            id={`tab-${index}`} role="tab" aria-selected={tab === name} aria-controls={`tabpanel-${index}`}
            tabIndex={tab === name ? 0 : -1} onClick={() => setTab(name)} onKeyDown={(event) => moveTab(event, index)}><Icon name={tabIcons[index]} />{name}</button>)}
        </div>
        <div id="tabpanel-0" role="tabpanel" aria-labelledby="tab-0" hidden={tab !== '封面图片'}>
          <div className="media-stage cover-stage">
            {parsed?.cover_url && !coverError ? <img src={parsed.cover_url} alt={`${parsed.title}的封面`} onError={() => setCoverError(true)} /> :
              <div className="empty-stage"><Icon name="image" className="empty-glyph" /><p>{parsed ? '暂无可用封面' : '解析后查看封面'}</p></div>}
          </div>
          <div className="stage-actions">{parsed?.cover_download_url && !coverError && <a className="button" href={parsed.cover_download_url} download><Icon name="image-down" />保存封面</a>}</div>
        </div>
        <div id="tabpanel-1" role="tabpanel" aria-labelledby="tab-1" hidden={tab !== '视频预览'}>
          <div className="media-stage" id="video-stage">
            {media ? <video key={media.preview_url} controls playsInline preload="metadata" poster={coverError ? undefined : parsed?.cover_url || undefined}
              src={media.preview_url} onError={() => setVideoError(true)} aria-label="视频播放器" /> : <div className="empty-stage">
              <Icon name={busy === 'prepare' ? 'loader-circle' : 'circle-play'} className={busy === 'prepare' ? 'film-icon spinner' : 'film-icon'} />
              <p>{busy === 'prepare' ? '正在准备视频，请稍候…' : parsed ? (error ? status : '选择清晰度并下载归档后预览') : '先解析链接，再选择清晰度下载归档'}</p>
            </div>}
          </div>
          {videoError && <p className="error-text" role="alert">浏览器无法播放此编码，可下载后使用本地播放器打开；文件失效时请重新解析。</p>}
        </div>
        <div id="tabpanel-2" role="tabpanel" aria-labelledby="tab-2" hidden={tab !== 'AI 分析'}>
          <div className="analysis-form">
            <p className="notice">仅分析抽样画面，不读取音频或字幕。</p>
            {!config?.ai_configured && <p className="notice" role="note">{configError || (config ? '请先在本机 .env 配置 QWEN_API_KEY 并重启服务。' : '正在读取 AI 配置…')}</p>}
            <div className="analysis-fields"><div className="prompt-field"><label htmlFor="prompt">分析要求 <span className="optional">（选填）</span></label>
              <textarea id="prompt" disabled={busy === 'analyze'} value={prompt} maxLength={4000} rows={3} placeholder="例如：描述场景与人物的动作" onChange={(event) => setPrompt(event.target.value)} /></div>
              <div className="count-field"><label htmlFor="frame-count">抽样帧数</label><select id="frame-count" disabled={busy === 'analyze'} value={count} onChange={(event) => setCount(event.target.value)}>
                {[1, 2, 4, 6, 8, 12, 16].map(value => <option key={value} value={value}>{value} 帧</option>)}</select></div></div>
            <label className="consent"><input type="checkbox" disabled={busy === 'analyze'} checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              <span>同意将抽样画面发送给模型服务，并了解可能产生费用</span></label>
            <div className="analysis-actions"><button className="primary" type="button" disabled={!media || !config?.ai_configured || !consent || !validCount || busy !== null} onClick={analyze}>
              {busy === 'analyze' ? <><Icon name="loader-circle" className="spinner" />分析中…</> : <><Icon name="scan-eye" />开始分析</>}</button></div>
            <div className="analysis-result" aria-live="polite" aria-busy={busy === 'analyze'}><label htmlFor="analysis-result">分析结果</label>
              <textarea id="analysis-result" readOnly value={analysis} rows={9} placeholder={busy === 'analyze' ? '正在提取画面并分析…' : ''} /></div>
          </div>
        </div>
      </section>

      <aside className="panel details-panel" aria-labelledby="details-heading">
        <h2 id="details-heading">视频信息</h2>
        <div className="info-title"><span className="field-label">视频标题</span><p className={parsed ? '' : 'muted'}>{parsed?.title || '—'}</p></div>
        <div className="info-field"><span className="field-label">识别平台</span><div className="inset">{parsed?.platform || '自动识别'}</div></div>
        {media && <dl className="media-meta"><div><dt>时长</dt><dd>{formatDuration(media.duration)}</dd></div>
          <div><dt>大小</dt><dd>{(media.size_bytes / 1024 / 1024).toFixed(1)} MB</dd></div>
          {media.width && media.height && <div><dt>分辨率</dt><dd>{media.width} × {media.height}</dd></div>}</dl>}
        <div className="info-field"><span className="field-label">任务状态</span><div className={`status inset ${error ? 'status-error' : ''}`} role="status" aria-live="polite" aria-atomic="true">
          {busy && <Icon name="loader-circle" className="spinner" />}{status}</div></div>
        {parsed && parsed.qualities.length > 0 && <div className="info-field quality-field"><label className="field-label" htmlFor="video-quality">视频清晰度</label>
          <select id="video-quality" value={quality} onChange={event => chooseQuality(event.target.value)}>
            {parsed.qualities.map(item => <option key={item.id} value={item.id}>{item.label}{item.media && !item.label.includes('已归档') ? ' · 已归档' : ''}</option>)}
          </select>
          {parsed.bilibili_cookie_status === 'reused_unverified' && <p className="notice">已尝试复用字幕工具登录态；画质以本次返回和账号权限为准。</p>}
          {['missing', 'missing_session', 'expired', 'invalid'].includes(parsed.bilibili_cookie_status || '') && <p className="notice">未找到可用的字幕工具登录 Cookie；可在原工具重新登录后再次解析。</p>}
        </div>}
        <button className="primary download-button" type="button" disabled={!parsed || !quality || !!media || busy !== null} onClick={prepare}>
          <Icon name={busy === 'prepare' ? 'loader-circle' : 'download'} className={busy === 'prepare' ? 'spinner' : ''} />{busy === 'prepare' ? '下载归档中…' : media ? '所选视频已归档' : '下载'}</button>
        {parsed && <ProjectPanel project={parsed.project} />}
        {parsed?.source_url && <a className="source-link" href={parsed.source_url} target="_blank" rel="noreferrer">打开原始链接 <Icon name="external-link" /></a>}
      </aside>
    </div>
    <Transcription projectId={parsed?.project.id} media={media} ready={config?.transcription_ready} uploadLimit={config?.transcription_upload_limit} />
    <Subtitles source={source} ready={config?.subtitles_ready} />
    <TaskCenter />
    <details className="workspace-help"><summary>使用提示与运行要求<Icon name="chevron-down" /></summary><div>
      <p>支持{config?.platforms.join('、') || '抖音、哔哩哔哩、小红书、快手等平台'}。平台限制、登录要求或链接过期可能导致解析失败。</p>
      <p>解析只获取信息与封面，不自动下载视频。选择清晰度后点击“下载”，视频保存到项目归档目录。B站会合并音视频，需要 ffmpeg 和 ffprobe。</p>
      <p>切换链接或清空不会删除成果，也不会自动停止任务。请在任务中心点击“取消任务”；刷新后可查看进度与历史结果。</p>
      {config && !config.media_ready && <p className="error-text">未检测到 ffmpeg 或 ffprobe，请安装并加入 PATH 后重启服务。</p>}
      {configError && <p className="error-text" role="alert">{configError}</p>}
    </div></details>
  </main>;
}
