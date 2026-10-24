import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { VideoProject, VideoProjectSummary } from '../../lib/api';
import { projectDisplayTitle, videoDisplayTitle } from '../../lib/projectTitles';

type Item = VideoProject | VideoProjectSummary;
const single = (p: Item) => p.is_single === true || !p.part;
export const projectLabel = (p: Item) => `${single(p) ? '' : `P${p.part} · `}${videoDisplayTitle(p)}`;
export const projectSearch = (p: Item) => `${p.title} ${courseName(p)} ${p.episode_title || ''} ${!single(p) && p.part ? `P${p.part} P${String(p.part).padStart(3, '0')}` : ''}`;
const courseName = (p: Item) => p.display_title || projectDisplayTitle(p).replace(/[（(]完整版[^）)]*[）)]/g, '').replace(/(?:通俗易懂|绝对是|必看|天花板).*$/, '').trim() || p.title;

const keyOf = (p: Item) => single(p) ? 'single' : `${p.location?.split('/')[0] || p.platform}:${p.video_id || p.id}`;

type Props = { items: Item[]; current: Item | null; label: string; disabled: boolean; query: string; setQuery: (v: string) => void; onSelect: (id: string) => void };
export default function ProjectPickerMenu({ items, current, label, disabled, query, setQuery, onSelect }: Props) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null), popup = useRef<HTMLDivElement>(null), input = useRef<HTMLInputElement>(null);
  const pendingFocus = useRef(false);
  const [open, setOpen] = useState(false), [active, setActive] = useState('');
  const [position, setPosition] = useState({ left: 16, top: 80, width: 320, maxHeight: 420 });
  const groups = new Map<string, { name: string; full: string; items: Item[] }>();
  for (const item of items) {
    const key = keyOf(item);
    if (!groups.has(key)) groups.set(key, { name: single(item) ? '单个视频' : courseName(item), full: single(item) ? '单个视频' : projectDisplayTitle(item), items: [] });
    groups.get(key)!.items.push(item);
  }
  for (const [key, group] of groups) {
    if (key !== 'single') group.items.sort((a, b) => (a.part || 0) - (b.part || 0));
    if (key !== 'single' && [...groups.values()].filter(other => other.name === group.name).length > 1) group.name += ` · ${group.items[0].video_id || group.items[0].id.slice(0, 6)}`;
  }
  const ordered = [...groups.entries()].sort(([a], [b]) => a === 'single' ? 1 : b === 'single' ? -1 : 0);
  const enabled = ordered.flatMap(([, g]) => g.items).filter(p => 'resources' in p ? p.resources.some(r => r.kind === 'video') : p.archived);
  const close = (focus = true) => { setOpen(false); if (focus) trigger.current?.focus(); };
  const choose = (p: Item) => { close(); if (p.id !== current?.id) { pendingFocus.current = true; onSelect(p.id); } };
  function navigate(key: string) {
    if (!enabled.length) return;
    const index = enabled.findIndex(p => p.id === active);
    const next = key === 'Home' ? 0 : key === 'End' ? enabled.length - 1 : key === 'ArrowUp' ? (index <= 0 ? enabled.length : index) - 1 : (index + 1) % enabled.length;
    setActive(enabled[next].id);
  }
  useEffect(() => {
    if (!open) return;
    function place() {
      const box = trigger.current!.getBoundingClientRect(), width = Math.min(420, innerWidth - 32);
      const below = innerHeight - box.bottom - 16, above = box.top - 16;
      const flip = below < 220 && above > below, height = Math.min(460, Math.max(120, flip ? above : below));
      setPosition({ left: Math.max(16, Math.min(box.right - width, innerWidth - width - 16)), top: flip ? Math.max(16, box.top - height - 6) : box.bottom + 6, width, maxHeight: height });
    }
    place(); input.current?.focus();
    function outside(event: PointerEvent) { if (!popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close(false); }
    function focusOutside(event: FocusEvent) { if (!popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close(false); }
    document.addEventListener('pointerdown', outside); document.addEventListener('focusin', focusOutside);
    window.addEventListener('resize', place); window.addEventListener('scroll', place, true);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('focusin', focusOutside); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [open]);
  useEffect(() => {
    if (disabled) setOpen(false);
    else if (pendingFocus.current) {
      pendingFocus.current = false;
      if (document.activeElement === document.body || document.activeElement === trigger.current) trigger.current?.focus();
    }
  }, [disabled, current?.id]);
  useEffect(() => { if (open) document.getElementById(`${id}-${active}`)?.scrollIntoView({ block: 'nearest' }); }, [active, open, id]);
  const activeItem = enabled.find(p => p.id === active);
  return <>
    <button ref={trigger} type="button" className="project-picker-trigger" role="combobox" aria-label={label} aria-haspopup="listbox"
      aria-expanded={open} aria-controls={open ? id : undefined} data-value={current?.id || ''} disabled={disabled}
      onClick={() => { setActive(current?.id || enabled[0]?.id || ''); setOpen(!open); }}
      onKeyDown={e => { if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) { e.preventDefault(); setActive(current?.id || enabled[0]?.id || ''); setOpen(true); } }}>
      <span translate={current ? "no" : undefined}>{current ? projectLabel(current) : '选择已归档视频…'}</span><span aria-hidden="true">⌄</span>
    </button>
    {open && createPortal(<div ref={popup} className="project-picker-popup" style={position}
      onKeyDown={e => {
        if (e.nativeEvent.isComposing) return;
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
        else if (['ArrowDown', 'ArrowUp'].includes(e.key) || (e.target !== input.current && ['Home', 'End'].includes(e.key))) { e.preventDefault(); navigate(e.key); }
        else if (e.key === 'Enter' && !e.nativeEvent.isComposing && activeItem) { e.preventDefault(); choose(activeItem); }
        else if (e.key === 'Tab') { close(); }
      }}>
      <div className="project-picker-filter"><input ref={input} type="search" aria-label="筛选视频列表" placeholder="搜索课程、分集或 P 号" value={query}
        aria-controls={id} aria-activedescendant={activeItem ? `${id}-${activeItem.id}` : undefined}
        onChange={e => { setQuery(e.target.value); setActive(''); }} /></div>
      <div id={id} role="listbox" aria-label={label} className="project-picker-options" tabIndex={0} aria-activedescendant={activeItem ? `${id}-${activeItem.id}` : undefined}>
        {ordered.map(([key, group]) => <div key={key} role="group" aria-label={group.full}>
          <div className="project-picker-group" aria-hidden="true" translate={key === 'single' ? undefined : "no"}>{group.name}</div>
          {group.items.map(p => {
            const available = enabled.some(item => item.id === p.id);
            return <div id={`${id}-${p.id}`} key={p.id} role="option" data-project-id={p.id} aria-selected={p.id === current?.id} aria-disabled={!available}
              className={'project-picker-option' + (p.id === active ? ' is-active' : '')} onClick={() => { if (available) choose(p); }}>
              <span translate="no">{projectLabel(p)}{!available ? '（尚未归档）' : ''}</span><span aria-hidden="true">{p.id === current?.id ? '✓' : ''}</span>
            </div>;
          })}
        </div>)}
        {!items.length && <p className="project-picker-empty">没有匹配的视频</p>}
      </div>
    </div>, document.body)}
  </>;
}
