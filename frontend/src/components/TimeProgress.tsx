import { formatClock, formatEta } from '../lib/format';
import type { TaskInfo } from '../lib/jobs';
import './progress.css';

type Props = { progress?: TaskInfo['progress']; label: string };
// Progress through a media timeline (e.g. transcription): done/total are seconds of audio.
// Without a total yet (model loading, queued) the bar breathes instead of showing a number.
export default function TimeProgress({ progress, label }: Props) {
  const total = progress?.total || 0;
  const done = Math.min(Math.max(progress?.done || 0, 0), total);
  const percent = total > 0 ? Math.min(100, Math.floor(done / total * 100)) : undefined;
  const eta = progress?.eta_seconds;
  const parts = percent === undefined ? [] : [
    `${percent}%`,
    `${formatClock(done)} / ${formatClock(total)}`,
    eta !== undefined && eta >= 1 ? `剩余 ${formatEta(eta)}` : '',
  ].filter(Boolean);
  return <div className="progress-block">
    <div className={'progress-bar' + (percent === undefined ? ' is-pending' : '')} role="progressbar" aria-label={label}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
      <div className="progress-fill" style={percent !== undefined ? { width: `${percent}%` } : undefined} />
    </div>
    {parts.length > 0 && <div className="progress-meta"><span>{parts.join(' · ')}</span></div>}
  </div>;
}
