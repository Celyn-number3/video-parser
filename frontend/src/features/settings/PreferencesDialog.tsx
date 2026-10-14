import { useEffect, useRef } from 'react';
import type { Configuration } from '../../lib/api';
import type { Settings } from './settings';
import CacheManager from './CacheManager';

export default function SettingsDialog({ settings, onChange, config, configError, saveStatus, activeCount, onClose }: {
  settings: Settings; onChange: (settings: Settings) => void; config: Configuration | null;
  configError: string; saveStatus: string; activeCount: number | null; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const quality = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    quality.current?.focus();
    return () => { if (element.open) element.close(); };
  }, []);
  return <dialog ref={dialog} className="settings-dialog" aria-labelledby="settings-title" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <div className="settings-heading"><h2 id="settings-title">设置</h2><button type="button" className="settings-close" aria-label="关闭设置" onClick={onClose}>×</button></div>
    <section aria-labelledby="settings-preferences"><h3 id="settings-preferences">下载偏好</h3>
      <label htmlFor="default-quality">默认画质</label>
      <select ref={quality} id="default-quality" value={settings.qualityPreference} onChange={event => onChange({ ...settings, qualityPreference: event.target.value as Settings['qualityPreference'] })}>
        <option value="best">最高可用</option><option value="1080p">优先 1080P</option><option value="720p">优先 720P</option>
      </select>
      <label className="settings-check"><input type="checkbox" checked={settings.completionReminder} onChange={event => onChange({ ...settings, completionReminder: event.target.checked })} />归档完成提醒</label>
      {saveStatus && <p role="status" aria-live="polite" className="settings-save-status">{saveStatus}</p>}
    </section>
    <section aria-labelledby="settings-transcription"><h3 id="settings-transcription">本地转写</h3>
      <label className="settings-check"><input type="checkbox" checked={settings.reuseTranscriptionModel} onChange={event => onChange({ ...settings, reuseTranscriptionModel: event.target.checked })} />连续任务复用模型</label>
      <p className="settings-hint">本机 CUDA 模型（large-v3-turbo）空闲 60 秒后释放，不会切换到 CPU 或云端。</p>
    </section>
    <section aria-labelledby="settings-storage"><h3 id="settings-storage">归档位置</h3>
      <code className="archive-root">{config?.archive_root || (configError ? '无法读取归档位置' : '正在读取…')}</code>
    </section>
    <section aria-labelledby="settings-services"><h3 id="settings-services">服务状态</h3>
      {config ? <ul className="service-status"><li>媒体工具：{config.media_ready ? '就绪' : '未就绪'}</li><li>字幕：{config.subtitles_ready ? '就绪' : '未就绪'}</li><li>转录：{config.transcription_ready ? '就绪' : '未就绪'}</li><li>AI：{config.ai_configured ? '已配置' : '未配置'}</li></ul> : configError ? <p role="alert" className="error-text">{configError}</p> : <p>正在读取服务状态…</p>}
    </section>
    <CacheManager activeCount={activeCount} />
  </dialog>;
}
