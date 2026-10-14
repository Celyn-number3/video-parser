import Panel, { PanelTitle } from '../../components/Panel';
import FormField from '../../components/FormField';
import Icon from '../../components/Icon';
import BiliLogin from './BiliLogin';
import ProjectPanel from '../library/ProjectPanel';
import useSubtitles from './useSubtitles';
import { isActive } from '../../lib/jobs';

export default function Subtitles({ source, ready, projectContext, embedded = false, onFallback }: {
  source: string; ready: boolean | undefined; projectContext?: { title: string; source: string };
  // Embedded inside 字幕与转写: no own panel/heading. onFallback offers local transcription when no platform subtitle was obtained.
  embedded?: boolean; onFallback?: () => void;
}) {
  const { loginOpen, checkingLogin, scope, setScope, episodes, setEpisodes, job,
    busy, error, cancelling, downloadButton, detached, hasJob, matchesCurrentSource,
    start, retryFailed, cancel, refresh, closeLogin, completeLogin } = useSubtitles(source);
  // Only a locally captured matching source AND matching project title are redundant.
  // Historical/unknown ownership must not be inferred from title equality alone.
  const duplicateTitle = !!(job?.title && matchesCurrentSource
    && projectContext && projectContext.source === source && job.title === projectContext.title);
  // The live region stays mounted (so updates are announced) but collapses when idle.
  const statusText = detached ? '另一视频的字幕任务与成果保留在任务中心，不会应用到当前项目。' : error || (checkingLogin ? '正在检查 B站登录状态…' : loginOpen ? '等待扫码登录，尚未开始下载字幕。' : '') || job?.message || (busy ? '正在启动本机字幕工具…' : '');
  return <Panel as={embedded ? 'div' : 'section'} className={'subtitle-panel' + (embedded ? ' subtitle-embedded' : '')} aria-labelledby={embedded ? undefined : 'subtitle-heading'}>
    {!embedded && <PanelTitle id="subtitle-heading">B站分集字幕</PanelTitle>}
    {ready === false && <p className="error-text">未找到本机 B站字幕工具或校验脚本，请检查安装路径。</p>}
    <div className="subtitle-controls">
      <FormField htmlFor="subtitle-scope" label="下载范围"><select id="subtitle-scope" value={scope} disabled={busy} onChange={event => setScope(event.target.value as typeof scope)}>
        <option value="current">当前分集</option><option value="all">全部分集</option><option value="custom">指定分集</option>
      </select></FormField>
      {scope === 'custom' && <FormField className="subtitle-episodes" htmlFor="subtitle-episodes" label="指定集数">
        <input id="subtitle-episodes" type="text" maxLength={500} value={episodes} placeholder="例如 1-5,8" disabled={busy} onChange={event => setEpisodes(event.target.value)} /></FormField>}
      <button ref={downloadButton} type="button" className="primary operation-button" aria-busy={busy} disabled={!source.trim() || ready === false || loginOpen || busy || isActive(job?.state) || (scope === 'custom' && !episodes.trim())} onClick={() => { void start(); }}>
        <Icon name={busy ? 'loader-circle' : 'download'} className={busy ? 'spinner' : ''} />{checkingLogin ? '检查登录状态…' : busy ? '下载字幕中…' : '下载字幕'}</button>
    </div>
    <div className={`inset subtitle-status ${error || job?.state === 'failed' || job?.state === 'login_required' ? 'status-error' : ''}`} role="status" aria-live="polite" aria-atomic="true">
      {statusText}
    </div>
    <div className="task-inline-actions">{job && isActive(job.state) && <button type="button" disabled={cancelling || job.state === 'cancelling'} aria-busy={cancelling} onClick={() => { void cancel(); }}>{detached ? '取消另一视频的字幕任务' : '取消字幕任务'}</button>}
      {job && ['partial','failed','cancelled','interrupted'].includes(job.state) && <button type="button" disabled={busy} onClick={() => { void retryFailed(); }}>重试未完成分集</button>}</div>
    {error && hasJob && <button type="button" className="subtitle-refresh" onClick={refresh}>刷新字幕任务状态</button>}
    {job?.title && !duplicateTitle && <p className="subtitle-title">{detached ? '其他视频任务：' : '字幕任务：'}{job.title}</p>}
    {!detached && job?.results.length ? <ul className="subtitle-results">{job.results.map(item => <li key={item.episode}>
      <div className="subtitle-result-label"><strong>P{item.episode}</strong><span className={item.status === 'failed' ? 'error-text' : ''}>{item.message}</span></div>
      {item.project && <ProjectPanel project={item.project} />}
    </li>)}</ul> : null}
    {onFallback && !detached && job && ['partial', 'failed'].includes(job.state) && <p className="subtitle-fallback">没拿到平台字幕的分集，可以
      <button type="button" className="link-button" onClick={onFallback}>改用本地转写</button></p>}
    {job?.state === 'login_required' && <p className="subtitle-note">请点击下载字幕，在工作台弹出的二维码中完成登录后重试。</p>}
    {loginOpen && <BiliLogin onClose={closeLogin} onSuccess={completeLogin} />}
  </Panel>;
}
