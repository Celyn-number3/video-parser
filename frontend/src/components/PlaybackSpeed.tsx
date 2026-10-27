import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { MAX_RATE, MIN_RATE, SPEED_PRESETS, normalizeRate, readAutoNext, readRate, saveAutoNext, saveRate } from '../lib/playback';
import './playback-speed.css';

type Props = {
  videoRef: RefObject<HTMLVideoElement | null>;
  /** A new media element starts at the saved speed again. */
  mediaKey: string;
};

const PANEL_WIDTH = 220;

/** Native controls stay in charge of seeking; this only owns the playback rate. */
export default function PlaybackSpeed({ videoRef, mediaKey }: Props) {
  const [rate, setRate] = useState(readRate);
  const [draft, setDraft] = useState('');
  const [open, setOpen] = useState(false);
  const [autoNext, setAutoNext] = useState(readAutoNext);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const box = useRef<HTMLDivElement>(null), panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.playbackRate = rate;
    // Some browsers reset the rate when metadata for a new source arrives.
    const apply = () => { video.playbackRate = rate; };
    video.addEventListener('loadedmetadata', apply);
    return () => video.removeEventListener('loadedmetadata', apply);
  }, [videoRef, mediaKey, rate]);

  // The stage clips its children, so the panel is placed against the viewport instead.
  useLayoutEffect(() => {
    if (!open) { setPlace(null); return; }
    const button = box.current?.getBoundingClientRect(), height = panel.current?.getBoundingClientRect().height || 0;
    if (!button) return;
    const below = button.bottom + 6, top = below + height > innerHeight - 8 ? Math.max(8, button.top - height - 6) : below;
    setPlace({ top, left: Math.max(8, Math.min(innerWidth - PANEL_WIDTH - 8, button.right - PANEL_WIDTH)) });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!box.current?.contains(target) && !panel.current?.contains(target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', dismiss); document.removeEventListener('keydown', escape); };
  }, [open]);

  const apply = (value: number) => {
    const next = normalizeRate(value);
    setRate(next); setDraft(String(next)); saveRate(next);
  };

  return <div className="playback-speed" ref={box}>
    <button type="button" className="playback-speed-trigger" aria-haspopup="dialog" aria-expanded={open}
      aria-label="播放速度" title="播放速度" onClick={() => { setDraft(String(rate)); setOpen(value => !value); }}>
      <span aria-hidden="true">{`${rate}×`}</span>
    </button>
    {open && <div className="playback-speed-panel" ref={panel} role="dialog" aria-label="播放速度"
      style={place ? { top: place.top, left: place.left } : { top: 0, left: 0, visibility: 'hidden' }}>
      <div className="playback-speed-presets" role="group" aria-label="常用速度">
        {SPEED_PRESETS.map(preset => <button type="button" key={preset} aria-pressed={preset === rate}
          onClick={() => apply(preset)}>{`${preset}×`}</button>)}
      </div>
      <form className="playback-speed-custom" onSubmit={event => {
        event.preventDefault();
        const typed = Number(draft);
        if (Number.isFinite(typed) && typed > 0) apply(typed);
      }}>
        <label htmlFor="playback-speed-input">自定义速度</label>
        <div className="playback-speed-field">
          <input id="playback-speed-input" type="number" inputMode="decimal" min={MIN_RATE} max={MAX_RATE} step="0.05"
            value={draft} onChange={event => setDraft(event.target.value)} />
          <button type="submit">应用</button>
        </div>
      </form>
      <label className="playback-speed-auto"><input type="checkbox" checked={autoNext}
        onChange={event => { setAutoNext(event.target.checked); saveAutoNext(event.target.checked); }} />播放结束自动播放下一集</label>
    </div>}
  </div>;
}
