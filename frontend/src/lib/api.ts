export interface Configuration {
  platforms: string[];
  ai_configured: boolean;
  media_ready: boolean;
  subtitles_ready: boolean;
  transcription_ready: boolean;
  transcription_upload_limit: number;
  archive_root: string;
}

export interface ParsedVideo {
  id: string;
  title: string;
  platform: string;
  source_url: string;
  cover_url: string | null;
  cover_download_url: string | null;
  warning: string | null;
  project: VideoProject;
  media: Media | null;
  qualities: VideoQuality[];
  default_quality_id: string | null;
  bilibili_cookie_status?: string | null;
}

export interface VideoQuality {
  id: string;
  label: string;
  width: number | null;
  height: number | null;
  codec?: string | null;
  media: Media | null;
}

export interface Media {
  resource: string;
  quality_id: string;
  preview_url: string;
  download_url: string;
  filename: string;
  size_bytes: number;
  duration: number;
  width: number | null;
  height: number | null;
}

export async function request<T>(path: string, signal: AbortSignal, body?: unknown): Promise<T> {
  const uploading = body instanceof File;
  const response = await fetch(`/api/workspace${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': uploading ? 'application/octet-stream' : 'application/json' },
    body: body === undefined ? undefined : uploading ? body : JSON.stringify(body),
    signal,
  }).catch((error: unknown) => {
    if (signal.aborted) throw error;
    throw new Error('无法连接工作台服务，请确认本地后端正在运行。');
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || data === null) {
    throw new Error(typeof data?.detail === 'string' ? data.detail :
      response.status === 422 ? '输入不符合要求，请检查链接、帧数与隐私确认。' : `服务处理失败（HTTP ${response.status}，请求 ${response.headers.get('X-Request-ID')?.slice(0,12) || 'unknown'}）。请检查任务中心或本机诊断。`);
  }
  return data as T;
}

export interface SubtitleJob {
  id: string;
  state: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'login_required' | 'cancelled' | 'interrupted';
  message: string;
  title: string;
  downloaded: number;
  existing: number;
  failed: number;
  results: {
    episode: number;
    status: 'downloaded' | 'existing' | 'failed';
    message: string;
    lines?: number;
    files: { name: string; format: string; url: string }[];
    project?: VideoProject;
  }[];
}

export interface VideoProject {
  id: string;
  title: string;
  platform: string;
  part: number | null;
  location: string;
  identity_status: string;
  archive_url: string;
  resources: { path: string; kind: string; size_bytes: number; url: string }[];
}

export interface TranscriptionJob {
  id: string;
  state: 'queued' | 'running' | 'completed' | 'empty' | 'failed' | 'cancelled' | 'interrupted';
  message: string;
  title: string;
  text: string;
  language: string;
  files: { name: string; format: string; url: string }[];
}
