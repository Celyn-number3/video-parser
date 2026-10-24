import { isActive } from '../../lib/jobs';
import { saveFiles } from '../../lib/download';
import Icon from '../../components/Icon';
import Panel from '../../components/Panel';
import TimeProgress from '../../components/TimeProgress';
import { useEffect, useState } from 'react';
import { request } from '../../lib/api';
import type { ArchivedSubtitles, Configuration } from '../../lib/api';
import SubtitleTranslation from './SubtitleTranslation';
import SubtitleViewer from './SubtitleViewer';
import SavedLocation from './SavedLocation';
import useTranscription, { sourceKey, type TranscriptionOptions } from './useTranscription';
import Subtitles from '../subtitles/Subtitles';
import './transcription-layout.css';

const languageNames: Record<string, string> = { zh: '中文', en: '英文', yue: '粤语', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西班牙语', ru: '俄语' };
const languageName = (code: string) => languageNames[code] || code.toUpperCase();
function duration(seconds: number | null) {
  if (!seconds) return '';
  const total = Math.round(seconds), h = Math.floor(total / 3600), m = Math.floor(total % 3600 / 60), s = String(total % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}
const megabytes = (bytes: number) => bytes >= 1024 ** 3 ? (bytes / 1024 ** 3).toFixed(1) + ' GB' : (bytes / 1024 ** 2).toFixed(1) + ' MB';

export default function Transcription({ projectId, media, ready, subtitlesReady, uploadLimit, reuseModel, pending, focusRequest, visible, onSelectSource, config, onOpenSettings }: TranscriptionOptions & { ready?: boolean; subtitlesReady?: boolean; config?: Configuration | null; onOpenSettings?: (button: HTMLButtonElement) => void }) {
  const { destination, setDestination, targetProject, setTargetProject, folder, picking, pickFolder, projects, saveNotice, destinationReady,
    pendingSource, pendingKey, isBilibili, archived, chooseSource, effectiveMethod: method, setMethod,
    mode, setMode, sources, sourcesError, selectedKey, selectedSource, reloadSources, canRetry, requested, retryAs, batchFiles,
    batchNotice, file, job, busy, error, cancelling, limit, running, hasJob,
    selectFiles, start, cancel, refresh } = useTranscription({ projectId, media, uploadLimit, reuseModel, pending, focusRequest, visible, onSelectSource });
  const [filter, setFilter] = useState('');
  const [archiveState, setArchiveState] = useState<{ key: string; data: ArchivedSubtitles; sources: typeof sources } | null>(null);
  const [archiveError, setArchiveError] = useState('');
  // A resource path is scoped to one video. Never send the previous episode's
  // selection while the new episode's default is being resolved.
  const [subtitleSelection, setSubtitleSelection] = useState<{ key: string; resource: string } | null>(null);
  const subtitleResource = subtitleSelection?.key === selectedKey ? subtitleSelection.resource : '';
  const setSubtitleResource = (resource: string) => setSubtitleSelection({ key: selectedKey, resource });
  const archiveKey = mode === 'video' && selectedSource?.has_subtitles ? sourceKey(selectedSource) : '';
  const archive = archiveState?.key === archiveKey ? archiveState.data : null;
  useEffect(() => {
    setArchiveState(current => current?.key === archiveKey ? current : null); setArchiveError('');
    if (!archiveKey || !selectedSource) return;
    // Pinning a version we just loaded must not issue a duplicate read. A real
    // source-list refresh still revalidates it because the snapshot changes.
    if (subtitleResource && archiveState?.key === archiveKey && archiveState.sources === sources
      && archiveState.data.selected?.resource === subtitleResource) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ video_resource: selectedSource.resource });
    if (subtitleResource && !subtitleResource.startsWith('task:')) params.set('subtitle_resource', subtitleResource);
    request<ArchivedSubtitles>(`/projects/${selectedSource.project_id}/subtitles?${params}`, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return;
        if (!subtitleResource) {
          // Prefer verified local transcripts on entry, even when an older API
          // defaults to platform captions. Filenames/language are not provenance.
          const preferred = (data.versions || data.files).find(row => row.origin === 'local'
            || (!row.origin && row.kind === 'transcription')) || data.selected;
          if (preferred) {
            // Pin the first view as well as manual choices: background refreshes
            // and newly completed tasks must not switch what the user is reading.
            setSubtitleResource(preferred.resource);
            if (preferred.resource !== data.selected?.resource) return;
          }
        }
        setArchiveState({ key: archiveKey, data, sources });
      })
      .catch(reason => { if (!controller.signal.aborted) setArchiveError(reason instanceof Error ? reason.message : '无法读取已有字幕，请刷新列表。'); });
    return () => controller.abort();
  }, [archiveKey, subtitleResource, sources]);
  const selectingLocked = busy && !job;
  const [acquireOpen, setAcquireOpen] = useState(false);
  // Re-fetch controls start collapsed for every newly selected video that already has subtitles.
  useEffect(() => { setAcquireOpen(false); }, [selectedKey, mode]);
  const shownSources = (sources || []).filter(item => !filter.trim() || (item.title + ' P' + (item.part ?? '')).toLowerCase().includes(filter.trim().toLowerCase()));
  // The job itself knows whether a language was forced (also for tasks restored after a reload).
  const asked = job?.requested_language && job.requested_language !== 'auto' ? job.requested_language : requested;
  const forced = asked !== 'auto';
  // Only show a finished result under the source it belongs to.
  const jobForSelection = !job || (job.source_project_id
    ? mode === 'video' && !!selectedSource && job.source_project_id === selectedSource.project_id && job.source_resource === selectedSource.resource
    : mode === 'upload');
  // A translation of this video's subtitles (e.g. restored after a reload) belongs in the subtitle card's
  // AI 中英互译 section, not in the transcription result area, and must not force the controls open.
  const videoTranslation = mode === 'video' && job?.operation === 'translation';
  const restoredTranslation = videoTranslation && !!selectedSource && job?.source_project_id === selectedSource.project_id
    && job.source_resource === selectedSource.resource ? job : null;
  const shownJob = jobForSelection && !videoTranslation ? job : null;
  const locked = selectingLocked || (jobForSelection && (busy || running));
  const viewBusy = busy && jobForSelection;
  const transcribing = viewBusy || (!!shownJob && isActive(shownJob.state));
  const shownError = jobForSelection ? error : '';
  const detected = shownJob && !isActive(shownJob.state) && shownJob.language ? shownJob.language : '';
  // Offer the other language after a finished run; for anything else (e.g. 粤语) offer both.
  const retryLanguages = (detected === 'zh' ? ['en'] : detected === 'en' ? ['zh'] : ['zh', 'en']) as ('zh' | 'en')[];
  // Idle placeholder text is omitted; the live region stays mounted but collapses when empty.
  const statusText = shownError || shownJob?.message || (viewBusy ? '正在提交到本机服务…' : '');
  const sourceProject = projects?.find(item => item.id === selectedSource?.project_id);
  const destinationHint = destination === 'source' ? (sourceProject ? `outputs/${sourceProject.location}/subtitles/` : '和视频放在同一个项目文件夹')
    : destination === 'default' ? 'outputs/transcriptions/' : destination === 'project' ? (projects?.find(item => item.id === targetProject)?.location ? `outputs/${projects?.find(item => item.id === targetProject)?.location}/subtitles/` : '') : '';
  const platformMode = method === 'platform';
  // One state, one message: a video with local subtitles shows them first and keeps the
  // acquisition controls folded away until the user asks to re-fetch or fill in episodes.
  const completedResult = mode === 'video' && shownJob?.state === 'completed' && !!shownJob.text ? shownJob : null;
  const hasArchive = mode === 'video' && (selectedSource?.has_subtitles === true || !!completedResult);
  const noSelection = mode === 'video' && !selectedSource;
  const showAcquire = !noSelection && (!hasArchive || acquireOpen || transcribing);
  // Picking a method is a request to acquire subtitles: unfold the controls for it.
  const chooseMethod = (next: 'platform' | 'transcribe') => { setMethod(next); setAcquireOpen(true); };
  const archiveFolder = sourceProject ? `outputs/${sourceProject.location}/subtitles/` : '视频所在项目的 subtitles 文件夹';
  const saveHint = destinationHint;
  const acquireToggle = <button type="button" className="acquire-toggle" aria-expanded={showAcquire} aria-controls="subtitle-acquire" disabled={transcribing} onClick={() => setAcquireOpen(open => !open)}>
    {showAcquire ? '收起获取选项' : platformMode ? '重新下载字幕' : '重新转写'}</button>;
  return <Panel className={'transcription-panel' + (mode === 'video' ? ' is-video' : '')} aria-label="字幕与转写">
    {ready === false && !platformMode && !selectedSource?.has_subtitles && <p className="error-text" role="alert">本机转写组件未安装（需要 NVIDIA 显卡），可以先用平台字幕。</p>}
    {job && isActive(job.state) && !jobForSelection && <p className="notice" role="status">其他视频的转写仍在后台运行，切换不会取消任务。可在任务中心查看。</p>}
    <div className="transcription-head">
      <div className="source-switch" role="group" aria-label="来源">
        <button type="button" aria-pressed={mode === 'upload'} disabled={selectingLocked} onClick={() => setMode('upload')}>上传文件</button>
        <button type="button" aria-pressed={mode === 'video'} disabled={selectingLocked} onClick={() => setMode('video')}>已归档视频{sources?.length ? <span className="switch-count">{sources.length}</span> : null}</button>
      </div>

    </div>
    {/* Stable tree: the detail column (and the embedded Subtitles state) stays mounted across tab switches. */}
    <div className={mode === 'video' ? 'subtitle-split' : 'subtitle-single'}>
    {mode === 'upload' ? <div className="transcription-upload" onDragOver={event => { event.preventDefault(); if (!locked) event.currentTarget.classList.add('drag'); }} onDragLeave={event => event.currentTarget.classList.remove('drag')} onDrop={event => { event.preventDefault();event.currentTarget.classList.remove('drag');if (!locked) selectFiles(Array.from(event.dataTransfer.files)); }}>
      {/* Native file input stays for keyboard/tests but is visually replaced: its button text follows the browser locale. */}
      <input id="transcription-file" className="file-input" type="file" multiple accept="audio/*,video/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac,.wma,.mp4,.mkv,.webm,.mov,.avi,.m4v"
        disabled={locked} onChange={event => { selectFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
      <label htmlFor="transcription-file" className="file-drop">
        <span className="file-drop-icon" aria-hidden="true"><Icon name="audio-lines" /></span>
        <strong>{batchFiles.length ? `已选择 ${batchFiles.length} 个文件` : '选择音视频文件'}</strong>
        <span>{batchFiles.length ? '点击或拖入可重新选择' : `点击选择或拖到这里 · 最多 32 个，每个不超过 ${Math.round(limit / 1024 / 1024)}\u00a0MB`}</span>
      </label>
      <ul className="selected-files">{batchFiles.map((item,index) => <li key={item.name + index}><span>{item.name}<small>{(item.size / 1024 / 1024).toFixed(1)} MB</small></span><button type="button" disabled={locked} onClick={() => selectFiles(batchFiles.filter((_,position) => position !== index))}>移除</button></li>)}</ul>
    </div> : <div className="source-picker">
      {sources === null ? <p className="source-empty">正在读取归档视频…</p>
        : sourcesError ? <div className="source-empty" role="alert"><p title={sourcesError}>读取归档视频列表失败。如果刚更新过程序，请重启本机服务后再试。</p>
          <button type="button" onClick={reloadSources}>重新读取</button></div>
        : !sources.length && !pendingSource ? <p className="source-empty">还没有归档的视频。在视频工作台解析链接并点“下载并归档”后，会出现在这里。</p>
        : <>
          {sources.length > 6 && <input className="source-filter" type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="搜索标题或分集，如 P4" aria-label="搜索归档视频" />}
          <ul className="source-list" role="radiogroup" aria-label="选择视频">
            {pendingSource && <li><label className={'source-option' + (pendingKey === selectedKey ? ' checked' : '')}>
              <input type="radio" name="transcription-video" checked={pendingKey === selectedKey} disabled={selectingLocked} onChange={() => chooseSource(pendingKey)} />
              <span><strong>{pendingSource.title}</strong><small>{[pendingSource.platform, pendingSource.part ? 'P' + pendingSource.part : '', '工作台当前视频 · 未归档，只能下载平台字幕'].filter(Boolean).join(' · ')}</small></span>
            </label></li>}
            {shownSources.map(item => { const key = sourceKey(item); const meta = [item.platform, item.part ? 'P' + item.part : '', item.quality, duration(item.duration_seconds), megabytes(item.size_bytes)].filter(Boolean).join(' · ');
              // Two lines per row; only the exception (no local subtitles) gets a marker.
              return <li key={key}><label className={'source-option' + (key === selectedKey ? ' checked' : '')}>
                <input type="radio" name="transcription-video" checked={key === selectedKey} disabled={selectingLocked} onChange={() => chooseSource(key)} />
                <span><strong translate="no">{item.title}</strong><small>{meta}</small></span>
                {item.has_subtitles === false && <span className="subtitle-missing">无字幕</span>}
              </label></li>; })}
            {!shownSources.length && !pendingSource && <li className="source-empty">没有匹配的视频。</li>}
          </ul>
        </>}
    </div>}
    <div className="transcription-detail">
    {noSelection && !!sources?.length && <p className="detail-empty">从列表中选择一个视频。</p>}
    {mode === 'video' && selectedSource && typeof selectedSource.has_subtitles === 'boolean' && <section className={'archived-subtitles' + (hasArchive ? '' : ' is-missing')} aria-label="当前视频字幕" aria-busy={hasArchive && !archive && !completedResult && !archiveError}>
      {hasArchive ? <>
        <div className="archive-status"><span className="subtitle-badge">✓ 已有字幕</span></div>
        {archiveError && <p className="error-text" role="alert">{archiveError}</p>}
        <SubtitleViewer key={selectedKey} archive={archive} job={completedResult} restored={restoredTranslation} resource={subtitleResource}
          projectId={selectedSource.project_id} video={selectedSource.resource} onSelect={setSubtitleResource} config={config} onOpenSettings={onOpenSettings} />
        {/* Subtitles already live in the project folder: show where (and open it) instead of another download. */}
        {archive?.has_subtitles ? <SavedLocation label="字幕已保存到" location={archiveFolder} openPath={`/projects/${selectedSource.project_id}/open`} body={{ folder: 'subtitles' }}>{acquireToggle}</SavedLocation>
          : <div className="saved-location-row"><span className="saved-location-actions">{acquireToggle}</span></div>}
      </> : <p className="subtitle-note">尚无本地字幕，可下载平台字幕或进行本地转写。</p>}
    </section>}
    <div id="subtitle-acquire" className="acquire-section" hidden={!showAcquire}>
          {mode === 'video' && <div className="method-picker" role="group" aria-label="获取方式">
        <span className="option-label">获取方式</span>
        <div className="source-switch method-switch">
          <button type="button" aria-pressed={!!selectedSource && platformMode} disabled={locked || !isBilibili} title={isBilibili ? '直接下载 B站的字幕，快且准；需要登录，部分视频没有字幕' : selectedSource ? '该视频不是带链接的 B站视频，无法下载平台字幕' : '先选择一个视频'} onClick={() => chooseMethod('platform')}>B站平台字幕</button>
          <button type="button" aria-pressed={!!selectedSource && !platformMode} disabled={locked || !archived} title={archived ? '用本机显卡识别语音，音频不上传' : selectedSource ? '本地转写需要先在视频工作台归档视频' : '先选择一个视频'} onClick={() => chooseMethod('transcribe')}>本地转写</button>
        </div>
      </div>}
    {mode === 'video' && <h3 className="acquire-title">{platformMode ? '下载平台字幕' : '本地转写'}</h3>}
    {!platformMode && <div className="option-row save-target">
      <label className="option-label" htmlFor="save-destination">保存到</label>
      <div className="save-controls">
        <select id="save-destination" value={destination} disabled={locked} onChange={event => setDestination(event.target.value as typeof destination)}>
          {mode === 'video' ? <option value="source">视频所在项目</option> : <option value="default">默认输出目录</option>}
          <option value="project">其他项目</option>
          <option value="folder">自选文件夹</option>
        </select>
        {destination === 'project' && <select aria-label="选择项目" value={targetProject} disabled={locked} onChange={event => setTargetProject(event.target.value)}>
          <option value="">{projects === null ? '正在读取项目…' : projects.length ? '选择一个项目' : '资料库里还没有项目'}</option>
          {(projects || []).map(item => <option key={item.id} value={item.id}>{[item.platform, item.title, item.part ? 'P' + item.part : ''].filter(Boolean).join(' · ')}</option>)}
        </select>}
        {destination === 'folder' && <><code className="folder-path" title={folder}>{folder || '还没有选择文件夹'}</code>
          <button type="button" disabled={locked || picking} aria-busy={picking} onClick={() => { void pickFolder(); }}>{picking ? '等待选择…' : folder ? '更换' : '选择文件夹'}</button></>}
      </div>
      {/* Primary action at the right end of the control row, the same slot as 下载字幕 in platform mode. */}
      <div className="row-action"><button className="primary operation-button" type="button" aria-busy={viewBusy} disabled={ready === false || locked || !destinationReady || (mode === 'upload' ? !file : !archived)} onClick={() => { void start(); }}>
        <Icon name={viewBusy ? 'loader-circle' : 'file-play'} className={viewBusy ? 'spinner' : ''} />{viewBusy ? (shownJob ? '转录中…' : '提交文件中…') : shownJob?.state === 'failed' ? '重试转写' : '开始转写'}</button></div>
      {saveHint && <small className="option-hint" title={saveHint}>{saveHint}</small>}
    </div>}
    {saveNotice && <p className="notice" role="status">{saveNotice}</p>}
    <div hidden={!platformMode}>
      <Subtitles embedded source={mode === 'video' && selectedSource?.source_url ? selectedSource.source_url : ''} ready={subtitlesReady}
        onFallback={archived ? () => setMethod('transcribe') : undefined} />
    </div>
    {/* Progress and result of a transcription belong to the section that started it. */}
    {!platformMode && <>
    {batchNotice && <p className="notice" role="status">{batchNotice}</p>}
    <div className={'inset subtitle-status ' + (shownError || shownJob?.state === 'failed' ? 'status-error' : '')} role="status" aria-live="polite">
      {statusText}
    </div>
    {/* Outside the live region: the bar updates every second and must not be read out each time. */}
    {shownJob && (shownJob.state === 'queued' || shownJob.state === 'running') &&
      <TimeProgress progress={shownJob.phase === 'transcribing' ? shownJob.progress : undefined} label="转写进度" />}
    {shownJob && isActive(shownJob.state) && <div className="task-inline-actions"><button type="button" disabled={cancelling || shownJob.state === 'cancelling'} aria-busy={cancelling} onClick={() => { void cancel(); }}>取消转录任务</button></div>}
    {shownError && hasJob && <button type="button" className="subtitle-refresh" disabled={busy} onClick={refresh}>重新读取转录状态</button>}
    {shownJob && mode === 'upload' && <p className="subtitle-title">本次任务：<span translate="no">{shownJob.title}</span></p>}
    {job && !shownJob && !videoTranslation && !isActive(job.state) && <p className="subtitle-title">上次任务「<span translate="no">{job.title}</span>」的结果不属于当前选择，可在任务中心查看。</p>}
    {detected && shownJob?.operation !== 'translation' && <p className="detected-language">{forced ? `已按${languageName(asked)}转写` : `识别为：${languageName(detected)}`}
      {canRetry && !locked && <span className="retry-languages">{forced ? '' : '识别错了？'}{retryLanguages.map(code =>
        <button key={code} type="button" className="link-button" onClick={() => retryAs(code)}>{`按${languageName(code)}重新转写`}</button>)}</span>}
    </p>}
    {shownJob?.text && !completedResult && <div className="analysis-result transcription-result">
      {shownJob.state === 'completed' ? <SubtitleTranslation key={shownJob.id} source={{ job_id: shownJob.id }} text={shownJob.text}
        language={shownJob.language} config={config} onOpenSettings={onOpenSettings}
        label={shownJob.operation === 'translation' ? '译文' : '识别文字'} textId="transcription-text" />
        : <><label htmlFor="transcription-text">{shownJob.operation === 'translation' ? '译文' : '识别文字'}</label><textarea id="transcription-text" readOnly rows={8} value={shownJob.text} /></>}
    </div>}
    {/* Results are written to disk already; download buttons remain only for records without a saved location. */}
    {!completedResult && shownJob?.files.length && !shownJob.saved_to?.location ? <div className="transcription-downloads">{shownJob.files.map(output =>
      <button type="button" key={output.format} onClick={() => saveFiles([output.url])}><Icon name="download" />{shownJob.operation === 'translation' ? '下载译文 ' : '下载 '}{output.format.toUpperCase()}</button>)}
    </div> : null}
    {!completedResult && shownJob?.saved_to?.location && shownJob.files.length ? <SavedLocation label="转写结果已保存到" location={shownJob.saved_to.location} openPath={`/transcriptions/${shownJob.id}/open`} /> : null}
    </>}
    </div>
    </div>
    </div>
  </Panel>;
}
