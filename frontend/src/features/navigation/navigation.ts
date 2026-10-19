import type { IconName } from '../../components/Icon';

export type Page = 'workspace' | 'learning' | 'transcription' | 'tasks' | 'accounts' | 'settings';
export const pageNames: Record<Page, string> = {
  workspace: '视频工作台', learning: '学习视图', transcription: '字幕与转写', tasks: '任务中心', accounts: '账号与登录', settings: '设置',
};
export const pageIcons: Record<Page, IconName> = {
  workspace: 'circle-play', learning: 'book-open', transcription: 'captions', tasks: 'list-checks', accounts: 'user-round', settings: 'settings',
};

export function pageFromSearch(search: string): Page {
  const value = new URLSearchParams(search).get('page');
  return value && Object.hasOwn(pageNames, value) ? value as Page : 'workspace';
}
