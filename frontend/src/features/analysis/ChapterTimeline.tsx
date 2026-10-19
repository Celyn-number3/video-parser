import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { chapterTime } from './chapters';
import type { AnalysisTimeline } from './chapters';
import './chapter-timeline.css';

type Props = { timeline: AnalysisTimeline; videoRef: RefObject<HTMLVideoElement | null>; mediaKey: string;
  duration: number; enabled: boolean; view: 'player' | 'directory'; compact?: boolean; visible?: boolean; onSeek: (seconds: number) => void };

export default function ChapterTimeline({ timeline, videoRef, mediaKey, duration, enabled, view, compact = false, visible = true, onSeek }: Props) {
  const list = useRef<HTMLOListElement>(null);
  const [playback, setPlayback] = useState({ time: 0, duration: 0 });
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const update = () => setPlayback({ time: Number.isFinite(video.currentTime) ? video.currentTime : 0,
      duration: Number.isFinite(video.duration) ? video.duration : 0 });
    update();
    for (const name of ['loadedmetadata', 'durationchange', 'timeupdate', 'seeked', 'emptied']) video.addEventListener(name, update);
    return () => { for (const name of ['loadedmetadata', 'durationchange', 'timeupdate', 'seeked', 'emptied']) video.removeEventListener(name, update); };
  }, [videoRef, mediaKey]);
  const total = playback.duration || duration;
  const chapters = timeline.chapters.filter(chapter => !total || chapter.time < total);
  const scale = total || (chapters.at(-1)?.time || 0) + 1;
  const active = enabled ? chapters.reduce((found, chapter, index) => chapter.time <= playback.time ? index : found, -1) : -1;
  // Use the sidebar's single scroll viewport (or the standalone list), never the page/video.
  useEffect(() => {
    if (view !== 'directory' || !visible) return;
    const container = list.current?.closest<HTMLElement>('.study-sidebar-body') || list.current;
    if (!container) return;
    const reveal = () => {
      const item = container.querySelector<HTMLElement>('[aria-current]');
      if (!item || !container.clientHeight) return;
      const parent = container.getBoundingClientRect(), target = item.getBoundingClientRect();
      if (target.top < parent.top) container.scrollTop += target.top - parent.top;
      else if (target.bottom > parent.bottom) container.scrollTop += target.bottom - parent.bottom;
    };
    reveal();
    const observer = new ResizeObserver(reveal); observer.observe(container);
    return () => observer.disconnect();
  }, [active, visible, view, mediaKey, timeline.recordId]);
  if (!chapters.length) return view === 'directory' ? <p className="study-sidebar-empty">没有落在当前视频时长内的章节时间点。</p> : null;
  const current = active >= 0 ? chapters[active] : null;
  const end = current ? (chapters[active + 1]?.time || total) : 0;
  const seek = (time: number) => {
    if (!enabled) return;
    onSeek(time);
    setPlayback(previous => ({ ...previous, time }));
  };
  const introduction = <p className="chapter-timeline-intro-body" translate={current?.description ? 'no' : undefined}>{current ? current.description || '这条分析记录仅提供章节标题，暂无详细介绍。'
    : enabled ? '播放到章节起点，或点击圆点查看这一章的介绍。' : '当前分析记录对应另一份视频，不与此视频同步介绍。'}</p>;
  return <section className={`chapter-timeline chapter-timeline-${view}${compact && view === 'player' ? ' is-compact' : ''}`} aria-labelledby={`chapter-timeline-title-${view}`}>
    <div className="chapter-timeline-heading"><h3 id={`chapter-timeline-title-${view}`} title={timeline.label}>{view === 'player' ? 'AI 章节时间线' : '章节目录'}</h3></div>
    {view === 'player' && <>
    <div className="chapter-timeline-track" role="group" aria-label="点击章节跳转视频">
      {enabled && <span className="chapter-timeline-progress" aria-hidden="true"
        style={{ width: `${Math.min(100, Math.max(0, playback.time / scale * 100))}%` }} />}
      {chapters.map((chapter, index) => <button type="button" className="chapter-timeline-marker" key={chapter.time} disabled={!enabled}
        style={{ left: `${chapter.time / scale * 100}%` }}
        aria-label={`跳到 ${chapterTime(chapter.time)}：${chapter.title}`} aria-current={active === index ? 'true' : undefined}
        title={`${chapterTime(chapter.time)} · ${chapter.title}`} onClick={() => seek(chapter.time)}><span className="chapter-timeline-dot" aria-hidden="true" /></button>)}
    </div>
    {/* Shown once playback reaches a chapter (or when the record belongs to another video); nothing before that. */}
    <section className="chapter-timeline-intro" aria-label="当前章节介绍" aria-live="polite" aria-atomic="true" hidden={!current && enabled}>
      {current && <div className="chapter-timeline-intro-meta"><span>{`当前章节 · ${active + 1} / ${chapters.length}`}</span>
        <time>{chapterTime(current.time)}{end > current.time ? ` — ${chapterTime(end)}` : ''}</time></div>}
      <h4 translate={current ? 'no' : undefined}>{current ? current.title : '请切换到对应视频'}</h4>
      {current && (compact ? <details className="chapter-timeline-description"><summary>查看章节介绍</summary>{introduction}</details> : introduction)}
    </section>
    </>}
    {view === 'directory' && <>
    <ol ref={list} className="chapter-timeline-list" aria-label="章节列表">{chapters.map((chapter, index) => <li key={chapter.time}>
      <button type="button" disabled={!enabled} aria-current={active === index ? 'true' : undefined} onClick={() => seek(chapter.time)}>
        <time>{chapterTime(chapter.time)}</time><span translate="no">{chapter.title}</span></button>
    </li>)}</ol>
    {!enabled && <p className="chapter-timeline-hint">这条分析记录对应另一份视频；切换到对应归档视频后可跳转。</p>}
    </>}
  </section>;
}
