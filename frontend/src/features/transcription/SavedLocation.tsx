import { useState, type ReactNode } from 'react';
import Icon from '../../components/Icon';
import { request } from '../../lib/api';

// One row for every saved result (existing subtitles, transcription, translation):
// what and where it is on disk, then extra actions, then "打开文件夹" — always last, so stacked rows line it up.
export default function SavedLocation({ location, openPath, body = {}, label = '已保存到', children }: {
  location: string; openPath: string; body?: Record<string, string>; label?: string; children?: ReactNode;
}) {
  const [notice, setNotice] = useState('');
  const [opening, setOpening] = useState(false);
  async function open() {
    setOpening(true); setNotice('');
    try { setNotice((await request<{ message: string }>(openPath, new AbortController().signal, body)).message); }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : '无法打开文件夹。'); }
    finally { setOpening(false); }
  }
  return <div className="saved-location">
    <div className="saved-location-row">
      <span className="saved-location-text"><span>{label}</span><code title={location}>{location}</code></span>
      <span className="saved-location-actions">
        {children}
        <button type="button" disabled={opening} aria-busy={opening} onClick={() => { void open(); }}><Icon name="external-link" />打开文件夹</button>
      </span>
    </div>
    {notice && <p className="notice" role="status">{notice}</p>}
  </div>;
}
