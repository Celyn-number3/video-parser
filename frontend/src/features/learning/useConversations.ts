import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { AgentTarget, Conversation, ConversationContext } from '../../lib/api';

import { useConversationDrafts } from './conversationDrafts';
export { QUESTION_LIMIT } from './conversationDrafts';

export type PendingQuestion = { conversationId: string; question: string; count: number };
const selectionKey = (project: string) => `video-parser:conversation:${project}`;
function savedSelection(project: string) { try { return localStorage.getItem(selectionKey(project)); } catch { return null; } }

/** One owner in AnalysisPanel feeds both the existing manager and the learning sidebar. */
export default function useConversations(projectId: string, resource: string, version: number, busy: boolean) {
  const key = `${encodeURIComponent(projectId)}:${encodeURIComponent(resource)}`;
  const liveKey = useRef(key); liveKey.current = key;
  const [data, setData] = useState<{ key: string; sessions: Conversation[]; active: string | null; context: ConversationContext | null }>({ key: '', sessions: [], active: null, context: null });
  const [failure, setFailure] = useState('');
  const [creating, setCreating] = useState(false);
  const { drafts, setDraft, draftStorageFailed } = useConversationDrafts(projectId, resource);
  const [pending, setPending] = useState<PendingQuestion | null>(null);
  const [reload, setReload] = useState(0);
  const operations = useRef<AbortController | null>(null);
  const creation = useRef(false);
  useEffect(() => {
    setPending(null); setCreating(false); creation.current = false;
    return () => operations.current?.abort();
  }, [key]);
  useEffect(() => {
    if (!projectId || !resource) return;
    const controller = new AbortController();
    setFailure('');
    Promise.all([
      request<{ conversations: Conversation[] }>(`/projects/${projectId}/conversations${busy ? '' : '/migrate'}`, controller.signal, busy ? undefined : {}),
      request<ConversationContext>(`/projects/${projectId}/conversations/context?resource=${encodeURIComponent(resource)}`, controller.signal),
    ]).then(([list, context]) => {
      if (controller.signal.aborted) return;
      const sessions = list.conversations.filter(item => !item.video_resource || item.video_resource === resource);
      setData(old => {
        const preferred = old.key === key ? old.active : savedSelection(projectId);
        const active = sessions.find(item => item.id === preferred)?.id || sessions[0]?.id || null;
        return { key, sessions, active, context };
      });
      setPending(previous => previous && list.conversations.some(item => item.id === previous.conversationId && item.messages.length > previous.count) ? null : previous);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setFailure(reason instanceof Error ? reason.message : '无法读取对话。'); });
    return () => controller.abort();
  }, [projectId, resource, key, version, busy, reload]);
  const selectConversation = useCallback((id: string) => {
    setData(old => old.key === key && old.sessions.some(item => item.id === id) ? { ...old, active: id } : old);
    try { localStorage.setItem(selectionKey(projectId), id); } catch { /* Optional preference only. */ }
  }, [projectId, key]);
  const newConversation = useCallback(async (agent?: AgentTarget) => {
    if (creation.current) throw new Error('正在创建对话，请稍候。');
    creation.current = true; setCreating(true); setFailure('');
    const controller = new AbortController(); operations.current = controller;
    try {
      const result = await request<{ conversation: Conversation }>(`/projects/${projectId}/conversations`, controller.signal, { resource, agent });
      if (liveKey.current !== key || controller.signal.aborted) throw new Error('当前视频已切换。');
      setData(old => ({ ...old, key, sessions: [result.conversation, ...old.sessions], active: result.conversation.id }));
      try { localStorage.setItem(selectionKey(projectId), result.conversation.id); } catch { /* Optional. */ }
      return result.conversation;
    } finally { if (operations.current === controller) { operations.current = null; creation.current = false; setCreating(false); } }
  }, [projectId, resource, key]);
  const retry = useCallback(() => setReload(value => value + 1), []);
  return useMemo(() => {
  const matches = data.key === key;
  return {
    projectId, resource, ready: matches && !!data.context, available: matches && !!data.context?.available,
    missing: matches ? data.context?.missing || [] : [], sessions: matches ? data.sessions : [],
    session: matches ? data.sessions.find(item => item.id === data.active) || null : null,
    failure, creating, drafts, draftStorageFailed, setDraft, pending, setPending, selectConversation, newConversation,
    retry,
  };
  }, [projectId, resource, data, key, failure, creating, drafts, draftStorageFailed, pending, setDraft, selectConversation, newConversation, retry]);
}

export type ConversationState = ReturnType<typeof useConversations>;
