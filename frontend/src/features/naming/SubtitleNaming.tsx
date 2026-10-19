import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { Configuration } from '../../lib/api';
import { cancelTask, isActive, pollJob } from '../../lib/jobs';
import AgentModelPicker from '../learning/AgentModelPicker';
import useAgentModels from '../learning/useAgentModels';
import type { NamingEntry, NamingInventory, NamingJob, NamingPlan, NamingPreview, NamingRow } from './types';
import './subtitle-naming.css';

type Props = { projectId: string; config: Configuration | null; initialTaskId?: string | null;
  onClose: () => void; onChanged: () => Promise<void>; onBeforeApply: () => void; onOpenSettings: (button: HTMLButtonElement) => void };
const states: Record<string, string> = { analyzing: '生成建议中', proposed: '待编辑与验证', validated: '已验证，尚未改名', applying: '事务未完成，需检查恢复',
  applied: '真实文件名已同步', rolled_back: '已恢复原命名', recovery_required: '需要恢复原命名', failed: '未生成建议，没有改名', stale: '来源已变化，不可执行' };
const ready = (entry: NamingEntry) => entry.files.length > 0 && !!entry.transcript;

export default function SubtitleNaming({ projectId, config, initialTaskId, onClose, onChanged, onBeforeApply, onOpenSettings }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const active = useRef<AbortController | null>(null);
  const cancelRequest = useRef<AbortController | null>(null);
  const focusedDraft = useRef('');
  const [inventory, setInventory] = useState<NamingInventory | null>(null);
  const inventoryRef = useRef<NamingInventory | null>(null);
  const [plan, setPlan] = useState<NamingPlan | null>(null);
  const [rows, setRows] = useState<NamingRow[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<NamingPreview | null>(null);
  const [job, setJob] = useState<NamingJob | null>(null);
  const [pending, setPending] = useState(false);
  const [consent, setConsent] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');
  const models = useAgentModels(config?.ai || null, !!config?.ai_configured);
  const working = pending || isActive(job?.state);
  const canValidate = !!plan && ['proposed', 'validated'].includes(plan.state);
  const canRestore = !!plan && ['applied', 'applying', 'recovery_required'].includes(plan.state);
  useEffect(() => { setConsent(false); }, [models.key]);
  useEffect(() => {
    if (working) return;
    if (plan?.adjusted_from && canValidate && focusedDraft.current !== plan.id) {
      dialog.current?.querySelector<HTMLInputElement>('.naming-row-title input')?.focus(); focusedDraft.current = plan.id;
    } else if (plan?.state === 'applied' && focusedDraft.current) {
      dialog.current?.querySelector<HTMLButtonElement>('.naming-editor > button')?.focus(); focusedDraft.current = '';
    }
  }, [plan?.id, plan?.adjusted_from, plan?.state, canValidate, working]);

  function own(identifier: string) {
    if (!inventoryRef.current?.entries.some(entry => entry.project_id === identifier)) throw new Error('这个命名任务不属于当前课程，未切换或修改文件。');
  }
  async function readInventory(signal: AbortSignal) {
    const next = await request<NamingInventory>(`/projects/${projectId}/naming`, signal);
    if (signal.aborted) return next;
    inventoryRef.current = next; setInventory(next);
    return next;
  }
  async function readPlan(identifier: string, signal: AbortSignal) {
    const next = await request<NamingPlan>(`/naming/plans/${identifier}`, signal);
    if (signal.aborted) return next;
    own(next.project_id); setPlan(next); setConfirm(false); setRestoreConfirm(false);
    const edited = new Map((next.preview?.rows || []).map(row => [row.project_id, row]));
    setRows(next.rows.map(row => edited.get(row.project_id) || row));
    setSelected(next.preview?.rows.map(row => row.project_id) || next.rows.map(row => row.project_id));
    setPreview(next.preview ? { ...next.preview, plan_id: next.id, preview_token: next.preview_token || '' } : null);
    return next;
  }
  async function follow(initial: NamingJob, signal: AbortSignal) {
    own(initial.project_id); setJob(initial);
    const final = isActive(initial.state) ? await pollJob<NamingJob>(`/naming/tasks/${initial.id}`, signal, value => setJob(value)) : initial;
    if (signal.aborted) return;
    setJob(final); setCancelling(false);
    if (final.result?.plan_id) await readPlan(final.result.plan_id, signal);
    if (final.operation !== 'plan') await onChanged();
    await readInventory(signal);
    if (final.state !== 'completed') setError(final.message);
  }
  async function perform(action: (signal: AbortSignal) => Promise<unknown>) {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller;
    setPending(true); setError('');
    try { await action(controller.signal); }
    catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '操作未完成，未自动重试。'); }
    finally { if (active.current === controller) { active.current = null; if (!controller.signal.aborted) setPending(false); } }
  }
  useEffect(() => {
    const element = dialog.current; element?.showModal();
    void perform(async signal => {
      const next = await readInventory(signal);
      if (signal.aborted) return;
      setSelected(next.entries.filter(ready).map(entry => entry.project_id));
      if (initialTaskId) await follow(await request<NamingJob>(`/naming/tasks/${initialTaskId}`, signal), signal);
    });
    return () => { active.current?.abort(); active.current = null; cancelRequest.current?.abort(); cancelRequest.current = null; element?.close(); };
  }, [projectId, initialTaskId]);

  function toggle(identifier: string) {
    setSelected(values => values.includes(identifier) ? values.filter(value => value !== identifier) : [...values, identifier]);
    setPreview(null); setConfirm(false);
  }
  function edit(identifier: string, key: 'number' | 'title', value: string) {
    setRows(values => values.map(row => row.project_id === identifier ? { ...row, [key]: value } : row));
    setPreview(null); setConfirm(false);
  }
  function startNew() {
    setPlan(null); setRows([]); setPreview(null); setJob(null); setConsent(false); setConfirm(false); setRestoreConfirm(false); setError('');
    setSelected(inventory?.entries.filter(ready).map(entry => entry.project_id) || []);
  }
  async function adjustNaming(signal: AbortSignal) {
    if (!plan || plan.state !== 'applied') return;
    const result = await request<{ plan_id: string }>(`/projects/${projectId}/naming/adjust`, signal, { plan_id: plan.id });
    if (signal.aborted) return;
    await readInventory(signal);
    if (signal.aborted) return;
    await readPlan(result.plan_id, signal);
    if (!signal.aborted) { setJob(null); setConsent(false); }
  }
  async function cancelAdjustment(signal: AbortSignal) {
    if (!plan?.adjusted_from) return;
    await readInventory(signal);
    if (signal.aborted) return;
    await readPlan(plan.adjusted_from, signal);
    if (!signal.aborted) setJob(null);
  }
  async function openHistory(identifier: string, signal: AbortSignal) {
    const next = await readPlan(identifier, signal);
    if (next.job_id) {
      const previous = await request<NamingJob>(`/naming/tasks/${next.job_id}`, signal);
      if (isActive(previous.state)) await follow(previous, signal);
      else setJob(previous);
    }
  }
  async function cancel() {
    if (!job || !isActive(job.state) || job.phase === 'archiving' || cancelling) return;
    const controller = new AbortController(); cancelRequest.current = controller; setCancelling(true);
    try { await cancelTask('naming', job.id, controller.signal); }
    catch (reason) { if (!controller.signal.aborted) { setCancelling(false); setError(reason instanceof Error ? reason.message : '取消请求未完成。'); } }
    finally { if (cancelRequest.current === controller) cancelRequest.current = null; }
  }
  const displayEntries = plan?.entries || inventory?.entries || [];
  const resultRows = plan?.state === 'applied' ? preview?.rows || rows : rows;
  return <dialog ref={dialog} className="subtitle-naming-dialog" aria-labelledby="subtitle-naming-title" aria-busy={working} onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="subtitle-naming-heading"><div><h2 id="subtitle-naming-title">字幕层级命名</h2><p translate="no" title={inventory?.title}>{inventory?.title || '正在读取课程…'}</p></div>
      <button type="button" onClick={onClose} aria-label="关闭字幕层级命名">关闭</button></header>
    {inventory && <>
      {!plan && <details className="naming-scope" open><summary>选择本次命名分集：{selected.length} / {inventory.max_selected}</summary>
        <ul>{inventory.entries.map(entry => <li key={entry.project_id}><label><input type="checkbox" checked={selected.includes(entry.project_id)} disabled={working || !ready(entry)} onChange={() => toggle(entry.project_id)} />
          <span>{entry.part ? `P${entry.part} · ` : ''}{entry.title}{!entry.files.length ? '（未归档视频）' : !entry.transcript ? '（缺少字幕）' : `（${entry.files.length} 份归档画质）`}</span></label></li>)}</ul></details>}
      {!plan && <section className="naming-reuse" aria-label="复用字幕名称">
        <button type="button" className="primary" disabled={working || !selected.length || selected.length > inventory.max_selected}
          onClick={() => { void perform(async signal => {
            const result = await request<{ plan_id: string }>(`/projects/${projectId}/naming/reuse`, signal, { selected_ids: selected });
            if (signal.aborted) return;
            const next = await readPlan(result.plan_id, signal);
            const final = await request<NamingPreview>(`/naming/plans/${next.id}/preview`, signal, { rows: next.rows });
            if (!signal.aborted) { setPreview(final); setPlan(current => current && { ...current, state: 'validated' }); setConfirm(false); }
          }); }}>复用字幕名生成视频改名预览</button>
      </section>}
      {!plan && <section className="naming-analysis" aria-label="命名分析设置">
        <AgentModelPicker state={models} disabled={working} onManage={button => { onClose(); onOpenSettings(button); }} />
        <label className="naming-consent"><input type="checkbox" checked={consent} disabled={working} onChange={event => setConsent(event.target.checked)} />
          <span>同意本次由所选模型处理课程字幕，可能联网并产生费用；不会自动重试付费请求。</span></label>
        <button type="button" className="primary" disabled={working || !consent || !models.configured || !selected.length || selected.length > inventory.max_selected}
          onClick={() => { setConsent(false); void perform(async signal => follow(await request<NamingJob>(`/projects/${projectId}/naming/plan`, signal, { consent: true, agent: models.selected, selected_ids: selected }), signal)); }}>生成命名建议</button>
      </section>}

    </>}
    {job && isActive(job.state) && <section className="naming-job" aria-label="命名任务状态"><p role="status">{job.message}{job.progress?.total ? ` ${job.progress.done || 0} / ${job.progress.total}` : ''}</p>
      {isActive(job.state) && <><button type="button" disabled={cancelling || job.phase === 'archiving'} onClick={() => { void cancel(); }}>{cancelling ? '已请求取消' : '取消任务'}</button>
        {!pending && <button type="button" onClick={() => { void perform(async signal => follow(await request<NamingJob>(`/naming/tasks/${job.id}`, signal), signal)); }}>重新读取任务</button>}</>}
    </section>}
    {plan && <section className="naming-editor" aria-label="命名建议编辑"><div className="naming-result-heading"><h3>{states[plan.state] || plan.state}</h3>{plan.state === 'applied' && <small>{resultRows.length} 项</small>}</div>
      {plan.last_error && <p className="error-text">{plan.last_error}</p>}
      {rows.length > 0 && (canValidate ? <>
        {plan.adjusted_from && <p className="naming-hint">直接编辑上次结果，不会重新调用模型；修改后需重新验证。</p>}
        <div className={`naming-columns${plan.source === 'subtitle' ? ' is-subtitle' : ''}`} aria-hidden="true"><span>分集</span>{plan.source !== 'subtitle' && <span>层级序号</span>}<span>语义标题</span></div>
        <ul className={`naming-rows${plan.source === 'subtitle' ? ' is-subtitle' : ''}`}>{rows.map(row => {
          const entry = displayEntries.find(item => item.project_id === row.project_id);
          return <li key={row.project_id}><label className="naming-row-choice"><input type="checkbox" checked={selected.includes(row.project_id)} disabled={working || !canValidate} onChange={() => toggle(row.project_id)} />
            <span>{entry?.part ? `P${entry.part}` : '视频'}</span></label>
            {plan.source !== 'subtitle' && <label><span className="sr-only">层级序号</span><input aria-label={`${entry?.part ? `P${entry.part}` : '视频'} 层级序号`} value={row.number} maxLength={60} placeholder={plan.source === 'manual' ? '可留空' : undefined} disabled={working || !canValidate} onChange={event => edit(row.project_id, 'number', event.target.value)} /></label>}
            <label className="naming-row-title"><span className="sr-only">语义标题</span><input aria-label={`${entry?.part ? `P${entry.part}` : '视频'} 语义标题`} value={row.title} maxLength={100} disabled={working || !canValidate || plan.source === 'subtitle'} onChange={event => edit(row.project_id, 'title', event.target.value)} /></label>
            </li>;
        })}</ul>
        <details className="naming-originals"><summary>原文件信息</summary><ul>{displayEntries.map(entry => <li key={entry.project_id}><span>{entry.part ? `P${entry.part}` : '视频'}</span><span translate="no">{entry.files.map(file => file.filename).join('；')}{entry.transcript_filename && ` / ${entry.transcript_filename}`}</span></li>)}</ul></details>
      </> : <ul className="naming-results" aria-label="命名结果">{resultRows.map(row => {
        const entry = displayEntries.find(item => item.project_id === row.project_id);
        const original = plan.state === 'rolled_back';
        const originalTitle = entry?.number && entry.title.startsWith(`${entry.number} `) ? entry.title.slice(entry.number.length + 1) : entry?.title;
        return <li key={row.project_id}><span className="naming-result-part">{entry?.part ? `P${entry.part}` : '视频'}</span><span className="naming-result-number" translate="no">{original ? entry?.number : row.number}</span><span translate="no">{original ? originalTitle : row.title}</span></li>;
      })}</ul>)}
      {canValidate && <div className="naming-actions"><button type="button" disabled={working || selected.length === 0} onClick={() => { void perform(async signal => {
        const result = await request<NamingPreview>(`/naming/plans/${plan.id}/preview`, signal, { rows: rows.filter(row => selected.includes(row.project_id)) });
        if (!signal.aborted) { setPreview(result); setPlan(current => current && { ...current, state: 'validated' }); setConfirm(false); }
      }); }}>验证并预览最终文件名</button>
        {plan.adjusted_from && <button type="button" disabled={working} onClick={() => { void perform(cancelAdjustment); }}>取消调整</button>}</div>}
      {preview && <details key={`${plan.id}:${plan.state}`} className="naming-preview-details" open={canValidate}><summary><span>文件改名明细</span> ({preview.moves.length})</summary><section className="naming-final-preview" aria-label="真实文件改名预览"><h3>真实文件更名清单（{preview.moves.length} 个文件）</h3>
        <ol>{preview.moves.map(move => <li key={`${move.project_id}:${move.resource}`}><code>{move.source}</code><span aria-hidden="true"> → </span><code>{move.target}</code></li>)}</ol>
        {canValidate && <><label className="naming-consent"><input type="checkbox" checked={confirm} disabled={working} onChange={event => setConfirm(event.target.checked)} />
          <span>我已检查以上最终清单，确认修改真实文件名和视频界面标题。请等待其他任务完成，关闭占用视频的外部程序。</span></label>
          <button type="button" className="primary" disabled={working || !confirm || !preview.preview_token} onClick={() => {
            if (!confirm || !preview.preview_token) return;
            onBeforeApply(); setConfirm(false);
            void perform(async signal => follow(await request<NamingJob>(`/naming/plans/${plan.id}/apply`, signal, { confirm: true, preview_token: preview.preview_token }), signal));
          }}>确认执行真实文件改名</button></>}
      </section></details>}
      {plan.state === 'applied' && <button type="button" disabled={working} onClick={() => { void perform(adjustNaming); }}>调整命名</button>}
      {canRestore && <details key={`${plan.id}:${plan.state}:restore`} className="naming-restore" open={plan.state !== 'applied'}><summary>撤销这次命名</summary><label className="naming-consent"><input type="checkbox" checked={restoreConfirm} disabled={working} onChange={event => setRestoreConfirm(event.target.checked)} />
        <span>确认恢复这次操作前的真实文件名与界面标题；保留之后新增的 AI 材料、对话、笔记和进度。</span></label>
        <button type="button" disabled={working || !restoreConfirm} onClick={() => { if (!restoreConfirm) return; onBeforeApply(); setRestoreConfirm(false);
          void perform(async signal => follow(await request<NamingJob>(`/naming/plans/${plan.id}/restore`, signal, { confirm: true }), signal)); }}>恢复原命名</button></details>}
      {!working && !canRestore && (!canValidate || !plan.adjusted_from) && <button type="button" onClick={startNew}>开始新的命名建议</button>}
    </section>}
    {error && <p className="error-text" role="alert">{error}</p>}
    {inventory && <>
      {inventory.history.length > 0 && <details className="naming-history"><summary>最近预览与恢复记录</summary><ul>{inventory.history.map(item => <li key={item.id}>
        <button type="button" disabled={working} onClick={() => { void perform(signal => openHistory(item.id, signal)); }}>{states[item.state] || item.state} · {item.created_at?.slice(0, 16).replace('T', ' ')}</button>
      </li>)}</ul></details>}
    </>}
    <details className="naming-help"><summary>使用说明</summary>
    <p className="naming-hint">真实文件名＋视频界面标题。先生成建议、编辑、验证清单，再明确确认执行；不会拆分视频或自动搬迁目录。</p>
      {inventory && <p>全系列已登记字幕 {inventory.subtitle_count} 讲，可改名 {inventory.ready_count} 讲。B站按同一 BV 号分组，其他平台仅当前项目；未归档视频或无字幕分集不会自动下载、猜名或改名。</p>}
      <p className="naming-hint">可取消不想改名的分集。多个归档画质保留独立后缀；项目 ID 和逻辑资源标识不变，字幕、AI、对话、笔记和学习进度保持关联。</p>
    <footer className="naming-hint">关闭面板不会取消后台任务；可从任务中心或最近预览继续。执行前会再次校验视频和字幕；文件占用、重名或来源变化会阻止执行，不覆盖原文件。</footer>
      <p className="naming-hint">字幕已有合适名称时，视频直接复用对应字幕的文件名主体，仅保留视频扩展名；不调用 AI，不重复生成标题。先预览，再确认执行。</p>
      <p className="naming-hint">在本地校验并压缩全系列已登记字幕，选段覆盖各集多个位置；不是逐字全文审读。仅发送课程/分集标题和字幕选段，不发送视频、对话或个人笔记。建议仍需你检查。</p>
    </details>
  </dialog>;
}
