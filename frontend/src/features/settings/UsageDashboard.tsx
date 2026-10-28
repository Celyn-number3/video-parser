import { useEffect, useState } from 'react';
import { request } from '../../lib/api';
import type { UsageReport } from '../../lib/api';
import './usage-dashboard.css';

const WINDOWS: [number, string][] = [[7, '近 7 天'], [30, '近 30 天'], [90, '近 90 天'], [0, '全部时间']];
const number = (value: number) => (Number.isFinite(value) ? value.toLocaleString('zh-CN') : '0');
const money = (value: number | null) => value === null ? '费用未知'
  : `¥${value > 0 && value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;

export default function UsageDashboard({ visible }: { visible: boolean }) {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState<UsageReport | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    setBusy(true); setError('');
    request<UsageReport>(`/usage?days=${days}`, controller.signal)
      .then(data => { if (!controller.signal.aborted) setReport(data); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取用量失败。'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [visible, days, reload]);
  const totals = report?.totals;
  const peak = Math.max(1, ...(report?.by_day.map(day => day.total_tokens) || [0]));
  return <div className="usage-dashboard">
    <div className="usage-toolbar">
      <div className="usage-windows" role="group" aria-label="统计范围">{WINDOWS.map(([value, label]) =>
        <button key={value} type="button" aria-pressed={days === value} disabled={busy} onClick={() => setDays(value)}>{label}</button>)}</div>
      <button type="button" className="usage-refresh" disabled={busy} onClick={() => setReload(value => value + 1)}>{busy ? '正在读取用量…' : '重新读取'}</button>
    </div>
    {error && <p className="error-text" role="alert">{error}</p>}
    {!report && !error && <p className="settings-hint">正在读取用量…</p>}
    {report && totals && <>
      <dl className="usage-totals">
        <div><dt>调用次数</dt><dd>{number(totals.calls)}</dd></div>
        <div><dt>输入 tokens</dt><dd>{number(totals.prompt_tokens)}</dd></div>
        <div><dt>输出 tokens</dt><dd>{number(totals.completion_tokens)}</dd></div>
        <div><dt>估算费用</dt><dd>{money(totals.cost)}</dd></div>
        <div><dt>涉及项目</dt><dd>{number(totals.projects)}</dd></div>
      </dl>
      {!totals.calls && <p className="settings-hint">暂无用量记录。完成一次 AI 分析、追问或对话后会在这里汇总。</p>}
      {totals.calls > 0 && <>
        {report.by_day.length > 0 && <section className="usage-block" aria-labelledby="usage-daily">
          <h4 id="usage-daily">按天</h4>
          <div className="usage-chart" role="img" aria-label={`最近 ${report.by_day.length} 天的 token 用量`}>
            {report.by_day.map(day => <div key={day.date} className="usage-bar" title={`${day.date} · ${number(day.total_tokens)} tokens`}>
              <span style={{ height: `${Math.max(day.total_tokens ? 4 : 1, Math.round(day.total_tokens / peak * 100))}%` }} />
            </div>)}
          </div>
          <div className="usage-chart-axis"><span>{report.by_day[0].date.slice(5)}</span><span>{report.by_day.at(-1)?.date.slice(5)}</span></div>
        </section>}
        <div className="usage-tables">
          <section className="usage-block" aria-labelledby="usage-kinds"><h4 id="usage-kinds">按用途</h4>
            <table className="usage-table"><thead><tr><th scope="col">用途</th><th scope="col">调用</th><th scope="col">tokens</th><th scope="col">费用</th></tr></thead>
              <tbody>{report.by_kind.map(row => <tr key={row.kind}><th scope="row">{row.label}</th><td>{number(row.calls)}</td><td>{number(row.total_tokens)}</td><td>{money(row.cost)}</td></tr>)}</tbody>
            </table></section>
          <section className="usage-block" aria-labelledby="usage-models"><h4 id="usage-models">按模型</h4>
            <table className="usage-table"><thead><tr><th scope="col">模型</th><th scope="col">调用</th><th scope="col">tokens</th><th scope="col">费用</th></tr></thead>
              <tbody>{report.by_model.map(row => <tr key={row.model}><th scope="row">{row.model}</th><td>{number(row.calls)}</td><td>{number(row.total_tokens)}</td><td>{money(row.cost)}</td></tr>)}</tbody>
            </table></section>
        </div>
        {report.by_project.length > 0 && <section className="usage-block" aria-labelledby="usage-projects"><h4 id="usage-projects">按项目</h4>
          <table className="usage-table"><thead><tr><th scope="col">项目</th><th scope="col">调用</th><th scope="col">输入</th><th scope="col">输出</th><th scope="col">费用</th></tr></thead>
            <tbody>{report.by_project.map(row => <tr key={row.id}><th scope="row">{row.title}</th><td>{number(row.calls)}</td><td>{number(row.prompt_tokens)}</td><td>{number(row.completion_tokens)}</td><td>{money(row.cost)}</td></tr>)}</tbody>
          </table></section>}
        <p className="settings-hint">费用按当前单价估算，历史调用的实际账单以服务商为准。{report.totals.native_calls > 0 ? ' 本机 agent 的调用不按 token 计费，费用记作 0。' : ''}</p>
        {!report.prices.configured && totals.cost === null && <p className="settings-hint">尚未填写输入／输出单价，只能统计 token，无法估算费用。</p>}
        <p className="settings-hint">{report.coverage}</p>
      </>}
    </>}
  </div>;
}
