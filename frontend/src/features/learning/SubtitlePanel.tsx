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
    const update = () => setCurrent(video.currentTime); video.addEventListener('timeupdate', update); update();
    return () => video.removeEventListener('timeupdate', update);
  }, [videoRef, mediaKey]);
  useEffect(() => {
    const refresh = () => setReload(value => value + 1);
    window.addEventListener('video-parser:subtitles-changed', refresh);
    return () => window.removeEventListener('video-parser:subtitles-changed', refresh);
  }, []);
  let active = -1;
  data?.cues.forEach((cue, i) => { if (cue.time <= current) active = i; });
  useEffect(() => {
    const row = list.current?.querySelector<HTMLElement>('[aria-current="true"]');
    if (follow && row && list.current) list.current.scrollTop = Math.max(0, row.offsetTop - list.current.clientHeight / 3);
  }, [active, follow]);
  return <section className="subtitle-scroll-panel" aria-label="滚动字幕">
    <strong className="sr-only">字幕</strong>
    {error && <p role="alert">{error}</p>}
    {!data?.cues.length ? <p>暂无字幕。<button type="button" onClick={onGenerate}>生成字幕</button></p> : <>
      <div className="subtitle-toolbar"><select aria-label="字幕版本" value={data.resource} onChange={e => setResource(e.target.value)}>{data.sources.map(source => <option key={source.resource} value={source.resource}>{source.label}</option>)}</select>
      <button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? '自动跟随：开启' : '恢复自动跟随'}</button></div>
      <div className="subtitle-scroll-list" ref={list} tabIndex={0} onWheel={() => setFollow(false)} onTouchMove={() => setFollow(false)} onKeyDown={e => { if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) setFollow(false); }}>
        {data.cues.map((cue, i) => <button type="button" key={i} aria-current={active === i ? 'true' : undefined} onClick={() => onSeek(cue.time)}><time>{Math.floor(cue.time / 60)}:{String(Math.floor(cue.time % 60)).padStart(2, '0')}</time><span translate="no">{cue.text}</span></button>)}
      </div></>}
  </section>;
}
