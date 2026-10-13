import { useEffect, useRef, useState } from 'react';
import Icon from '../../components/Icon';
import { request } from '../../lib/api';
import type { VideoProject } from '../../lib/api';

export default function ProjectPanel({ project }: { project: VideoProject }) {
  const [message, setMessage] = useState('');
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function open() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    try {
      const result = await request<{ message: string }>(`/projects/${project.id}/open`, controller.signal, {});
      if (!controller.signal.aborted) setMessage(result.message);
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : '无法打开项目目录。');
    }
  }
  return <div className="project-panel">
    <span className="field-label">项目位置</span>
    <p className="project-location">library/{project.location}</p>
    <div className="project-actions"><button type="button" onClick={() => { void open(); }}><Icon name="external-link" />打开项目文件夹</button>
    </div>
    {message && <p className="project-message" aria-live="polite">{message}</p>}
  </div>;
}
