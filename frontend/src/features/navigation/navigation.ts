import type { IconName } from '../../components/Icon';

export type Page = 'workspace' | 'transcription' | 'tasks' | 'accounts';
export const pageNames: Record<Page, string> = {
  workspace: '视频工作台', transcription: '字幕与转写', tasks: '任务中心', accounts: '账号与登录',
};
export const pageIcons: Record<Page, IconName> = {
  workspace: 'circle-play', transcription: 'captions', tasks: 'list-checks', accounts: 'user-round',
};
