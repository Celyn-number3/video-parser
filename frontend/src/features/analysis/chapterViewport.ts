export type ChapterRow = { top: number; height: number };

/** Size the viewport to whole, variable-height rows within the available frame. */
export function chapterWindow(rows: ChapterRow[], room: number, scroll: number) {
  if (!rows.length || room <= 0) return { top: 0, height: 0 };
  // A pathological tall formula/title must remain freely readable, not a scroll trap.
  const oversized = rows.find(row => row.height > room && scroll >= row.top - .5 && scroll < row.top + row.height);
  if (oversized) return { top: scroll, height: room };
  let first = 0;
  for (let i = 1; i < rows.length; i++) {
    if (Math.abs(rows[i].top - scroll) < Math.abs(rows[first].top - scroll)) first = i;
  }
  if (rows[first].height > room) return { top: rows[first].top, height: room };
  const end = rows.at(-1)!.top + rows.at(-1)!.height;
  // At the end, include preceding rows rather than leaving just the final row visible.
  while (first > 0 && end - rows[first - 1].top <= room + .5) first--;
  let last = first;
  while (last + 1 < rows.length && rows[last + 1].top + rows[last + 1].height - rows[first].top <= room + .5) last++;
  return { top: rows[first].top, height: Math.min(room, rows[last].top + rows[last].height - rows[first].top) };
}
