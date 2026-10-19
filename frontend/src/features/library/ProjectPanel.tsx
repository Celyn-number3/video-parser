import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Icon from '../../components/Icon';
import { request } from '../../lib/api';
import type { VideoProject } from '../../lib/api';
import './project-panel.css';

type Props = { project: VideoProject; onRenamed?: (project: VideoProject, renamed: string[]) => void };
const TITLE_LIMIT = 200;

export default function ProjectPanel({ project, onRenamed }: Props) {
  const [message, setMessage] = useState('');
  const [opening, setOpening] = useState(false);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(project.title);
  const [saving, setSaving] = useState(false);
  const active = useRef<AbortController | null>(null);
  const renaming = useRef<AbortController | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const renameButton = useRef<HTMLButtonElement>(null);
  useEffect(() => () => { active.current?.abort(); renaming.current?.abort(); }, []);
  async function open() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setOpening(true);
    try {
      const result = await request<{ message: string }>(`/projects/${project.id}/open`, controller.signal, {});
      if (!controller.signal.aborted) setMessage(result.message);
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : '无法打开项目目录。');
    } finally {
      if (!controller.signal.aborted) { active.current = null; setOpening(false); }
    }
  }
  function startEditing() {
    setTitle(project.title); setEditing(true); setMessage('');
    requestAnimationFrame(() => field.current?.select());
  }
  function stopEditing() {
    setEditing(false); requestAnimationFrame(() => renameButton.current?.focus());
  }
  // Only the display title changes; the project ID, folder and archived files stay where they are.
  async function rename(event: FormEvent) {
    event.preventDefault();
    const next = title.replace(/\s+/g, ' ').trim();
    if (!next || renaming.current) return;
    if (next === project.title) { stopEditing(); return; }
    const controller = new AbortController();
    renaming.current = controller;
    setSaving(true); setMessage('');
    try {
      const result = await request<{ project: VideoProject; renamed: string[] }>(`/projects/${project.id}/title`, controller.signal, { title: next });
      if (controller.signal.aborted) return;
      onRenamed?.(result.project, result.renamed);
      setMessage(result.renamed.length > 1 ? `已重命名，并同步到本课程已归档的 ${result.renamed.length} 个分集。` : '已重命名，项目文件夹和归档文件保持不变。');
      stopEditing();
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : '无法保存标题。');
    } finally {
      if (!controller.signal.aborted) { renaming.current = null; setSaving(false); }
    }
  }
  return <div className="project-panel">
    <div className="project-actions">
      <code className="project-path" title={`outputs/${project.location}`}>outputs/{project.location}</code>
      {onRenamed && !editing && <button type="button" ref={renameButton} onClick={startEditing} title="修改显示标题，不移动文件">重命名</button>}
      <button type="button" aria-label="打开项目文件夹" title="打开项目文件夹" disabled={opening} aria-busy={opening} onClick={() => { void open(); }}><Icon name="external-link" />打开</button>
    </div>
    {editing && <form className="project-rename" onSubmit={event => { void rename(event); }}>
      <label className="sr-only" htmlFor={`project-title-${project.id}`}>项目标题</label>
      <input id={`project-title-${project.id}`} ref={field} value={title} maxLength={TITLE_LIMIT} disabled={saving} spellCheck={false}
        onChange={event => setTitle(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); stopEditing(); } }} />
      <button type="submit" className="primary" disabled={saving || !title.trim()} aria-busy={saving}>{saving ? '保存中…' : '保存'}</button>
      <button type="button" disabled={saving} onClick={stopEditing}>取消</button>
    </form>}
    {message && <p className="project-message" aria-live="polite">{message}</p>}
  </div>;
}
