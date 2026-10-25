import MathText from '../../components/MathText';
import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { request } from '../../lib/api';
import type { TranscriptOption } from '../../lib/api';
import './subtitle-panel.css';
type Data = { resource: string; sources: TranscriptOption[]; cues: { time: number; text: string }[] };
export type SubtitlePanelProps = { projectId: string; mediaKey: string; videoRef: RefObject<HTMLVideoElement | null>; onSeek: (time: number) => void; onGenerate: () => void; version?: number };
export default function SubtitlePanel({ projectId, mediaKey, videoRef, onSeek, onGenerate, version = 0 }: SubtitlePanelProps) {
  const [data, setData] = useState<Data | null>(null), [resource, setResource] = useState(''), [error, setError] = useState('');
  const [reload, setReload] = useState(0), [current, setCurrent] = useState(0), [follow, setFollow] = useState(true);
  const [seekVersion, setSeekVersion] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { setResource(''); setData(null); setCurrent(0); setFollow(true); }, [projectId, mediaKey]);
  useEffect(() => {
    const controller = new AbortController(); setError('');
    request<Data>(`/projects/${projectId}/subtitle-cues?resource=${encodeURIComponent(resource)}`, controller.signal).then(setData)
      .catch((e: unknown) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '读取字幕失败'); });
    return () => controller.abort();
  }, [projectId, mediaKey, resource, reload, version]);
  useEffect(() => {
    const video = videoRef.current; if (!video) return;
    const update = () => setCurrent(video.currentTime);
    // Listen on the media element, so native scrubbing, keyboard and timestamp seeks
    // all resume follow. Ordinary playback must not override manual subtitle browsing.
    const seeking = () => { update(); setFollow(true); setSeekVersion(value => value + 1); };
    // A user may pause follow while a seek is buffering; completion must respect that.
    const seeked = () => { update(); setSeekVersion(value => value + 1); };
    video.addEventListener('timeupdate', update);
    video.addEventListener('seeking', seeking); video.addEventListener('seeked', seeked); update();
    return () => {
      video.removeEventListener('timeupdate', update);
      video.removeEventListener('seeking', seeking); video.removeEventListener('seeked', seeked);
    };
  }, [videoRef, projectId, mediaKey]);
  useEffect(() => {
    const refresh = () => setReload(value => value + 1);
    window.addEventListener('video-parser:subtitles-changed', refresh);
    return () => window.removeEventListener('video-parser:subtitles-changed', refresh);
  }, []);
  let active = -1;
  data?.cues.forEach((cue, i) => { if (cue.time <= current) active = i; });
  useEffect(() => {
    const element = list.current;
    if (!follow || !element) return;
    const align = () => {
      const row = element.querySelector<HTMLElement>('[aria-current="true"]');
      if (row && element.clientHeight > 0) element.scrollTop = Math.max(0, row.offsetTop - element.clientHeight / 3);
    };
    align();
    // The subtitle tab can be hidden when seeking. Align again when it becomes visible
    // or reflows, including a paused video whose active cue has not changed.
    const observer = new ResizeObserver(align); observer.observe(element);
    return () => observer.disconnect();
  }, [active, follow, seekVersion, data]);
  return <section className="subtitle-scroll-panel" aria-label="滚动字幕">
    <strong className="sr-only">字幕</strong>
    {error && <p role="alert">{error}</p>}
    {!data?.cues.length ? <p>暂无字幕。<button type="button" onClick={onGenerate}>生成字幕</button></p> : <>
      <div className="subtitle-toolbar"><select aria-label="字幕版本" value={data.resource} onChange={e => setResource(e.target.value)}>{data.sources.map(source => <option key={source.resource} value={source.resource}>{source.label}</option>)}</select>
      <button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? '自动跟随：开启' : '恢复自动跟随'}</button></div>
      <div className="subtitle-scroll-list" ref={list} tabIndex={0} onWheel={() => setFollow(false)} onTouchMove={() => setFollow(false)} onKeyDown={e => { if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) setFollow(false); }}>
        {data.cues.map((cue, i) => <button type="button" key={i} aria-current={active === i ? 'true' : undefined} onClick={() => onSeek(cue.time)}><time>{Math.floor(cue.time / 60)}:{String(Math.floor(cue.time % 60)).padStart(2, '0')}</time><MathText text={cue.text} /></button>)}
      </div></>}
  </section>;
}
