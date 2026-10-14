import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { AISettings, AnalysisBody, AnalysisContext, AnalysisFrame, AnalysisRecord, AnalysisSource, Configuration, Media, ParsedVideo } from '../../lib/api';
import { phases } from '../../lib/jobs';
import type { TaskInfo } from '../../lib/jobs';
import Icon from '../../components/Icon';
import Panel, { PanelTitle } from '../../components/Panel';
import Markdown from '../../components/Markdown';
import './analysis.css';

type Props = {
  parsed: ParsedVideo | null; media: Media | null; qualityId: string; config: Configuration | null;
  busy: 'prepare' | 'analyze' | null; status: string; error: boolean; task?: TaskInfo;
  version: number; lastRecord?: string; cancelDisabled: boolean;
  onCancel: () => void; onAnalyze: (body: AnalysisBody) => void; onArchiveAndAnalyze: (body: AnalysisBody) => void;
  onAsk: (recordId: string, question: string) => void; onSeek?: (seconds: number) => void;
  onOpenSettings: (button: HTMLButtonElement) => void; onGenerateSubtitles: () => void;
};
type Preview = { token: string; frames: (AnalysisFrame & { name: string })[] };

const SOURCES: [AnalysisSource, string][] = [['both', '字幕 + 画面'], ['transcript', '只用字幕'], ['frames', '只用画面']];
const COUNTS = [4, 6, 8, 12, 16];
const PLACEHOLDERS: Record<string, string> = {
  custom: '写下你想让模型做什么，例如：列出视频里出现的所有产品和价格',
  notes: '选填，例如：只整理和特征值有关的部分',
  breakdown: '选填，例如：重点分析前 10 秒',
};
const autoCount = (duration: number) => Math.max(4, Math.min(16, Math.round(4 + duration / 60)));
const tokens = (value: number) => value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString('zh-CN');
function when(iso: string | null) {
  if (!iso) return '时间未知';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '时间未知';
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function hostOf(url: string) { try { return new URL(url).host; } catch { return url; } }

export default function AnalysisPanel(props: Props) {
  const { parsed, media, qualityId, config, busy, status, error, task, version, lastRecord, onSeek } = props;
  const projectId = parsed?.project.id || '';
  const resource = media?.resource || '';
  const [context, setContext] = useState<AnalysisContext | null>(null);
  const [loadError, setLoadError] = useState('');
  const [records, setRecords] = useState<AnalysisRecord[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [template, setTemplate] = useState('summary');
  const [source, setSource] = useState<AnalysisSource>('both');
  const [transcript, setTranscript] = useState('');
  const [frameMode, setFrameMode] = useState<'scene' | 'uniform'>('scene');
  const [count, setCount] = useState(0);
  const [prompt, setPrompt] = useState('');
  const [consent, setConsent] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [kept, setKept] = useState<Set<string>>(new Set());
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [question, setQuestion] = useState('');
  const [notice, setNotice] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const previewRequest = useRef<AbortController | null>(null);
  const shown = useRef({ project: '', version: 0 });
  // Model settings: from the latest context load, or from the settings dialog when it saves.
  const [ai, setAI] = useState<AISettings | null>(null);
  useEffect(() => { if (context?.ai) setAI(context.ai); }, [context]);
  useEffect(() => { if (config?.ai) setAI(config.ai); }, [config?.ai]);

  useEffect(() => {
    setConsent(false); setQuestion(''); setNotice(''); setConfirmDelete(false);
    if (!projectId) { setContext(null); setRecords([]); setActive(null); return; }
    const controller = new AbortController();
    setLoadError('');
    Promise.all([
      request<AnalysisContext>(`/projects/${projectId}/analysis/context?resource=${encodeURIComponent(resource)}`, controller.signal),
      request<{ records: AnalysisRecord[] }>(`/projects/${projectId}/analyses`, controller.signal),
    ]).then(([nextContext, list]) => {
      setContext(nextContext);
      setRecords(list.records);
      // A just-finished analysis or follow-up: bring the result into view.
      if (shown.current.project === projectId && version > shown.current.version && lastRecord) requestAnimationFrame(() => document.querySelector('.analysis-records')?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
      shown.current = { project: projectId, version };
      setActive(current => lastRecord && list.records.some(item => item.id === lastRecord) ? lastRecord
        : current && list.records.some(item => item.id === current) ? current : list.records[0]?.id || null);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setLoadError(reason instanceof Error ? reason.message : '无法读取分析信息。'); });
    return () => controller.abort();
  }, [projectId, resource, version, lastRecord]);
  // New frames are needed whenever the video or the way frames are picked changes.
  useEffect(() => { previewRequest.current?.abort(); setPreview(null); setKept(new Set()); setPreviewError(''); setPreviewing(false); }, [projectId, resource, frameMode, count]);
  useEffect(() => () => previewRequest.current?.abort(), []);
  useEffect(() => { setConfirmDelete(false); setNotice(''); }, [active]);

  const configured = ai ? ai.configured : !!config?.ai_configured;
  const needsConsent = !!ai && !ai.consented;
  const templates = context?.templates || [];
  const spec = templates.find(item => item.id === template);
  const transcripts = context?.transcripts || [];
  const chosen = transcripts.find(item => item.resource === transcript) || transcripts[0];
  const effective: AnalysisSource = source === 'both' && !transcripts.length ? 'frames' : source;
  const usesTranscript = effective !== 'frames';
  const usesFrames = effective !== 'transcript';
  const duration = context?.duration || media?.duration || parsed?.duration || 0;
  const automatic = autoCount(duration);
  const frameTotal = usesFrames ? (preview ? kept.size : count || automatic) : 0;
  const running = busy === 'analyze';
  const working = busy !== null;
  const record = records.find(item => item.id === active) || null;

  const inputTokens = (context?.prompt_tokens || 700) + (usesTranscript && chosen ? chosen.tokens : 0) + frameTotal * (context?.image_tokens || 800) + Math.ceil(prompt.length * 0.7);
  const outputTokens = context?.output_tokens || 1500;
  const cost = ai && ai.price_input !== null ? inputTokens / 1e6 * ai.price_input + outputTokens / 1e6 * (ai.price_output ?? ai.price_input) : null;

  const missingTranscript = !transcripts.length && (source === 'transcript' || spec?.requires === 'transcript');
  const blocker = !parsed ? '先解析链接并选择视频。'
    : !context ? (loadError || '正在读取分析信息…')
    : missingTranscript ? '这个视频还没有字幕，先生成字幕再分析。'
    : template === 'custom' && !prompt.trim() ? '自定义分析需要写下分析要求。'
    : usesFrames && preview && !kept.size ? '至少保留一张画面。'
    : !configured ? '尚未配置 AI 模型。'
    : needsConsent && !consent ? '请先勾选同意发送。' : '';

  function chooseTemplate(id: string) {
    setTemplate(id);
    const next = templates.find(item => item.id === id);
    if (next) setSource(next.source);
  }
  function body(): AnalysisBody {
    return {
      template, source: effective, transcript_resource: usesTranscript ? chosen?.resource || null : null, frame_mode: frameMode,
      count: usesFrames ? count : 0, preview_token: usesFrames && preview ? preview.token : null,
      frames: usesFrames && preview ? preview.frames.filter(frame => kept.has(frame.name)).map(frame => frame.name) : null, prompt: prompt.trim(),
    };
  }
  async function loadPreview() {
    if (!parsed || !media || previewing) return;
    previewRequest.current?.abort();
    const controller = new AbortController(); previewRequest.current = controller;
    setPreviewing(true); setPreviewError('');
    try {
      const result = await request<Preview>(`/videos/${parsed.id}/analysis/frames`, controller.signal, { quality_id: qualityId, mode: frameMode, count });
      if (controller.signal.aborted) return;
      setPreview(result); setKept(new Set(result.frames.map(frame => frame.name)));
    } catch (reason) {
      if (!controller.signal.aborted) setPreviewError(reason instanceof Error ? reason.message : '截取画面失败。');
    } finally { if (previewRequest.current === controller) { previewRequest.current = null; setPreviewing(false); } }
  }
  function toggleFrame(name: string) {
    setKept(current => { const next = new Set(current); if (next.has(name)) next.delete(name); else next.add(name); return next; });
  }
  async function copyRecord() {
    if (!record) return;
    const text = [record.text.trim(), ...record.followups.map(item => `## 追问：${item.question}\n\n${item.answer.trim()}`)].join('\n\n');
    try { await navigator.clipboard.writeText(text); setNotice('已复制到剪贴板。'); }
    catch {
      const area = document.createElement('textarea'); area.value = text; area.setAttribute('readonly', ''); area.style.position = 'fixed'; area.style.opacity = '0';
      document.body.append(area); area.select();
      const copied = document.execCommand('copy'); area.remove();
      setNotice(copied ? '已复制到剪贴板。' : '浏览器不允许复制，请导出 Markdown。');
    }
  }
  async function deleteRecord() {
    if (!record || !projectId) return;
    try {
      const result = await request<{ records: AnalysisRecord[] }>(`/projects/${projectId}/analyses/${record.id}/delete`, new AbortController().signal, { confirm: true });
      setRecords(result.records); setActive(result.records[0]?.id || null);
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '删除失败，请重试。'); setConfirmDelete(false); }
  }
  function submitQuestion() {
    if (!record || !question.trim() || working || !configured || (needsConsent && !consent)) return;
    props.onAsk(record.id, question.trim()); setQuestion('');
  }

  const estimate = !parsed || !context ? '' : `预计发送约 ${tokens(inputTokens)} tokens`
    + `（${[usesTranscript && chosen ? `字幕约 ${tokens(chosen.tokens)}` : '', usesFrames ? `画面 ${frameTotal} 张` : ''].filter(Boolean).join(' · ')}），输出约 ${tokens(outputTokens)}`;
  const price = !ai ? '' : ai.local ? '本机模型，不产生调用费用。' : cost !== null ? `按设置的单价约 ¥${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}。` : '未填写单价，无法估算费用（可在设置 → AI 模型填写）。';
  const phase = task?.phase && phases[task.phase] ? phases[task.phase] + ' · ' : '';

  if (!parsed) return <Panel className="analysis-form"><PanelTitle>AI 分析</PanelTitle><p className="analysis-empty">先解析视频链接，再用字幕和画面让模型总结、做笔记或拆解。</p></Panel>;

  return <>
    <Panel className="analysis-form" aria-labelledby="analysis-title">
      <PanelTitle id="analysis-title">AI 分析</PanelTitle>
      {!configured && <p className="notice analysis-setup" role="note">尚未配置 AI 模型，填写密钥后无需重启。
        <button type="button" className="link-button" onClick={event => props.onOpenSettings(event.currentTarget)}>打开设置</button></p>}

      <div className="analysis-block">
        <span className="analysis-label" id="analysis-template-label">分析模板</span>
        <div className="analysis-templates" role="group" aria-labelledby="analysis-template-label">
          {templates.map(item => <button key={item.id} type="button" className="chip" aria-pressed={template === item.id} disabled={running} onClick={() => chooseTemplate(item.id)}>{item.name}</button>)}
        </div>
        {spec && <p className="analysis-hint">{spec.description}</p>}
      </div>

      <fieldset className="analysis-block analysis-source" disabled={running}>
        <legend className="analysis-label">分析依据</legend>
        <div className="analysis-segment">
          {SOURCES.map(([value, label]) => <label key={value} className={source === value ? 'checked' : ''}>
            <input type="radio" name="analysis-source" value={value} checked={source === value}
              disabled={(value === 'frames' && spec?.requires === 'transcript') || (value === 'transcript' && spec?.requires === 'frames')}
              onChange={() => setSource(value)} />{label}</label>)}
        </div>
        {usesTranscript && transcripts.length > 1 && <label className="analysis-inline">
          <span>字幕</span>
          <select value={chosen?.resource || ''} onChange={event => setTranscript(event.target.value)} aria-label="使用哪份字幕">
            {transcripts.map(item => <option key={item.resource} value={item.resource}>{item.label} · {item.cues} 条 · 到 {item.end}</option>)}
          </select>
        </label>}
        {usesTranscript && transcripts.length === 1 && chosen && <p className="analysis-hint">使用{chosen.label}：{chosen.cues} 条，到 {chosen.end}{chosen.merged ? '（较长，会按时间段合并）' : ''}。</p>}
        {!transcripts.length && context && source !== 'frames' && <p className={'analysis-hint' + (missingTranscript ? ' analysis-warning' : '')}>
          {missingTranscript ? '这个视频还没有字幕。' : '这个视频还没有字幕，这次只会用画面分析。'}
          <button type="button" className="link-button" onClick={props.onGenerateSubtitles}>先生成字幕</button></p>}
      </fieldset>

      {usesFrames && <div className="analysis-block">
        <span className="analysis-label">画面</span>
        <div className="analysis-frame-controls">
          <select aria-label="选取画面的方式" value={frameMode} disabled={running} onChange={event => setFrameMode(event.target.value as 'scene' | 'uniform')}>
            <option value="scene">按镜头切换选取</option><option value="uniform">按时间平均选取</option>
          </select>
          <select aria-label="画面数量" value={count} disabled={running} onChange={event => setCount(Number(event.target.value))}>
            <option value={0}>自动（{automatic} 张）</option>{COUNTS.map(value => <option key={value} value={value}>{value} 张</option>)}
          </select>
          {media ? <button type="button" disabled={previewing || running} aria-busy={previewing} onClick={() => { void loadPreview(); }}>
            {previewing ? <><Icon name="loader-circle" className="spinner" />截取中…</> : <><Icon name="image" />{preview ? '重新截取' : '预览画面'}</>}
          </button> : <span className="analysis-hint">归档后可以先预览画面、去掉不要的。</span>}
        </div>
        {previewError && <p className="error-text" role="alert">{previewError}</p>}
        {preview && <>
          <p className="analysis-hint">点击画面可以取消选择，已选 {kept.size} / {preview.frames.length} 张。</p>
          <ul className="analysis-frames analysis-picker" aria-label="预览画面">
            {preview.frames.map(frame => <li key={frame.name}><button type="button" aria-pressed={kept.has(frame.name)} disabled={running} onClick={() => toggleFrame(frame.name)}
              aria-label={`画面 ${frame.label}${kept.has(frame.name) ? '（已选）' : '（未选）'}`}>
              <img src={frame.url} alt="" /><span>{frame.label}</span></button></li>)}
          </ul>
        </>}
      </div>}

      <div className="analysis-block">
        <label className="analysis-label" htmlFor="prompt">{template === 'custom' ? '分析要求' : <>补充要求 <span className="optional">（选填）</span></>}</label>
        <textarea id="prompt" disabled={running} value={prompt} maxLength={4000} rows={2} placeholder={PLACEHOLDERS[template] || '选填，例如：用英文输出 / 重点关注配色'} onChange={event => setPrompt(event.target.value)} />
      </div>

      {estimate && <p className="analysis-estimate">{estimate}。{price}</p>}
      {configured && needsConsent && ai && <label className="consent">
        <input type="checkbox" disabled={running} checked={consent} onChange={event => setConsent(event.target.checked)} />
        <span>同意把{usesTranscript && usesFrames ? '字幕和画面' : usesTranscript ? '字幕' : '画面'}发送到 {ai.provider_name}（{hostOf(ai.base_url)}），可能产生费用，发送后无法撤销。同意一次后，对这个服务不再询问。</span>
      </label>}
      <div className="analysis-actions">
        <button className="primary operation-button" type="button" aria-busy={running || busy === 'prepare'} disabled={!!blocker || working}
          onClick={() => media ? props.onAnalyze(body()) : props.onArchiveAndAnalyze(body())}>
          {working ? <><Icon name="loader-circle" className="spinner" />{busy === 'prepare' ? '归档中…' : '分析中…'}</>
            : <><Icon name={media ? 'scan-eye' : 'download'} />{media ? '开始分析' : '归档并分析'}</>}
        </button>
        {running && <button type="button" disabled={props.cancelDisabled} onClick={props.onCancel}>取消分析</button>}
        {!working && blocker && parsed && context && <span className="analysis-hint">{blocker}</span>}
      </div>
      {(working || (error && status)) && <p className={error ? 'error-text' : 'analysis-status'} role="status" aria-live="polite">{working ? phase : ''}{status}</p>}
    </Panel>

    {records.length > 0 && <Panel className="analysis-records" aria-labelledby="analysis-records-title">
      <div className="analysis-record-bar">
        <PanelTitle id="analysis-records-title">分析记录</PanelTitle>
        <select aria-label="选择分析记录" value={active || ''} onChange={event => setActive(event.target.value)}>
          {records.map(item => <option key={item.id} value={item.id}>{item.template_name} · {when(item.created_at)}{item.followups.length ? ` · 追问 ${item.followups.length}` : ''}</option>)}
        </select>
      </div>
      {record && <article className="analysis-record" aria-label={`${record.template_name}结果`}>
        <p className="analysis-meta">{[record.source_label + (record.transcript_label ? `（${record.transcript_label}）` : ''), record.frame_count ? `${record.frame_count} 张画面` : '',
          record.model, record.usage.prompt_tokens ? `用量 ${tokens(record.usage.prompt_tokens)} + ${tokens(record.usage.completion_tokens || 0)} tokens` : ''].filter(Boolean).join(' · ')}</p>
        {record.prompt && <p className="analysis-meta">要求：{record.prompt}</p>}
        <div className="analysis-record-actions">
          <button type="button" onClick={() => { void copyRecord(); }}><Icon name="copy" />复制</button>
          <a className="button" href={`/api/workspace/projects/${projectId}/analyses/${record.id}/export?format=md`} download><Icon name="file-down" />导出 Markdown</a>
          <a className="button" href={`/api/workspace/projects/${projectId}/analyses/${record.id}/export?format=docx`} download><Icon name="file-down" />导出 Word</a>
          {confirmDelete ? <span className="analysis-confirm">删除这条记录和它的画面？
            <button type="button" disabled={working} onClick={() => { void deleteRecord(); }}>删除</button><button type="button" onClick={() => setConfirmDelete(false)}>取消</button></span>
            : <button type="button" className="analysis-delete" disabled={working} onClick={() => setConfirmDelete(true)}><Icon name="trash-2" />删除</button>}
        </div>
        {notice && <p className="analysis-hint" role="status">{notice}</p>}
        {record.frames.length > 0 && <ul className="analysis-frames" aria-label="这次分析用到的画面">
          {record.frames.map(frame => <li key={frame.url}><button type="button" disabled={!onSeek} title={onSeek ? `跳到 ${frame.label}` : '归档视频后可跳转'} onClick={() => onSeek?.(frame.time)}>
            <img src={frame.url} alt={`画面 ${frame.label}`} loading="lazy" /><span>{frame.label}</span></button></li>)}
        </ul>}
        <Markdown text={record.text} onSeek={onSeek} maxSeconds={duration} className="analysis-markdown" />
        {record.followups.map(item => <section className="analysis-followup" key={item.id} aria-label={'追问：' + item.question}>
          <p className="analysis-question"><span>追问</span>{item.question}</p>
          <Markdown text={item.answer} onSeek={onSeek} maxSeconds={duration} className="analysis-markdown" />
        </section>)}
        <form className="analysis-ask" onSubmit={event => { event.preventDefault(); submitQuestion(); }}>
          <label htmlFor="analysis-question" className="sr-only">追问这次分析</label>
          <textarea id="analysis-question" rows={2} maxLength={2000} value={question} disabled={working} placeholder="接着问，例如：第二部分再展开讲讲"
            onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); submitQuestion(); } }} />
          <button type="submit" disabled={!question.trim() || working || !configured || (needsConsent && !consent)} aria-busy={running}>
            <Icon name={running ? 'loader-circle' : 'send'} className={running ? 'spinner' : ''} />追问</button>
        </form>
        <p className="analysis-hint">追问会带上这次的字幕、画面和之前的问答一起发送。{needsConsent ? '需要先在上方勾选同意发送。' : ''}</p>
      </article>}
    </Panel>}
  </>;
}
