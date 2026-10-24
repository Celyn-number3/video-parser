import type { VideoProject, VideoProjectSummary } from './api';

type ProjectTitle = Pick<VideoProject | VideoProjectSummary, 'title' | 'display_title' | 'episode_title'>;
// Source title stays available for provenance/search; directory changes only affect display_title.
export const projectDisplayTitle = (project: ProjectTitle) => project.display_title || project.title;
export const videoDisplayTitle = (project: ProjectTitle) => project.episode_title || projectDisplayTitle(project);
