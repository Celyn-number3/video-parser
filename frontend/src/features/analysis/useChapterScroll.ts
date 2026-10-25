import { useLayoutEffect, useState, type RefObject } from 'react';
import { chapterWindow } from './chapterViewport';

/** One inner scroll owner. Preserve native wheel/touch/keyboard movement; settle after it ends. */
export default function useChapterScroll(ref: RefObject<HTMLOListElement | null>, active: number, visible: boolean, identity: string) {
  const [hasMore, setHasMore] = useState(false);
  const scrollNext = () => {
    const list = ref.current;
    if (!list) return;
    list.focus({ preventScroll: true });
    list.scrollBy({ top: Math.max(44, list.clientHeight - 44), behavior: 'auto' });
  };
  useLayoutEffect(() => {
    const list = ref.current, frame = list?.parentElement;
    if (!visible || !list || !frame) { setHasMore(false); return; }
    const updateHint = () => setHasMore(list.scrollTop + list.clientHeight < list.scrollHeight - 2);
    let timer = 0, raf = 0, dragging = false, alive = true, internalTop: number | null = null;
    const rows = () => {
      const top = list.getBoundingClientRect().top;
      return Array.from(list.children, child => {
        const rect = child.getBoundingClientRect();
        return { top: rect.top - top + list.scrollTop, height: rect.height };
      });
    };
    function fit(reveal = -1) {
      if (!alive || !list || !frame || !frame.getClientRects().length) return;
      const css = getComputedStyle(frame);
      const room = frame.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom);
      if (room < 1) return;
      const measured = rows();
      let target = list.scrollTop;
      const row = measured[reveal];
      if (row && (row.top < target - .5 || row.top + row.height > target + list.clientHeight + .5)) target = row.top;
      let next = chapterWindow(measured, room, target);
      // Native focus scrolling can reveal a bottom row before focusin. Snapping
      // must not shrink that row out of the new viewport again.
      if (row && row.height <= room &&
          (row.top < next.top - .5 || row.top + row.height > next.top + next.height + .5)) {
        next = chapterWindow(measured, room, row.top);
      }
      list.style.height = `${next.height}px`;
      internalTop = next.top;
      list.scrollTop = next.top;
      list.dataset.settled = 'true';
      updateHint();
    }
    function settle() {
      window.clearTimeout(timer);
      if (!dragging) timer = window.setTimeout(() => fit(), 160);
    }
    const scroll = () => {
      updateHint();
      if (internalTop !== null && Math.abs(list.scrollTop - internalTop) < 1) { internalTop = null; return; }
      internalTop = null; delete list.dataset.settled; settle();
    };
    const down = () => { dragging = true; window.clearTimeout(timer); };
    const up = () => { if (dragging) { dragging = false; settle(); } };
    const focus = (event: FocusEvent) => {
      const item = (event.target as HTMLElement).closest('li');
      if (item?.parentElement === list) fit(Array.from(list.children).indexOf(item));
    };
    const resize = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => fit()); };
    list.addEventListener('scroll', scroll, { passive: true });
    list.addEventListener('pointerdown', down, { passive: true });
    window.addEventListener('pointerup', up, { passive: true });
    window.addEventListener('pointercancel', up, { passive: true });
    list.addEventListener('focusin', focus);
    const observer = new ResizeObserver(resize);
    observer.observe(frame);
    for (const child of list.children) observer.observe(child);
    fit(active);
    document.fonts.ready.then(() => { if (alive) fit(); });
    return () => {
      alive = false; window.clearTimeout(timer); cancelAnimationFrame(raf); observer.disconnect();
      list.removeEventListener('scroll', scroll); list.removeEventListener('pointerdown', down);
      window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up);
      list.removeEventListener('focusin', focus);
    };
  }, [ref, active, visible, identity]);
  return { hasMore, scrollNext };
}
