import Panel, { PanelTitle } from '../../components/Panel';
import FormField from '../../components/FormField';
import Icon from '../../components/Icon';
import BiliLogin from './BiliLogin';
import ProjectPanel from '../library/ProjectPanel';
import useSubtitles, { linkPart } from './useSubtitles';
import './subtitle-inventory.css';
import { isActive } from '../../lib/jobs';

export default function Subtitles({ source, ready, projectContext, embedded = false, onFallback }: {
  source: string; ready: boolean | undefined; projectContext?: { title: string; source: string };
  // Embedded inside 字幕与转写: no own panel/heading. onFallback offers local transcription when no platform subtitle was obtained.
  embedded?: boolean; onFallback?: () => void;
}) {
  const { inventory, loginOpen, checkingLogin, scope, setScope, episodes, setEpisodes, job,
    busy, error, cancelling, downloadButton, detached, hasJob, matchesCurrentSource,
    start, retryFailed, cancel, refresh, closeLogin, completeLogin } = useSubtitles(source);
  // Only a locally captured matching source AND matching project title are redundant.
  // Historical/unknown ownership must not be inferred from title equality alone.
  const duplicateTitle = !!(job?.title && matchesCurrentSource
    && projectContext && projectContext.source === source && job.title === projectContext.title);
  const archived = new Set(inventory?.archived || []);
  const ranges = episodes.split(',').map(part => {
    const [first, last = first] = part.split('-').map(Number);
    return { first, last };
  });
  const validCustom = /^\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*$/.test(episodes.trim())
    && ranges.every(({ first, last }) => first >= 1 && last >= first && last <= 1000);
  const requested = scope === 'current' ? [linkPart(source)] : scope === 'all' ? inventory?.episodes.map(item => item.part) || []
    : validCustom ? ranges.flatMap(({ first, last }) => Array.from({ length: last - first + 1 }, (_, index) => first + index)) : [];
  // Nothing left to download: every requested episode already has verified subtitles locally.
  const nothingToDo = requested.length > 0 && requested.every(part => archived.has(part));
  const available = inventory?.available || inventory?.archived || [];
  const total = inventory?.total ?? 0;
  const inventoryRows = inventory?.episodes.length ? inventory.episodes : inventory?.archived.map(part => ({ part, title: '', subtitles: true })) || [];
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
      {/* Nothing to fetch: no disabled "已有字幕" button, just one short hint in the same slot. */}
      {nothingToDo && !busy ? <p className="subtitle-done-hint">所选分集本地都已有字幕</p>
        : <button ref={downloadButton} type="button" className="primary operation-button" aria-busy={busy} disabled={!source.trim() || ready === false || loginOpen || busy || isActive(job?.state) || (scope === 'custom' && !episodes.trim())} onClick={() => { void start(); }}>
        <Icon name={busy ? 'loader-circle' : 'download'} className={busy ? 'spinner' : ''} />{checkingLogin ? '检查登录状态…' : busy ? '下载字幕中…' : '下载字幕'}</button>}
    </div>
    {/* Per-episode inventory only matters for multi-part videos with gaps. */}
    {inventory && available.length > 0 && total > 1 && available.length < total && <details className="subtitle-inventory">
      <summary>{`本地已有字幕 ${available.length} / ${total} 集`}</summary>
      <ul aria-label="各分集的平台字幕归档">{inventoryRows.map(item => <li key={item.part} className={item.subtitles ? 'has-subtitles' : undefined}>
        P{item.part}<span aria-hidden="true">{item.subtitles ? ' ✓' : ''}</span><span>{item.subtitles ? ' 已有字幕' : ' 未归档字幕'}</span></li>)}</ul>
      <p className="subtitle-note">下载时会自动跳过已有校验字幕的分集，不会重复排队。</p>
    </details>}
    <div className={`inset subtitle-status ${error || job?.state === 'failed' || job?.state === 'login_required' ? 'status-error' : ''}`} role="status" aria-live="polite" aria-atomic="true">
      {statusText}
    </div>
    <div className="task-inline-actions">{job && isActive(job.state) && <button type="button" disabled={cancelling || job.state === 'cancelling'} aria-busy={cancelling} onClick={() => { void cancel(); }}>{detached ? '取消另一视频的字幕任务' : '取消字幕任务'}</button>}
      {job && ['partial','failed','cancelled','interrupted'].includes(job.state) && <button type="button" disabled={busy} onClick={() => { void retryFailed(); }}>重试未完成分集</button>}</div>
    {error && hasJob && <button type="button" className="subtitle-refresh" onClick={refresh}>刷新字幕任务状态</button>}
    {job?.title && !duplicateTitle && <p className="subtitle-title">{detached ? '其他视频任务：' : '字幕任务：'}<span translate="no">{job.title}</span></p>}
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
