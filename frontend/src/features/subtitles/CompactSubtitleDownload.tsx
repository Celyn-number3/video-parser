import { useState } from 'react';
import { isActive } from '../../lib/jobs';
import BiliLogin from './BiliLogin';
import useSubtitles, { linkPart } from './useSubtitles';

/** An explicit, source-keyed confirmation. Restored history stays in Task Center. */
export default function CompactSubtitleDownload({ source, ready, currentArchived, onClose }: {
  source: string; ready?: boolean; currentArchived: boolean; onClose?: () => void;
}) {
  const { inventory, scope, setScope, episodes, setEpisodes, job, busy, error, downloadButton,
    checkingLogin, loginOpen, matchesCurrentSource, start, closeLogin, completeLogin } = useSubtitles(source);
  const [batch, setBatch] = useState(false);
  const ranges = episodes.split(',').map(value => { const [first, last = first] = value.trim().split('-').map(Number); return { first, last }; });
  const valid = /^\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*$/.test(episodes.trim())
    && ranges.every(({ first, last }) => first >= 1 && last >= first && last <= 1000);
  const archived = new Set(inventory?.archived || []);
  if (currentArchived) archived.add(linkPart(source));
  const requested = scope === 'current' ? [linkPart(source)] : scope === 'all' ? inventory?.episodes.map(row => row.part) || []
    : valid ? ranges.flatMap(({ first, last }) => Array.from({ length: last - first + 1 }, (_, i) => first + i)) : [];
  const nothing = requested.length > 0 && requested.every(part => archived.has(part));
  const locked = busy || loginOpen || isActive(job?.state);
  const status = matchesCurrentSource ? error || (checkingLogin ? '正在检查登录状态…' : loginOpen ? '请完成登录，确认的下载尚未开始。'
    : job?.state === 'completed' ? '本次字幕获取已完成。' : job && !isActive(job.state) ? '本次字幕任务未全部完成，请到任务中心查看原因。'
    : busy ? '字幕任务正在处理，可到任务中心查看进度。' : '')
    : job && isActive(job.state) ? '已有字幕任务正在处理，可到任务中心查看。' : '';
  return <div className="compact-acquire" role="group" aria-label="平台字幕获取确认">
    <p className="subtitle-note">{scope === 'current' ? `获取当前分集 P${linkPart(source)} 的平台字幕。` : '按所选范围获取平台字幕。'} 已有校验通过的字幕会自动跳过，不会覆盖。</p>
    <button type="button" className="compact-range-toggle" aria-expanded={batch} disabled={locked}
      onClick={() => { setBatch(value => !value); setScope('current'); setEpisodes(''); }}>{batch ? '收起批量范围' : '选择批量范围（可选）'}</button>
    {batch && <div className="compact-acquire-fields">
      <label>下载范围<select aria-label="下载范围" value={scope} disabled={locked} onChange={event => setScope(event.target.value as typeof scope)}>
        <option value="current">当前分集</option><option value="all">全部分集</option><option value="custom">指定分集</option>
      </select></label>
      {scope === 'custom' && <label>指定集数<input aria-label="指定集数" value={episodes} maxLength={500} placeholder="例如 1-3,8" disabled={locked} onChange={event => setEpisodes(event.target.value)} /></label>}
    </div>}
    {scope === 'custom' && !valid && <p className="subtitle-note">请输入有效集数范围，例如 1-3,8。</p>}
    {nothing && <p className="subtitle-note">所选分集已有可用平台字幕，无需重复下载；可选择批量范围补全缺失分集。</p>}
    {ready === false && <p className="error-text" role="alert">本机平台字幕工具尚未就绪，请检查设置。</p>}
    <div className="compact-acquire-actions">
      <button ref={downloadButton} type="button" className="primary" disabled={locked || nothing || !source.trim() || ready === false || scope === 'custom' && !valid} onClick={() => { void start(); }}>确认下载</button>
      {onClose && <button type="button" onClick={onClose}>{matchesCurrentSource ? '关闭' : '取消'}</button>}
      <a href="?page=tasks">查看任务中心</a>
    </div>
    {status && <p className={matchesCurrentSource && error ? 'error-text' : 'subtitle-note'} role={matchesCurrentSource && error ? 'alert' : 'status'}>{status}</p>}
    {loginOpen && <BiliLogin onClose={closeLogin} onSuccess={completeLogin} />}
  </div>;
}
