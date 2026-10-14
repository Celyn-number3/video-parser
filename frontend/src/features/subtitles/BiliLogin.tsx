import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';

type QR = { id: string; image: string; state: string; expires_in: number };
export default function BiliLogin({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const success = useRef(onSuccess);
  success.current = onSuccess;
  const [generation, setGeneration] = useState(0);
  const [qr, setQr] = useState<QR | null>(null);
  const [state, setState] = useState('loading');
  const [error, setError] = useState('');
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let identifier = '';
    let timer: ReturnType<typeof setTimeout> | undefined;
    setQr(null); setState('loading'); setError('');
    async function poll() {
      try {
        const result = await request<{ state: string }>(`/bili-login/${identifier}/poll`, controller.signal, {});
        if (controller.signal.aborted) return;
        setState(result.state);
        if (result.state === 'authenticated') success.current();
        else if (result.state !== 'expired') timer = setTimeout(() => { void poll(); }, 2200);
      } catch (reason) {
        if (!controller.signal.aborted) { setState('error'); setError(reason instanceof Error ? reason.message : '登录状态读取失败'); }
      }
    }
    void (async () => {
      try {
        const result = await request<QR>('/bili-login', controller.signal, {});
        identifier = result.id;
        if (controller.signal.aborted) return;
        setQr(result); setState('waiting');
        timer = setTimeout(() => { void poll(); }, 2200);
      } catch (reason) {
        if (!controller.signal.aborted) { setState('error'); setError(reason instanceof Error ? reason.message : '二维码获取失败'); }
      }
    })();
    return () => {
      controller.abort(); clearTimeout(timer);
      if (identifier) void request(`/bili-login/${identifier}/cancel`, new AbortController().signal, {}).catch(() => {});
    };
  }, [generation]);
  const messages: Record<string, string> = { loading: '正在申请二维码…', waiting: '请使用哔哩哔哩手机 App 扫码', scanned: '扫码成功，请在手机上确认登录', expired: '二维码已过期，请刷新后重新扫码', authenticated: '登录成功', error: '登录暂时不可用' };
  return <dialog ref={dialog} className="settings-dialog login-dialog" aria-labelledby="bili-login-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="bili-login-title">B站扫码登录</h2>
    <div className="login-qr" aria-busy={state === 'loading'}>
      {qr && state !== 'expired' && state !== 'error' ? <img src={qr.image} alt="使用哔哩哔哩 App 扫描此登录二维码" width="256" height="256" /> : <span aria-hidden="true">{state === 'loading' ? '正在获取二维码…' : '二维码暂不可用'}</span>}
    </div>
    <p className="login-status" role="status" aria-live="polite" aria-atomic="true">{error || messages[state]}</p>
    <p className="notice">二维码 3 分钟内有效，登录信息只保存在本机。</p>
    <div className="login-actions">
      <button type="button" onClick={() => setGeneration(value => value + 1)} disabled={state === 'loading'}>刷新二维码</button>
      <button type="button" onClick={onClose}>取消</button>
    </div>
  </dialog>;
}
