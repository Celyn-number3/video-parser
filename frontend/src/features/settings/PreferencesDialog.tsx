import { useEffect, useRef } from 'react';
import type { Configuration } from '../../lib/api';
import type { Settings } from './settings';

export default function SettingsDialog({ settings, onChange, config, configError, saveStatus, onReset, onClose }: {
  settings: Settings; onChange: (settings: Settings) => void; config: Configuration | null;
  configError: string; saveStatus: string; onReset: () => void; onClose: () => void;
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
      <p className="settings-hint">偏好仅影响下次解析，不会改变当前视频、正在运行的任务或恢复的历史项目。</p>
      <p role="status" aria-live="polite" className="settings-save-status">{saveStatus}</p>
      <button type="button" className="secondary" onClick={onReset}>恢复默认</button>
    </section>
    <section aria-labelledby="settings-storage"><h3 id="settings-storage">保存说明</h3>
      <p>归档位置（只读）：</p><code className="archive-root">{config?.archive_root || (configError ? '无法读取归档位置' : '正在读取…')}</code>
      <p>点击“下载”会将视频保存到上述归档目录，可通过“打开项目文件夹”查看。</p>
      <p>归档按项目和画质管理，已有资源优先复用。</p>
    </section>
    <section aria-labelledby="settings-services"><h3 id="settings-services">服务状态</h3>
      {config ? <ul className="service-status"><li>媒体工具：{config.media_ready ? '就绪' : '未就绪'}</li><li>字幕：{config.subtitles_ready ? '就绪' : '未就绪'}</li><li>转录：{config.transcription_ready ? '就绪' : '未就绪'}</li><li>AI：{config.ai_configured ? '已配置' : '未配置'}</li></ul> : configError ? <p role="alert" className="error-text">{configError}</p> : <p>正在读取服务状态…</p>}
    </section>
  </dialog>;
}
