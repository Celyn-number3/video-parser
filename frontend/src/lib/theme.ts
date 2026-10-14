import { useCallback, useEffect, useState } from 'react';

// 主题只切换 <html data-theme>；颜色映射全部在 styles/tokens.css。
// 存储键与 index.html 中的首帧脚本保持一致。
export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'vp-theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.(DARK_QUERY).matches ? 'dark' : 'light';
}

function initialTheme(): Theme {
  const current = document.documentElement.dataset.theme;
  if (current === 'light' || current === 'dark') return current;
  return storedTheme() ?? systemTheme();
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // 用户未手动选择时，跟随系统主题变化。
  useEffect(() => {
    const query = window.matchMedia?.(DARK_QUERY);
    if (!query) return;
    const onChange = () => { if (!storedTheme()) setTheme(query.matches ? 'dark' : 'light'); };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const toggleTheme = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* 存储不可用时只在本次会话生效 */ }
    setTheme(next);
  }, [theme]);

  return { theme, toggleTheme };
}
