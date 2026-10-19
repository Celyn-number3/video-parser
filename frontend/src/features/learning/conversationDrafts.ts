import { useCallback, useSyncExternalStore } from 'react';

export const QUESTION_LIMIT = 2000;
type Snapshot = { drafts: Record<string, string>; draftStorageFailed: boolean };
type Entry = { snapshot: Snapshot; listeners: Set<() => void> };
const entries = new Map<string, Entry>();
const storageKey = (key: string) => `video-parser:chat-drafts:v1:${key}`;
function limited(text: string) {
  const value = text.slice(0, QUESTION_LIMIT);
  const last = value.charCodeAt(value.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? value.slice(0, -1) : value;
}
function read(key: string): Snapshot {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey(key)) || '{}');
    const drafts = value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === 'string')
        .map(([id, text]) => [id, limited(text)])) : {};
    return { drafts, draftStorageFailed: false };
  } catch { return { drafts: {}, draftStorageFailed: true }; }
}
function entry(key: string): Entry {
  let current = entries.get(key);
  if (!current) { current = { snapshot: read(key), listeners: new Set() }; entries.set(key, current); }
  return current;
}

/** One synchronous source for both chat surfaces; never echo a controlled input through parent effects. */
export function useConversationDrafts(projectId: string, resource: string) {
  const key = `${encodeURIComponent(projectId)}:${encodeURIComponent(resource)}`;
  const subscribe = useCallback((listener: () => void) => {
    const current = entry(key); current.listeners.add(listener);
    return () => { current.listeners.delete(listener); };
  }, [key]);
  const snapshot = useCallback(() => entry(key).snapshot, [key]);
  const state = useSyncExternalStore(subscribe, snapshot, snapshot);
  const setDraft = useCallback((id: string, text: string, composing = false) => {
    const current = entry(key), previous = current.snapshot;
    // Keep the browser's entire composition intact. Persist/clamp only confirmed text.
    const value = composing ? text : limited(text);
    const drafts = { ...previous.drafts };
    if (value) drafts[id] = value; else delete drafts[id];
    let failed = previous.draftStorageFailed;
    if (!composing) {
      try {
        if (Object.keys(drafts).length) localStorage.setItem(storageKey(key), JSON.stringify(drafts));
        else localStorage.removeItem(storageKey(key));
        failed = false;
      } catch { failed = true; }
    }
    if ((previous.drafts[id] || '') === value && failed === previous.draftStorageFailed) return;
    current.snapshot = { drafts, draftStorageFailed: failed };
    current.listeners.forEach(listener => listener());
  }, [key]);
  return { ...state, setDraft };
}
