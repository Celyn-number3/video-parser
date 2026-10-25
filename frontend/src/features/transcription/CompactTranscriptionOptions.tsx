import { useState, type ReactNode } from 'react';
import type { TranscriptionJob } from '../../lib/api';
import { isActive } from '../../lib/jobs';

type Language = 'auto' | 'zh' | 'en';
export default function CompactTranscriptionOptions({ disabled, ready, busy, error, job, saveControls, saveHint, saveNotice, onStart, onClose }: {
  disabled: boolean; ready?: boolean; busy: boolean; error: string; job: TranscriptionJob | null;
  saveControls: ReactNode; saveHint: string; saveNotice: string; onStart: (language: Language) => Promise<void>; onClose?: () => void;
}) {
  const [language, setLanguage] = useState<Language>('auto');
  const [attempted, setAttempted] = useState(false);
  const status = attempted ? error || (busy || job && isActive(job.state) ? '本次生成正在处理，可到任务中心查看进度。'
    : job?.state === 'completed' ? '本次字幕生成已完成，结果已保留。' : job ? '本次生成未完成，请到任务中心查看原因。' : '')
    : job && isActive(job.state) ? '本视频已有生成任务进行中，可到任务中心查看。' : '';
  return <div className="compact-acquire" role="group" aria-label="本地字幕生成确认">
    <div className="compact-acquire-fields">
      <label>字幕语言<select aria-label="字幕语言" disabled={busy || disabled} value={language} onChange={event => setLanguage(event.target.value as Language)}>
        <option value="auto">自动识别</option><option value="zh">中文</option><option value="en">英文</option>
      </select></label>
      <div className="compact-save-field"><label htmlFor="save-destination">保存到</label><div className="save-controls">{saveControls}</div></div>
    </div>
    {saveHint && <p className="subtitle-note compact-save-hint">保存位置：{saveHint}</p>}
    {saveNotice && <p className="notice" role="status">{saveNotice}</p>}
    {ready === false && <p className="error-text" role="alert">本机转写组件尚未就绪，请检查设置。</p>}
    <div className="compact-acquire-actions">
      <button type="button" className="primary" disabled={disabled || ready === false || busy} onClick={() => { setAttempted(true); void onStart(language); }}>确认生成字幕</button>
      {onClose && <button type="button" onClick={onClose}>{attempted ? '关闭' : '取消'}</button>}
      <a href="?page=tasks">查看任务中心</a>
    </div>
    {status && <p className={attempted && error ? 'error-text' : 'subtitle-note'} role={attempted && error ? 'alert' : 'status'}>{status}</p>}
  </div>;
}
