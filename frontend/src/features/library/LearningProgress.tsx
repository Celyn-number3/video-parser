import { useEffect, useState } from 'react';
import type { LearningEpisode, VideoProject } from '../../lib/api';
import './learning.css';

type ToggleProps = {
  episode: LearningEpisode;
  disabled: boolean;
  onChange: (learned: boolean) => void;
  placement?: 'player' | 'list';
};

export function LearningToggle({ episode, disabled, onChange, placement = 'list' }: ToggleProps) {
  const label = placement === 'player'
    ? `当前这一讲 P${episode.part} 已学完`
    : `标记 P${episode.part}「${episode.title}」已学完`;
  return <label className={`learning-toggle${placement === 'player' ? ' learning-player-toggle' : ' learning-episode-toggle'}${disabled ? ' is-disabled' : ''}`}>
    <input type="checkbox" aria-label={label} checked={episode.learned} disabled={disabled}
      onChange={event => onChange(event.currentTarget.checked)} />
    <span>已学完</span>
  </label>;
}

type Props = {
  project: VideoProject;
  episodes: LearningEpisode[];
  disabled: boolean;
  savingPart: number | null;
  error: string;
  onSelectEpisode: (part: number) => void;
  onSetLearned: (part: number, learned: boolean) => void;
};

function durationLabel(seconds: number | null) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return '';
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function initiallyCompact() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(max-width: 1360px)').matches;
}

export default function LearningProgress({ project, episodes, disabled, savingPart, error, onSelectEpisode, onSetLearned }: Props) {
  const [query, setQuery] = useState('');
  useEffect(() => { setQuery(''); }, [project.id]);
  const [compact, setCompact] = useState(initiallyCompact);
  const [expanded, setExpanded] = useState(() => !initiallyCompact());
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(max-width: 1360px)');
    const update = () => setCompact(query.matches);
    update();
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', update);
      return () => query.removeEventListener('change', update);
    }
    query.addListener(update);
    return () => query.removeListener(update);
  }, []);
  useEffect(() => { setExpanded(!compact); }, [compact, project.id]);

  if (episodes.length <= 1) return null;
  const completed = episodes.filter(episode => episode.learned).length;
  const current = episodes.find(episode => episode.part === project.part);
  const next = episodes.find(episode => !episode.learned);
  const term = query.trim().toLocaleLowerCase();
  const partQuery = /^p?\s*(\d+)$/i.exec(term);
  const filtered = episodes.filter(episode => !term || (partQuery ? episode.part === Number(partQuery[1]) : episode.title.toLocaleLowerCase().includes(term)));
  const progress = Math.round(completed / episodes.length * 100);
  const titleId = `learning-progress-title-${project.id}`;
  const rowDisabled = disabled || savingPart !== null;
  const canContinue = current?.learned && next && next.part !== current.part && !rowDisabled;

  function selectEpisode(part: number) {
    if (rowDisabled || part === project.part) return;
    onSelectEpisode(part);
    if (compact) setExpanded(false);
  }

  return <section className="learning-progress" aria-labelledby={titleId}>
    <div className="learning-progress-heading">
      <h3 id={titleId}>分集学习</h3>
      <span className="learning-count">已学完 {completed} / {episodes.length}</span>
    </div>
    <div className="learning-progress-track" role="progressbar" aria-label="学习进度" aria-valuemin={0}
      aria-valuemax={episodes.length} aria-valuenow={completed} aria-valuetext={`${completed} / ${episodes.length} 讲已学完`}>
      <span style={{ width: `${progress}%` }} />
    </div>
    <div className="learning-progress-summary">
      <span>{`当前播放：P${project.part}`} · {next ? next.part === project.part ? '继续本集' : `下一未完成：P${next.part}` : `${episodes.length} 讲全部学完`}</span>
      {canContinue && <button type="button" className="learning-continue" disabled={rowDisabled}
        onClick={() => selectEpisode(next.part)}>继续学 P{next.part}</button>}
    </div>
    {error && <p className="learning-error" role="alert">{error}</p>}
    <button type="button" className="learning-list-toggle" aria-expanded={expanded}
      onClick={() => setExpanded(value => !value)}>{expanded ? '收起分集列表' : '展开分集列表'}</button>
    <div hidden={compact && !expanded}>
    {episodes.length >= 12 && <div className="learning-episode-search">
      <label htmlFor={`episode-search-${project.id}`} className="sr-only">定位分集</label>
      <input id={`episode-search-${project.id}`} type="search" placeholder="P42 或分集标题" value={query}
        onChange={event => setQuery(event.target.value)} onKeyDown={event => {
          if (event.key === 'Escape') { event.preventDefault(); setQuery(''); }
          if (event.key === 'Enter' && !event.nativeEvent.isComposing && filtered.length === 1) { event.preventDefault(); selectEpisode(filtered[0].part); }
        }} />
      {query && <button type="button" onClick={() => setQuery('')}>清除筛选</button>}
      {term && <p role="status">{filtered.length ? `匹配分集：${filtered.length}` : '没有匹配分集。'}</p>}
    </div>}
    <ol className="learning-episode-list" aria-label="分集列表" hidden={compact && !expanded}>
      {filtered.map(episode => {
        const isCurrent = episode.part === project.part;
        const duration = durationLabel(episode.duration);
        return <li className={`learning-episode-row${isCurrent ? ' is-current' : ''}`} key={episode.part}>
          <button type="button" className="learning-episode-open" aria-current={isCurrent ? 'true' : undefined}
            disabled={rowDisabled} onClick={() => selectEpisode(episode.part)}>
            <span className="learning-episode-number">P{episode.part}</span>
            <span className="learning-episode-copy">
              <span className="learning-episode-title" translate="no">{episode.title}</span>
              <span className="learning-episode-meta">{[duration, episode.archived ? '已归档' : '未归档'].filter(Boolean).join(' · ')}</span>
            </span>
          </button>
          <LearningToggle episode={episode} disabled={rowDisabled} onChange={learned => onSetLearned(episode.part, learned)} />
        </li>;
      })}
    </ol>
    </div>
  </section>;
}
