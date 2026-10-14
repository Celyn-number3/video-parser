import { useCallback, useState } from 'react';
import { DEFAULT_SETTINGS, normalizeSettings, SETTINGS_KEY, type Settings } from './settings';

export default function usePreferences() {
  const [settings, setSettings] = useState<Settings>(() => {
    try { return normalizeSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY) || 'null')); }
    catch { return { ...DEFAULT_SETTINGS }; }
  });
  const [saveStatus, setSaveStatus] = useState('');
  const saveSettings = useCallback((next: Settings) => {
    setSettings(next);
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(next)); setSaveStatus('设置已保存。'); }
    catch { setSaveStatus('当前页已生效，关闭或刷新后可能丢失。'); }
  }, []);
  return { settings, saveStatus, saveSettings };
}
