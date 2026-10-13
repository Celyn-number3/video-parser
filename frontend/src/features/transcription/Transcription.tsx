import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import { isActive, pollJob, remember, remembered, cancelTask } from '../../lib/jobs';
import type { Media, TranscriptionJob } from '../../lib/api';
import { saveFiles } from '../../lib/download';
import Icon from '../../components/Icon';

export default function Transcription({ projectId, media, ready, uploadLimit }: {
  projectId?: string; media: Media | null; ready?: boolean; uploadLimit?: number;
}) {
  const [mode, setMode] = useState('upload');
  const [language, setLanguage] = useState('auto');
  const [batchFiles,setBatchFiles]=useState<File[]>([]);
  const [reuseModel,setReuseModel]=useState(false);
  const [batchNotice,setBatchNotice]=useState('');
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const lastId = useRef<string | null>(null);
  const limit = uploadLimit ?? 512 * 1024 * 1024;
  const running = isActive(job?.state);

  useEffect(() => {
    function resume(identifier: string) {
      active.current?.abort();
      const controller=new AbortController();active.current=controller;lastId.current=identifier;
      remember('transcriptions',identifier);setBusy(true);setError('');void poll(identifier,controller);
    }
    const previous=remembered('transcriptions');if (previous) resume(previous);
    const listener=(event: Event) => { const detail=(event as CustomEvent<{kind:string;id:string}>).detail;if (detail?.kind==='transcriptions') resume(detail.id); };
    window.addEventListener('video-parser:restore-task',listener);
    return () => { active.current?.abort();window.removeEventListener('video-parser:restore-task',listener); };
  }, []);

  async function poll(identifier: string, controller: AbortController) {
    try {
      await pollJob<TranscriptionJob>('/transcriptions/'+identifier,controller.signal,setJob);
      if (!controller.signal.aborted) { active.current=null;setBusy(false); }
    } catch (reason) {
      if (controller.signal.aborted) return;
      active.current=null;setBusy(false);setError(reason instanceof Error ? reason.message : '无法读取任务状态，请重试连接。');
    }
  }

  async function start() {
    if (active.current) return;
    if (mode === 'upload' && (!file || !file.size || file.size > limit)) {
      setError('请选择非空音视频文件，大小不能超过 ' + Math.round(limit / 1024 / 1024) + ' MB。');
      return;
    }
    if (mode === 'video' && (!projectId || !media)) return;
    const controller = new AbortController();
    active.current = controller;
    lastId.current = null;
    setBusy(true);
    setError('');
    setJob(null);
    try {
      if (mode==='upload' && batchFiles.length>1) {
        const submitted:TranscriptionJob[]=[];const rejected:string[]=[];
        for (const item of batchFiles.slice(0,32)) {
          if (controller.signal.aborted) return;
          try {
            if (!item.size || item.size>limit) throw new Error('大小不符合要求');
            const next=await request<TranscriptionJob>('/transcriptions/upload?'+new URLSearchParams({filename:item.name,language,reuse_model:String(reuseModel)}),controller.signal,item);submitted.push(next);
          } catch (reason) { if (controller.signal.aborted) return;rejected.push(item.name+': '+String(reason)); }
        }
        setBatchNotice(`批量提交 ${submitted.length} 个任务；失败 ${rejected.length} 个。所有任务和结果可在任务中心查看。`+(rejected.length?' '+rejected.join('；'):''));
        const last=submitted.at(-1);
        if (last) { lastId.current=last.id;remember('transcriptions',last.id);setJob(last);await poll(last.id,controller); }
        else { active.current=null;setBusy(false); }
        return;
      }
      const path = mode === 'upload'
        ? '/transcriptions/upload?' + new URLSearchParams({ filename: file!.name, language, reuse_model:String(reuseModel) })
        : '/transcriptions';
      const body = mode === 'upload' ? file! : { project_id: projectId, resource: media!.resource, language, reuse_model:reuseModel };
      const result = await request<TranscriptionJob>(path, controller.signal, body);
      if (controller.signal.aborted) return;
      lastId.current = result.id;remember('transcriptions',result.id);
      setJob(result);
      await poll(result.id, controller);
    } catch (reason) {
      if (controller.signal.aborted) return;
      active.current = null;
      setBusy(false);
      setError(reason instanceof Error ? reason.message : '无法启动转录任务。');
    }
  }

  function refresh() {
    if (!lastId.current || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setError('');
    setBusy(true);
    void poll(lastId.current, controller);
  }

  return <section className="panel transcription-panel" aria-labelledby="transcription-heading">
    <h2 id="transcription-heading">音频转文字</h2>
    <p className="notice">音频不会发送到云端。</p>
    {ready === false && <p className="error-text" role="alert">未找到项目内 Whisper 环境或模型，请运行 scripts/setup-local-tools.ps1 -DownloadModel 后重启后端。</p>}
    <div className="subtitle-controls">
      <div><label htmlFor="transcription-source">转录来源</label>
        <select id="transcription-source" value={mode} disabled={busy || running} onChange={event => setMode(event.target.value)}>
          <option value="upload">上传本地音视频</option><option value="video" disabled={!media}>当前已下载的视频</option>
        </select></div>
      <div><label htmlFor="transcription-language">识别语言</label>
        <select id="transcription-language" value={language} disabled={busy || running} onChange={event => setLanguage(event.target.value)}>
          <option value="auto">自动检测</option><option value="zh">中文</option><option value="en">英文</option>
        </select></div>
      <button className="primary" type="button" disabled={ready === false || busy || running || (mode === 'upload' ? !file : !media)} onClick={() => { void start(); }}>
        <Icon name={busy ? 'loader-circle' : 'file-play'} className={busy ? 'spinner' : ''} />{busy ? (job ? '转录中…' : '提交文件中…') : '开始转录'}</button>
    </div>
    {mode === 'upload' ? <div className="transcription-upload">
      <label htmlFor="transcription-file">选择音视频文件（最多 32 个，每个最大 {Math.round(limit / 1024 / 1024)} MB）</label>
      <input id="transcription-file" type="file" multiple accept="audio/*,video/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac,.wma,.mp4,.mkv,.webm,.mov,.avi,.m4v"
        disabled={busy || running} onChange={event => { const selected=Array.from(event.target.files || []).slice(0,32);setBatchFiles(selected);setFile(selected[0] ?? null);if (selected.length>1) setReuseModel(true);setBatchNotice(selected.length>1?`已选择 ${selected.length} 个文件，将分别排队；单个失败不影响后续。`:'');setError(''); }} />
    </div> : <p className="subtitle-title">转写版本：{media?.filename || '请先下载并归档视频。'}</p>}
    <label className="settings-check"><input type="checkbox" checked={reuseModel} disabled={busy || running} onChange={event=>setReuseModel(event.target.checked)} />连续任务复用 CUDA 模型（空闲 60 秒释放；批量选择时默认启用）</label>
    {batchNotice && <p className="notice" role="status">{batchNotice}</p>}
    <div className={'inset subtitle-status ' + (error || job?.state === 'failed' ? 'status-error' : '')} role="status" aria-live="polite">
      {error || job?.message || (busy ? '正在提交到本机服务…' : '等待选择音视频。')}
    </div>
    {job && isActive(job.state) && <button type="button" onClick={() => { void cancelTask('transcriptions',job.id).catch(reason=>setError(String(reason))); }}>取消转录任务</button>}
    {error && lastId.current && <button type="button" className="subtitle-refresh" disabled={busy} onClick={refresh}>重新读取转录状态</button>}
    {job && <p className="subtitle-title">本次任务：{job.title}{job.language ? ' · 识别语言：' + job.language : ''}</p>}
    {job?.text && <div className="analysis-result transcription-result">
      <label htmlFor="transcription-text">识别文字</label><textarea id="transcription-text" readOnly rows={8} value={job.text} />
    </div>}
    {job?.files.length ? <div className="transcription-downloads">{job.files.map(output =>
      <button type="button" key={output.format} onClick={() => saveFiles([output.url])}><Icon name="download" />下载 {output.format.toUpperCase()}</button>)}
    </div> : null}
    {job?.files.some(file => file.format.toLowerCase() === 'srt') && <p className="subtitle-note">SRT 为片段级时间戳，识别结果需人工校对。</p>}
    {job?.state === 'running' && <p className="subtitle-note">切换视频或刷新页面不会停止后台转录任务。</p>}
  </section>;
}
