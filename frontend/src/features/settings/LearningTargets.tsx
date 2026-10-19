import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { AgentCatalog, AgentTarget, AISettings } from '../../lib/api';
import { API_TARGET, isEnabled, saveAgentPreferences, targetKey, useAgentPreferences } from '../learning/agentPreferences';
import './learning-targets.css';

type Row = { key: string; target: AgentTarget; label: string; detail?: string; ready: boolean; locked?: boolean };
type Group = { id: string; name: string; state: string; rows: Row[] };

// Presentation changes only: target IDs, browser preference format and discovery stay unchanged.
export default function LearningTargets({ api }: { api: AISettings | null }) {
  const preferences = useAgentPreferences();
  const [catalog, setCatalog] = useState<AgentCatalog | null>(null);
  const [status, setStatus] = useState('');
  const [failed, setFailed] = useState(false);
  const [reading, setReading] = useState(false);
  const [query, setQuery] = useState('');
  const [showIds, setShowIds] = useState(false);
  const discovery = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    request<AgentCatalog>('/ai/agents', controller.signal).then(setCatalog).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setFailed(true); setStatus(reason instanceof Error ? reason.message : '无法读取本地 agent。'); }
    });
    return () => { controller.abort(); discovery.current?.abort(); };
  }, []);
  async function discover() {
    if (discovery.current) return;
    const controller = new AbortController(); discovery.current = controller;
    setReading(true); setStatus(''); setFailed(false);
    try {
      const next = await request<AgentCatalog>('/ai/agents/discover', controller.signal, { confirm: true, engine: 'all', model: '' });
      if (controller.signal.aborted) return;
      setCatalog(next);
      const problem = next.engines.find(item => item.installed && item.error);
      setFailed(!!problem); setStatus(problem ? problem.error : '已读取本机模型列表。');
    } catch (reason) {
      if (!controller.signal.aborted) { setFailed(true); setStatus(reason instanceof Error ? reason.message : '无法读取本地 agent。'); }
    } finally {
      if (discovery.current === controller) { discovery.current = null; setReading(false); }
    }
  }

  const groups: Group[] = [{ id: 'api', name: 'API', state: api?.configured ? '已配置' : '未配置',
    rows: [{ key: targetKey(API_TARGET), target: API_TARGET, label: api?.configured ? api.provider_name + ' · ' + api.model : 'API（模型设置）',
      ready: true, locked: true }] }];
  for (const engine of catalog?.engines || []) {
    const rows: Row[] = [{ key: targetKey({ engine: engine.id, model: '' }), target: { engine: engine.id, model: '', effort: '' },
      label: '跟随工具默认模型', ready: engine.installed }];
    for (const model of engine.models) rows.push({ key: targetKey({ engine: engine.id, model: model.id }),
      target: { engine: engine.id, model: model.id, effort: '' }, label: model.label, detail: model.label === model.id ? undefined : model.id, ready: engine.installed });
    groups.push({ id: engine.id, name: engine.name, rows,
      state: !engine.installed ? '未安装' : engine.discovered ? `${engine.models.length} 个模型` : '未读取模型' });
  }
  const current = targetKey(preferences.target);
  const known = groups.flatMap(group => group.rows);
  if (!known.some(row => row.key === current)) {
    const owner = groups.find(group => group.id === preferences.target.engine);
    const extra = owner && { key: current, target: preferences.target, label: preferences.target.model || '跟随工具默认模型',
      detail: preferences.target.model ? '自定义模型 ID' : undefined, ready: owner.rows[0].ready };
    if (extra) { owner.rows.push(extra); known.push(extra); }
  }
  const selected = known.find(row => row.key === current);
  const enabledKeys = () => preferences.enabled ?? groups.flatMap(group => group.rows).map(row => row.key);
  const effective = (row: Row) => row.locked || row.key === current || isEnabled(preferences, row.target);
  function store(enabled: string[], target: AgentTarget, message: string) {
    const saved = saveAgentPreferences({ enabled, target });
    setFailed(!saved); setStatus(saved ? message : '当前页已生效，关闭或刷新后可能丢失。');
  }
  function toggle(row: Row, on: boolean) {
    if (row.locked) return;
    const keys = enabledKeys().filter(key => key !== row.key);
    if (on) keys.push(row.key);
    const target = !on && row.key === current ? API_TARGET : preferences.target;
    store(keys, target, on ? '已在学习页显示。' : row.key === current ? '已隐藏，默认改为 API。' : '已在学习页隐藏。');
  }
  function makeDefault(key: string) {
    const row = known.find(item => item.key === key);
    if (!row?.ready) return;
    const keys = enabledKeys();
    store(keys.includes(row.key) ? keys : [...keys, row.key], row.target, '默认模型已保存，学习页立即使用。');
  }
  const term = query.trim().toLocaleLowerCase();
  const managed = groups.filter(group => group.id !== 'api').map(group => ({ ...group,
    rows: group.rows.filter(row => !term || `${group.name} ${row.label} ${row.detail || ''} ${row.target.model}`.toLocaleLowerCase().includes(term)) })).filter(group => group.rows.length);
  const enabledCount = known.filter(row => row.ready && effective(row)).length;

  return <section className="settings-card learning-targets" aria-labelledby="learning-targets-title">
    <div className="learning-targets-title"><h3 id="learning-targets-title">学习与对话的模型</h3><span>仅此浏览器 · 自动保存</span></div>
    <div className="learning-default-control">
      <label htmlFor="learning-default-model">默认学习模型</label>
      <select id="learning-default-model" aria-describedby="learning-default-state" value={current} onChange={event => makeDefault(event.target.value)}>
        {!selected && <option value={current} disabled>{preferences.target.engine} · {preferences.target.model || '跟随工具默认模型'}</option>}
        {groups.map(group => <optgroup key={group.id} label={group.name}>{group.rows.map(row =>
          <option key={row.key} value={row.key} disabled={!row.ready} translate={row.target.model || (row.target.engine === 'api' && api?.configured) ? 'no' : undefined}>
            {group.id === 'api' ? (api?.configured ? 'API · ' + row.label : row.label) : group.name + ' · ' + row.label}
          </option>)}</optgroup>)}
      </select>
      {/* Only problems are explained; a working default needs no sentence. */}
      {(() => { const problem = !selected ? '所选默认模型不在当前列表，请检查工具或更换。' : selected.target.engine === 'api'
        ? api && !api.configured ? 'API 连接尚未配置，请展开下方连接配置。' : ''
        : selected.ready ? '' : '本地引擎不可用，请展开选择其他模型。';
        return problem ? <p id="learning-default-state" className="settings-hint">{problem}</p> : null; })()}
      {selected && selected.target.engine !== 'api' && !selected.target.model && <p className="settings-hint">跟随工具默认不代表离线或免费，联网与费用由对应工具配置决定。</p>}
    </div>
    <details className="learning-target-options"><summary>管理学习页可见模型 <small>{enabledCount} 项</small></summary>
      <p className="settings-hint">这里只控制学习页菜单的可见项；隐藏当前默认模型会切回 API。</p>
      <div className="learning-targets-heading">
        <label className="learning-model-search"><span className="sr-only">搜索可见模型</span><input type="search" placeholder="搜索模型名称或 ID" value={query}
          onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') setQuery(''); }} /></label>
        <button type="button" disabled={reading} aria-busy={reading} onClick={() => { void discover(); }}
          title="只运行本机程序读取模型与命令，不发送课程内容">{reading ? '读取中…' : '读取本机模型'}</button>
      </div>
      <div className="learning-model-meta-tools"><label className="settings-check"><input type="checkbox" checked={showIds} onChange={event => setShowIds(event.target.checked)} />显示调用 ID</label></div>
      <div className="learning-fixed-source"><strong>API 连接</strong><span>固定入口 · 始终可见</span></div>
      {managed.map(group => <details key={group.id} className="learning-engine-group" open={term ? true : undefined}>
        <summary><span translate="no">{group.name}</span><small>{group.state}</small></summary>
        <fieldset className="learning-target-group" aria-label={group.name}><legend className="sr-only">{group.name}</legend>
          <ul>{group.rows.map(row => <li key={row.key} className={row.key === current ? 'is-default' : undefined}>
            <label className="settings-check"><input type="checkbox" checked={!!effective(row)} disabled={!row.ready} onChange={event => toggle(row, event.target.checked)} />
              <span className="learning-model-copy"><span translate={row.target.model ? 'no' : undefined}>{row.label}</span>
                {showIds && row.target.model && <code translate="no">{row.target.model}</code>}</span></label>
            {row.key === current && <small className="learning-model-default-badge">当前默认</small>}
          </li>)}</ul>
        </fieldset>
      </details>)}
      {term && managed.length === 0 && <p className="settings-hint" role="status">没有匹配的模型。</p>}
      {!catalog && !failed && <p role="status" className="settings-hint">正在读取本地 agent…</p>}
    </details>
    {status && <p role={failed ? 'alert' : 'status'} aria-live="polite" className={failed ? 'error-text' : 'settings-save-status'}>{status}</p>}
  </section>;
}
