import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { Configuration, TranscriptionJob } from '../../lib/api';
import { cancelTask, isActive, pollJob } from '../../lib/jobs';
import SavedLocation from './SavedLocation';
import AgentModelPicker from '../learning/AgentModelPicker';
import useAgentModels from '../learning/useAgentModels';

type Source = { job_id: string } | { project_id: string; resource: string; video_resource?: string };
// restoredJob: a translation of this video restored after a reload / from the task center, shown here
// (where it belongs) instead of in the transcription result area.
type Props = { source: Source; text: string; language?: string; config?: Configuration | null; label?: string; textId?: string; rows?: number; restoredJob?: TranscriptionJob | null; onOpenSettings?: (button: HTMLButtonElement) => void };
export default function SubtitleTranslation({ source, text, language, config, label, textId, rows = 8, restoredJob, onOpenSettings }: Props) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<'zh' | 'en'>(() => language === 'en' ? 'zh' : language === 'zh' ? 'en' : (text.match(/[\u3400-\u9fff]/g)?.length || 0) > (text.match(/[a-zA-Z]/g)?.length || 0) / 3 ? 'en' : 'zh');
  const [consent, setConsent] = useState(false);
  const [outputConfirmed, setOutputConfirmed] = useState(false);
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const models = useAgentModels(config?.ai || null, !!config?.ai_configured);
  // A new run replaces the restored result instead of showing it while the request is pending.
  const [freshRun, setFreshRun] = useState(false);
  const current = job || (freshRun ? null : restoredJob) || null;
  const working = pending || isActive(current?.state);
  const local = !models.native && config?.ai?.provider === 'llamacpp';
  useEffect(() => { setConsent(false); }, [models.key, target]);
  useEffect(() => { setOutputConfirmed(false); }, [models.key]);
  useEffect(() => () => active.current?.abort(), []);
  async function start() {
    if (active.current || !consent || !models.configured) return;
    const controller = new AbortController(); active.current = controller;
    setPending(true); setError(''); setConsent(false); setJob(null); setFreshRun(true);
    try {
      const result = await request<TranscriptionJob>('/translations', controller.signal, { ...source, target, consent: true, agent: models.selected, output_confirmed: !local && outputConfirmed });
      if (controller.signal.aborted) return;
      setJob(result);
      if (isActive(result.state)) await pollJob<TranscriptionJob>('/transcriptions/' + result.id, controller.signal, value => setJob(value));
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '翻译未完成，原字幕保留。'); }
    finally { if (active.current === controller) { active.current = null; if (!controller.signal.aborted) setPending(false); } }
  }
  return <section className="subtitle-translation" aria-label="AI 中英互译">
    <div className="translation-heading">
      {label && <label htmlFor={textId}>{label}</label>}
      <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>AI 中英互译</button>
    </div>
    {label && <textarea id={textId} aria-label={label} readOnly rows={rows} value={text} />}
    {open && <>
      <div className="translation-controls"><label>翻译方向<select aria-label="翻译方向" value={target} disabled={working} onChange={event => setTarget(event.target.value as 'zh' | 'en')}>
        <option value="zh">英文 → 中文</option><option value="en">中文 → 英文</option>
      </select></label></div>
      <AgentModelPicker state={models} disabled={working} onManage={button => { if (onOpenSettings) onOpenSettings(button); else setError('请在设置中配置 AI 模型。'); }} />
      <p className="subtitle-note">翻译仅发送当前字幕文字，不发送音视频。长字幕会分批请求，可能产生多次费用；失败不自动重试。原字幕保留，时间戳不变，译文单独保存。</p>
      {local ? <p className="subtitle-note">本机模型按启动配置的上下文和单次回复上限自动分批。</p>
        : <label className="naming-consent"><input type="checkbox" checked={outputConfirmed} disabled={working} onChange={event => setOutputConfirmed(event.target.checked)} />
          <span>我已确认所选模型及接入端单次输出不少于 32K tokens，启用云端大批次（每批最多 20,000 字符／300 条）。不勾选则按兼容档（2,200 字符／24 条）分批。</span></label>}
      <label className="naming-consent"><input type="checkbox" checked={consent} disabled={working} onChange={event => setConsent(event.target.checked)} />
        <span>同意本次由所选 AI 模型翻译字幕，可能联网并产生费用。</span></label>
      <div className="translation-controls"><button type="button" className="primary" disabled={working || !consent || !models.configured} onClick={() => { void start(); }}>开始 AI 翻译</button>
        {current && isActive(current.state) && <button type="button" onClick={() => { void cancelTask('transcriptions', current.id, new AbortController().signal).catch(() => setError('取消请求未完成，请在任务中心检查。')); }}>取消翻译</button>}</div>
    </>}
    {/* Status and result stay visible when the settings above are folded. */}
    {/* Progress or failure only: a finished translation speaks for itself (译文 + where it was saved). */}
    {current && current.state !== 'completed' && <p className="translation-status" role="status">{current.message}</p>}
    {error && <p role="alert" className="error-text">{error}</p>}
    {current?.state === 'completed' && <div className="translation-result"><label>译文<textarea aria-label="译文" readOnly rows={8} value={current.text} /></label>
      {current.saved_to?.location && <SavedLocation label="译文已保存到" location={current.saved_to.location} openPath={`/transcriptions/${current.id}/open`} />}</div>}
    {working && <p className="subtitle-note">切换视频或离开页面不会取消后台翻译，可在任务中心继续查看。</p>}
  </section>;
}
