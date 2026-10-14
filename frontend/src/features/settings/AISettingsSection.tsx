import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { AIPreset, AISettings } from '../../lib/api';

type Draft = { provider: string; base_url: string; model: string; api_key: string; price_input: string; price_output: string };
const toDraft = (value: AISettings): Draft => ({ provider: value.provider, base_url: value.base_url, model: value.model, api_key: '',
  price_input: value.price_input === null ? '' : String(value.price_input), price_output: value.price_output === null ? '' : String(value.price_output) });

// Saved to .local/ai/settings.json by the local service; the key is never sent back to the page.
export default function AISettingsSection({ onChange, autoFocus = false }: { onChange: (settings: AISettings) => void; autoFocus?: boolean }) {
  const [saved, setSaved] = useState<AISettings | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [status, setStatus] = useState('');
  const [failed, setFailed] = useState(false);
  const [working, setWorking] = useState<'save' | 'test' | null>(null);
  const controller = useRef(new AbortController());
  const provider = useRef<HTMLSelectElement>(null);
  const loaded = !!draft;
  useEffect(() => {
    if (!autoFocus || !loaded) return;
    provider.current?.closest('section')?.scrollIntoView({ block: 'start' });
    provider.current?.focus({ preventScroll: true });
  }, [autoFocus, loaded]);
  useEffect(() => {
    const current = controller.current;
    request<AISettings>('/ai/settings', current.signal).then(value => { setSaved(value); setDraft(toDraft(value)); })
      .catch((reason: unknown) => { if (!current.signal.aborted) { setFailed(true); setStatus(reason instanceof Error ? reason.message : '无法读取 AI 设置。'); } });
    return () => current.abort();
  }, []);
  if (!saved || !draft) return <section aria-labelledby="settings-ai"><h3 id="settings-ai">AI 模型</h3><p className={failed ? 'error-text' : 'settings-hint'}>{status || '正在读取…'}</p></section>;

  const preset: AIPreset = saved.presets[draft.provider] || saved.presets.custom || { name: draft.provider, base_url: draft.base_url, model: draft.model, models: [], key_required: true, hint: '' };
  const local = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/.test(draft.base_url);
  const dirty = draft.provider !== saved.provider || draft.base_url !== saved.base_url || draft.model !== saved.model || !!draft.api_key
    || draft.price_input !== (saved.price_input === null ? '' : String(saved.price_input)) || draft.price_output !== (saved.price_output === null ? '' : String(saved.price_output));
  const sameService = draft.base_url.replace(/\/+$/, '') === saved.base_url;
  const keyPlaceholder = saved.key_saved && sameService ? `已保存（${saved.key_hint}），留空表示不修改` : preset.key_required ? '粘贴 API Key' : '本机或无需密钥的服务可留空';
  const priceInvalid = [draft.price_input, draft.price_output].some(value => value !== '' && !(Number(value) >= 0 && Number(value) <= 10000));
  const update = (patch: Partial<Draft>) => { setDraft({ ...draft, ...patch }); setStatus(''); setFailed(false); };
  function chooseProvider(provider: string) {
    const next = saved!.presets[provider]; if (!next) return;
    update(provider === 'custom' ? { provider } : { provider, base_url: next.base_url, model: next.model });
  }
  async function save(clearKey = false): Promise<boolean> {
    setWorking('save'); setStatus(''); setFailed(false);
    try {
      const value = await request<AISettings>('/ai/settings', controller.current.signal, {
        provider: draft!.provider, base_url: draft!.base_url.trim(), model: draft!.model.trim(), api_key: draft!.api_key.trim() || null, clear_key: clearKey,
        price_input: draft!.price_input === '' ? null : Number(draft!.price_input), price_output: draft!.price_output === '' ? null : Number(draft!.price_output),
      });
      setSaved(value); setDraft(toDraft(value)); onChange(value);
      setStatus(clearKey ? '已清除保存的密钥。' : value.configured ? '已保存，立即生效。' : '已保存；还缺少密钥，暂时不能分析。');
      return true;
    } catch (reason) { setFailed(true); setStatus(reason instanceof Error ? reason.message : '保存失败。'); return false; }
    finally { setWorking(null); }
  }
  async function test() {
    if (dirty && !(await save())) return;
    setWorking('test'); setStatus('正在连接模型服务…'); setFailed(false);
    try {
      const result = await request<{ latency_ms: number; model: string }>('/ai/settings/test', controller.current.signal, {});
      setStatus(`连接正常：${result.model}，用时 ${(result.latency_ms / 1000).toFixed(1)} 秒。`);
    } catch (reason) { setFailed(true); setStatus(reason instanceof Error ? reason.message : '连接失败。'); }
    finally { setWorking(null); }
  }

  return <section aria-labelledby="settings-ai" className="settings-ai"><h3 id="settings-ai">AI 模型</h3>
    <label htmlFor="ai-provider">服务</label>
    <select ref={provider} id="ai-provider" value={draft.provider} onChange={event => chooseProvider(event.target.value)}>
      {Object.entries(saved.presets).map(([key, item]) => <option key={key} value={key}>{item.name}</option>)}
    </select>
    {preset.hint && <p className="settings-hint">{preset.hint}</p>}
    <label htmlFor="ai-base-url">接口地址</label>
    <input id="ai-base-url" type="url" value={draft.base_url} spellCheck={false} placeholder="https://…/v1" onChange={event => update({ base_url: event.target.value })} />
    <label htmlFor="ai-model">模型 ID</label>
    <input id="ai-model" list="ai-model-options" value={draft.model} spellCheck={false} placeholder="支持图片输入的模型" onChange={event => update({ model: event.target.value })} />
    <datalist id="ai-model-options">{preset.models.map(model => <option key={model} value={model} />)}</datalist>
    <p className="settings-hint">可从列表选，也可以直接填写更大的模型 ID。只用字幕分析时，纯文本模型也可以。</p>
    {!local && <>
      <label htmlFor="ai-key">API Key</label>
      <input id="ai-key" type="password" autoComplete="off" spellCheck={false} value={draft.api_key} placeholder={keyPlaceholder} onChange={event => update({ api_key: event.target.value })} />
      {!sameService && saved.key_saved && <p className="settings-hint">换了服务地址，原来的密钥不会带过去，请填写新服务的密钥。</p>}
    </>}
    <div className="settings-price">
      <label>输入单价<input type="number" min="0" max="10000" step="0.01" inputMode="decimal" value={draft.price_input} placeholder="选填" onChange={event => update({ price_input: event.target.value })} /></label>
      <label>输出单价<input type="number" min="0" max="10000" step="0.01" inputMode="decimal" value={draft.price_output} placeholder="选填" onChange={event => update({ price_output: event.target.value })} /></label>
      <span>元 / 百万 tokens，用于估算费用</span>
    </div>
    <div className="settings-actions">
      <button type="button" className="primary" disabled={!dirty || priceInvalid || working !== null} aria-busy={working === 'save'} onClick={() => { void save(); }}>保存</button>
      <button type="button" disabled={working !== null || priceInvalid || (!saved.configured && !dirty)} aria-busy={working === 'test'} onClick={() => { void test(); }}>测试连接</button>
      {saved.key_saved && saved.source === 'settings' && !local && <button type="button" className="link-button" disabled={working !== null} onClick={() => { void save(true); }}>清除密钥</button>}
    </div>
    {status && <p role="status" aria-live="polite" className={failed ? 'error-text' : 'settings-save-status'}>{status}</p>}
    <p className="settings-hint">
      {saved.configured ? `当前：${saved.provider_name} · ${saved.model}` : '当前：未配置'}
      {saved.source === 'env' ? '（来自 .env；在这里保存后以这里为准）' : ''}
      {saved.local ? ' · 本机运行，不需要同意发送' : saved.consented ? ' · 已同意发送到这个服务' : ' · 第一次分析时会询问是否同意发送'}
    </p>
    <p className="settings-hint">{saved.storage}</p>
  </section>;
}
