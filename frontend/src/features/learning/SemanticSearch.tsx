import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
type Hit = { text: string; time: number; score: number; title: string; part: number | null; resource: string };
export default function SemanticSearch({ projectId, onSeek }: { projectId: string; onSeek: (time: number) => void }) {
  const [query, setQuery] = useState(''), [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [results, setResults] = useState<Hit[]>([]);
  const [endpoint, setEndpoint] = useState(''); const pending = useRef<AbortController | null>(null);
  useEffect(() => { setResults([]); setMessage(''); setConsent(false); setBusy(false); return () => pending.current?.abort(); }, [projectId]);
  useEffect(() => { const controller = new AbortController(); const load = () => { setConsent(false); request<{ base_url: string; model: string }>('/embedding/settings', controller.signal).then(data => setEndpoint([data.base_url, data.model].filter(Boolean).join(' · '))).catch(() => setEndpoint('')); }; load(); window.addEventListener('video-parser:embedding-changed', load); return () => { controller.abort(); window.removeEventListener('video-parser:embedding-changed', load); }; }, []);
  async function run(index: boolean) {
    if (!consent || busy) return;
    const c = new AbortController(); pending.current = c; setBusy(true); setMessage(''); setResults([]);
    try {
      if (index) { const data = await request<{ count: number }>(`/projects/${projectId}/embedding/index`, c.signal, { consent: true }); if (!c.signal.aborted) setMessage(`已索引 ${data.count} 个字幕片段。`); }
      else { const data = await request<{ results: Hit[] }>(`/projects/${projectId}/embedding/search`, c.signal, { query, consent: true }); if (!c.signal.aborted) { setResults(data.results); setMessage(`找到 ${data.results.length} 个相关片段。`); } }
    } catch (e) { if (!c.signal.aborted) setMessage(e instanceof Error ? e.message : '检索失败'); } finally { if (!c.signal.aborted) setBusy(false); }
  }
  return <details className="subtitle-scroll-panel"><summary>语义检索 · 当前视频字幕</summary>
    <p>在设置 → AI 模型配置 Embedding。首次检索前建立索引；字幕或模型变化后需重建。</p>
    <p translate="no">{endpoint || '尚未配置 Embedding 服务'}</p><label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />同意将当前视频字幕（建立索引）或查询（检索）发送到上述服务，可能产生费用。</label>
    <div className="subtitle-toolbar"><button type="button" disabled={!consent || busy || !endpoint} onClick={() => { void run(true); }}>建立 / 重建索引</button>
      <input aria-label="语义检索问题" value={query} maxLength={2000} placeholder="例如：如何管理项目排期？" onChange={e => setQuery(e.target.value)} />
      <button type="button" disabled={!consent || busy || !query.trim() || !endpoint} onClick={() => { void run(false); }}>{busy ? '处理中…' : '语义检索'}</button></div>
    <p role="status">{message}</p><ol>{results.map((hit, i) => <li key={i}><button type="button" onClick={() => onSeek(hit.time)}>{hit.part ? `P${hit.part} · ` : ''}{Math.floor(hit.time / 60)}:{String(Math.floor(hit.time % 60)).padStart(2, '0')} · {hit.title}</button><p translate="no">{hit.text}</p><small>来源：{hit.resource} · 相似度 {hit.score.toFixed(3)}</small></li>)}</ol>
  </details>;
}
