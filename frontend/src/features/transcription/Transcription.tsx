import { isActive } from '../../lib/jobs';
import { saveFiles } from '../../lib/download';
import Icon from '../../components/Icon';
import Panel from '../../components/Panel';
import { useState } from 'react';
import useTranscription, { sourceKey, type TranscriptionOptions } from './useTranscription';
import Subtitles from '../subtitles/Subtitles';

const languageNames: Record<string, string> = { zh: '中文', en: '英文', yue: '粤语', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西班牙语', ru: '俄语' };
const languageName = (code: string) => languageNames[code] || code.toUpperCase();
function duration(seconds: number | null) {
  if (!seconds) return '';
  const total = Math.round(seconds), h = Math.floor(total / 3600), m = Math.floor(total % 3600 / 60), s = String(total % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}
const megabytes = (bytes: number) => bytes >= 1024 ** 3 ? (bytes / 1024 ** 3).toFixed(1) + ' GB' : (bytes / 1024 ** 2).toFixed(1) + ' MB';

export default function Transcription({ projectId, media, ready, subtitlesReady, uploadLimit, reuseModel, pending, focusRequest }: TranscriptionOptions & { ready?: boolean; subtitlesReady?: boolean }) {
  const { destination, setDestination, targetProject, setTargetProject, folder, picking, pickFolder, projects, saveNotice, destinationReady, openSaved,
    pendingSource, pendingKey, isBilibili, archived, chooseSource, effectiveMethod: method, setMethod,
    mode, setMode, sources, sourcesError, selectedKey, selectedSource, reloadSources, canRetry, requested, retryAs, batchFiles,
    batchNotice, file, job, busy, error, cancelling, limit, running, hasJob,
    selectFiles, start, cancel, refresh } = useTranscription({ projectId, media, uploadLimit, reuseModel, pending, focusRequest });
  const [filter, setFilter] = useState('');
  const locked = busy || running;
  const shownSources = (sources || []).filter(item => !filter.trim() || (item.title + ' P' + (item.part ?? '')).toLowerCase().includes(filter.trim().toLowerCase()));
  // The job itself knows whether a language was forced (also for tasks restored after a reload).
  const asked = job?.requested_language && job.requested_language !== 'auto' ? job.requested_language : requested;
  const forced = asked !== 'auto';
  // Only show a finished result under the source it belongs to.
  const jobForSelection = !job || isActive(job.state) || (job.source_project_id
    ? mode === 'video' && !!selectedSource && job.source_project_id === selectedSource.project_id && job.source_resource === selectedSource.resource
    : mode === 'upload');
  const shownJob = jobForSelection ? job : null;
  const detected = shownJob && !isActive(shownJob.state) && shownJob.language ? shownJob.language : '';
  // Offer the other language after a finished run; for anything else (e.g. 粤语) offer both.
  const retryLanguages = (detected === 'zh' ? ['en'] : detected === 'en' ? ['zh'] : ['zh', 'en']) as ('zh' | 'en')[];
  // Idle placeholder text is omitted; the live region stays mounted but collapses when empty.
  const statusText = error || shownJob?.message || (busy ? '正在提交到本机服务…' : '');
  const sourceProject = projects?.find(item => item.id === selectedSource?.project_id);
  const destinationHint = destination === 'source' ? (sourceProject ? `library/${sourceProject.location}/subtitles/` : '和视频放在同一个项目文件夹')
    : destination === 'default' ? 'outputs/transcriptions/' : destination === 'project' ? (projects?.find(item => item.id === targetProject)?.location ? `library/${projects?.find(item => item.id === targetProject)?.location}/subtitles/` : '') : '';
  const platformMode = method === 'platform';
  return <Panel className="transcription-panel" aria-label="字幕与转写">
    {ready === false && !platformMode && <p className="error-text" role="alert">未找到项目内 Whisper 环境或模型，请运行 scripts/setup-local-tools.ps1 -DownloadModel 后重启后端。</p>}
    <div className="transcription-head">
      <div className="source-switch" role="group" aria-label="来源">
        <button type="button" aria-pressed={mode === 'upload'} disabled={locked} onClick={() => setMode('upload')}>上传文件</button>
        <button type="button" aria-pressed={mode === 'video'} disabled={locked} onClick={() => setMode('video')}>已归档视频{sources?.length ? <span className="switch-count">{sources.length}</span> : null}</button>
      </div>
      {!platformMode && <button className="primary operation-button" type="button" aria-busy={busy} disabled={ready === false || locked || !destinationReady || (mode === 'upload' ? !file : !archived)} onClick={() => { void start(); }}>
        <Icon name={busy ? 'loader-circle' : 'file-play'} className={busy ? 'spinner' : ''} />{busy ? (shownJob ? '转录中…' : '提交文件中…') : shownJob?.state === 'failed' ? '重试转写' : '开始转写'}</button>}
    </div>
    {mode === 'upload' ? <div className="transcription-upload" onDragOver={event => { event.preventDefault(); if (!busy && !running) event.currentTarget.classList.add('drag'); }} onDragLeave={event => event.currentTarget.classList.remove('drag')} onDrop={event => { event.preventDefault();event.currentTarget.classList.remove('drag');if (!busy && !running) selectFiles(Array.from(event.dataTransfer.files)); }}>
      {/* Native file input stays for keyboard/tests but is visually replaced: its button text follows the browser locale. */}
      <input id="transcription-file" className="file-input" type="file" multiple accept="audio/*,video/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac,.wma,.mp4,.mkv,.webm,.mov,.avi,.m4v"
        disabled={busy || running} onChange={event => { selectFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
      <label htmlFor="transcription-file" className="file-drop">
        <span className="file-drop-icon" aria-hidden="true"><Icon name="audio-lines" /></span>
        <strong>{batchFiles.length ? `已选择 ${batchFiles.length} 个文件` : '选择音视频文件'}</strong>
        <span>{batchFiles.length ? '点击或拖入可重新选择' : `点击选择或拖到这里 · 最多 32 个，每个不超过 ${Math.round(limit / 1024 / 1024)}\u00a0MB`}</span>
      </label>
      <ul className="selected-files">{batchFiles.map((item,index) => <li key={item.name + index}><span>{item.name}<small>{(item.size / 1024 / 1024).toFixed(1)} MB</small></span><button type="button" disabled={busy || running} onClick={() => selectFiles(batchFiles.filter((_,position) => position !== index))}>移除</button></li>)}</ul>
    </div> : <div className="source-picker">
      {sources === null ? <p className="source-empty">正在读取归档视频…</p>
        : sourcesError ? <div className="source-empty" role="alert"><p title={sourcesError}>读取归档视频列表失败。如果刚更新过程序，请重启本机服务后再试。</p>
          <button type="button" onClick={reloadSources}>重新读取</button></div>
        : !sources.length && !pendingSource ? <p className="source-empty">还没有归档的视频。在视频工作台解析链接并点“下载并归档”后，会出现在这里。</p>
        : <>
          {sources.length > 6 && <input className="source-filter" type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="搜索标题或分集，如 P4" aria-label="搜索归档视频" />}
          <ul className="source-list" role="radiogroup" aria-label="选择视频">
            {pendingSource && <li><label className={'source-option' + (pendingKey === selectedKey ? ' checked' : '')}>
              <input type="radio" name="transcription-video" checked={pendingKey === selectedKey} disabled={locked} onChange={() => chooseSource(pendingKey)} />
              <span><strong>{pendingSource.title}</strong><small>{[pendingSource.platform, pendingSource.part ? 'P' + pendingSource.part : '', '工作台当前视频 · 未归档，只能下载平台字幕'].filter(Boolean).join(' · ')}</small></span>
            </label></li>}
            {shownSources.map(item => { const key = sourceKey(item); const meta = [item.platform, item.part ? 'P' + item.part : '', item.quality, duration(item.duration_seconds), megabytes(item.size_bytes)].filter(Boolean).join(' · ');
              return <li key={key}><label className={'source-option' + (key === selectedKey ? ' checked' : '')}>
                <input type="radio" name="transcription-video" checked={key === selectedKey} disabled={locked} onChange={() => chooseSource(key)} />
                <span><strong>{item.title}</strong><small>{meta}</small></span>
              </label></li>; })}
            {!shownSources.length && !pendingSource && <li className="source-empty">没有匹配的视频。</li>}
          </ul>
        </>}
    </div>}
    {isBilibili && <div className="option-row" role="group" aria-label="字幕来源">
      <span className="option-label">字幕来源</span>
      <div className="source-switch method-switch">
        <button type="button" aria-pressed={platformMode} disabled={locked} onClick={() => setMethod('platform')}>B站平台字幕</button>
        <button type="button" aria-pressed={!platformMode} disabled={locked || !archived} title={archived ? '' : '本地转写需要先在视频工作台归档视频'} onClick={() => setMethod('transcribe')}>本地转写</button>
      </div>
      <small className="option-hint">{platformMode ? '直接下载 B站的字幕，快且准；需要登录，部分视频没有字幕。' : '用本机显卡识别语音，音频不上传。'}</small>
    </div>}
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
      {destinationHint && <small className="option-hint">{destinationHint}</small>}
    </div>}
    {!platformMode && !isBilibili && <p className="notice">本地转写，音频不会发送到云端。</p>}
    {saveNotice && <p className="notice" role="status">{saveNotice}</p>}
    <div hidden={!platformMode}>
      <Subtitles embedded source={mode === 'video' && selectedSource?.source_url ? selectedSource.source_url : ''} ready={subtitlesReady}
        onFallback={archived ? () => setMethod('transcribe') : undefined} />
    </div>
    {!platformMode && <>
    {batchNotice && <p className="notice" role="status">{batchNotice}</p>}
    <div className={'inset subtitle-status ' + (error || shownJob?.state === 'failed' ? 'status-error' : '')} role="status" aria-live="polite">
      {statusText}
    </div>
    {job && isActive(job.state) && <div className="task-inline-actions"><button type="button" disabled={cancelling || job.state === 'cancelling'} aria-busy={cancelling} onClick={() => { void cancel(); }}>取消转录任务</button></div>}
    {error && hasJob && <button type="button" className="subtitle-refresh" disabled={busy} onClick={refresh}>重新读取转录状态</button>}
    {shownJob && <p className="subtitle-title">本次任务：{shownJob.title}</p>}
    {job && !shownJob && <p className="subtitle-title">上次任务「{job.title}」的结果不属于当前选择，可在任务中心查看。</p>}
    {detected && <p className="detected-language">{forced ? `已按${languageName(asked)}转写` : `识别为：${languageName(detected)}`}
      {canRetry && !locked && <span className="retry-languages">{forced ? '' : '识别错了？'}{retryLanguages.map(code =>
        <button key={code} type="button" className="link-button" onClick={() => retryAs(code)}>按{languageName(code)}重新转写</button>)}</span>}
    </p>}
    {shownJob?.text && <div className="analysis-result transcription-result">
      <label htmlFor="transcription-text">识别文字</label><textarea id="transcription-text" readOnly rows={8} value={shownJob.text} />
    </div>}
    {shownJob?.files.length ? <div className="transcription-downloads">{shownJob.files.map(output =>
      <button type="button" key={output.format} onClick={() => saveFiles([output.url])}><Icon name="download" />下载 {output.format.toUpperCase()}</button>)}
    </div> : null}
    {shownJob?.saved_to && shownJob.files.length ? <p className="saved-to">已保存到 <code title={shownJob.saved_to.location}>{shownJob.saved_to.location}</code>
      <button type="button" className="link-button" onClick={() => { void openSaved(); }}>打开文件夹</button></p> : null}
    {shownJob?.files.some(file => file.format.toLowerCase() === 'srt') && <p className="subtitle-note">识别结果建议人工校对。</p>}
    </>}
  </Panel>;
}
