import { useEffect, useState, type RefObject } from 'react';

/** Native scrolling; manual browsing pauses playback follow, and seeking resumes it. */
export default function useChapterScroll(ref: RefObject<HTMLOListElement | null>, active: number,
  visible: boolean, identity: string, videoRef: RefObject<HTMLVideoElement | null>) {
  const [follow, setFollow] = useState(true), [seekVersion, setSeekVersion] = useState(0);
  useEffect(() => { setFollow(true); }, [identity]);
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !ref.current) return;
    const seeking = () => { setFollow(true); setSeekVersion(value => value + 1); };
    // A manual pause while buffering must survive seek completion, as in subtitles.
    const seeked = () => setSeekVersion(value => value + 1);
    video.addEventListener('seeking', seeking); video.addEventListener('seeked', seeked);
    return () => { video.removeEventListener('seeking', seeking); video.removeEventListener('seeked', seeked); };
  }, [ref, videoRef, identity]);
  useEffect(() => {
    const element = ref.current;
    if (!follow || !visible || !element) return;
    const align = () => {
      const row = element.querySelector<HTMLElement>('[aria-current="true"]');
      if (row && element.clientHeight > 0) element.scrollTop = Math.max(0, row.offsetTop - element.clientHeight / 3);
    };
    align();
    const observer = new ResizeObserver(align); observer.observe(element);
    return () => observer.disconnect();
  }, [ref, active, follow, seekVersion, visible, identity]);
  return { pauseFollow: () => setFollow(false) };
}
