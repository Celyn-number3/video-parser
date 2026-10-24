import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent, RefObject } from 'react';
import type { Media } from '../../lib/api';
import Icon from '../../components/Icon';
import ChapterTimeline from '../analysis/ChapterTimeline';
import type { AnalysisTimeline } from '../analysis/chapters';
import TimestampNotes from './TimestampNotes';
import AIChat from './AIChat';
import type { AIChatProps } from './AIChat';
import './study-sidebar.css';
import SubtitlePanel from './SubtitlePanel';
import type { SubtitlePanelProps } from './SubtitlePanel';

type Props = {
  projectId: string; media: Media; videoRef: RefObject<HTMLVideoElement | null>;
  timeline: AnalysisTimeline | null; enabled: boolean; collapsed: boolean;
  onToggle: () => void; onSeek: (time: number) => void; assistant: AIChatProps;
  /** alignTo is the playback bar whose bottom the sidebar matches. */
  subtitles?: SubtitlePanelProps;
  active: boolean; alignTo: RefObject<HTMLElement | null>;
};
const tabs = [{ id: 'chapters', label: '章节' }, { id: 'notes', label: '个人笔记' }, { id: 'chat', label: 'AI 对话' }, { id: 'subtitles', label: '字幕' }] as const;
type Tab = typeof tabs[number]['id'];
const WIDE = '(min-width: 1171px)';
export default function StudySidebar({ projectId, media, videoRef, timeline, enabled, collapsed, onToggle, onSeek, assistant, alignTo, active, subtitles }: Props) {
  const [tab, setTab] = useState<Tab>('chapters');
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const aside = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const positions = useRef<Partial<Record<Tab, number>>>({});
  useLayoutEffect(() => { positions.current = {}; }, [projectId, media.resource]);
  useLayoutEffect(() => {
    const element = body.current;
    if (element) element.scrollTop = positions.current[tab] ?? (tab === 'chat' ? element.scrollHeight : 0);
  }, [tab, projectId, media.resource, collapsed, active]);
  function show(id: Tab) { setTab(id); }
  useEffect(() => {
    const sidebar = aside.current, anchor = alignTo.current, panel = anchor?.closest('.preview-panel');
    if (!sidebar || !anchor || !panel || collapsed) return;
    const wide = window.matchMedia(WIDE);
    const reset = () => { delete sidebar.dataset.aligned; sidebar.style.removeProperty('--study-sidebar-height'); };
    const align = () => {
      // Unrounded: rounding left the sidebar up to 1px longer than the bar.
      const height = anchor.getBoundingClientRect().bottom - sidebar.getBoundingClientRect().top;
      if (!wide.matches || height <= 0) { reset(); return; }
      sidebar.dataset.aligned = ''; sidebar.style.setProperty('--study-sidebar-height', `${height}px`);
    };
    // The panel resizes when the video loads or the bar wraps; the sidebar itself is never observed (no feedback loop).
    const observer = new ResizeObserver(align);
    observer.observe(panel); wide.addEventListener('change', align); align();
    return () => { observer.disconnect(); wide.removeEventListener('change', align); reset(); };
  }, [alignTo, collapsed, media.resource, projectId, active]);
  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index+1)%tabs.length : event.key === 'ArrowLeft' ? (index+tabs.length-1)%tabs.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : null;
    if (next === null) return;
    event.preventDefault(); show(tabs[next].id); buttons.current[next]?.focus();
  }
  return <aside ref={aside} className={'study-sidebar' + (collapsed ? ' is-collapsed' : '')} aria-label="学习侧栏">
    <div className="study-sidebar-heading"><h2 className={collapsed ? undefined : 'sr-only'}>学习侧栏</h2>
      <button type="button" className="study-sidebar-toggle" onClick={onToggle} aria-expanded={!collapsed}
        aria-controls="learning-sidebar-content project-context" aria-label={collapsed ? '展开学习侧栏' : '收起学习侧栏'}
        title={collapsed ? '展开学习侧栏' : '收起学习侧栏'}><Icon name={collapsed ? 'book-open' : 'x'} /></button></div>
    <div id="learning-sidebar-content" hidden={collapsed}>
      <div className="study-sidebar-tabs" role="tablist" aria-label="学习侧栏内容">{tabs.map((item,index) =>
        <button type="button" key={item.id} ref={element => { buttons.current[index] = element; }}
          id={`study-tab-${item.id}`} role="tab" aria-selected={tab === item.id} aria-controls={`study-panel-${item.id}`}
          tabIndex={tab === item.id ? 0 : -1} onClick={() => show(item.id)} onKeyDown={event => move(event,index)}>{item.label}</button>)}</div>
      <div className="study-sidebar-body" data-tab={tab} ref={body} onScroll={event => { if (!collapsed && active && event.currentTarget.getClientRects().length) positions.current[tab] = event.currentTarget.scrollTop; }}>
        <div id="study-panel-chapters" role="tabpanel" aria-labelledby="study-tab-chapters" hidden={tab !== 'chapters'}>
          {timeline ? <ChapterTimeline timeline={timeline} videoRef={videoRef} mediaKey={`${projectId}:${media.preview_url}`}
            duration={media.duration} enabled={enabled} view="directory" visible={!collapsed && tab === 'chapters'} onSeek={onSeek} />
            : <p className="study-sidebar-empty">暂无章节目录，生成“章节时间轴”后可在这里跳转。</p>}
        </div>
        <div id="study-panel-notes" role="tabpanel" aria-labelledby="study-tab-notes" hidden={tab !== 'notes'}>
          {/* Hidden rather than unmounted: switching tabs or collapsing must not lose the editor/draft. */}
          <TimestampNotes key={`${projectId}:${media.resource}`} projectId={projectId} media={media} videoRef={videoRef} onSeek={onSeek} />
        </div>
        <div id="study-panel-subtitles" role="tabpanel" aria-labelledby="study-tab-subtitles" hidden={tab !== 'subtitles'}>
          {subtitles && <SubtitlePanel {...subtitles} />}
        </div>
        <div id="study-panel-chat" role="tabpanel" aria-labelledby="study-tab-chat" hidden={tab !== 'chat'}>
          <AIChat key={`chat:${projectId}:${media.resource}`} {...assistant} videoRef={videoRef} duration={media.duration} onSeek={onSeek}
            floating visible={active && !collapsed && tab === 'chat'} pickerVisible={active && (collapsed || tab === 'chat')} onReveal={() => { if (collapsed) onToggle(); show('chat'); }} />
        </div>
      </div>
    </div>
  </aside>;
}
