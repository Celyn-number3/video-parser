import { useEffect, useRef, useState } from 'react';
import { request } from '../../lib/api';
import type { Account } from './Accounts';

// Headless QR login for 抖音 / 小红书: the server keeps a hidden browser on the site's login
// page and relays its QR code; cookies are saved on this machine and never sent here.
const ACTIVE = ['starting', 'waiting', 'scanned', 'saving'];
type Session = NonNullable<Account['login']>;

export default function QrLogin({ account, onClose, onSuccess, onFallback }: {
  account: Pick<Account, 'id' | 'name'>; onClose: () => void; onSuccess: () => void; onFallback: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const success = useRef(onSuccess);
  success.current = onSuccess;
  const cancelling = useRef<Promise<unknown>>(Promise.resolve());
  const [generation, setGeneration] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    setSession(null); setError('');
    function update(next: Session | null) {
      if (controller.signal.aborted) return;
      setSession(next);
      active = Boolean(next && ACTIVE.includes(next.state));
      if (next?.state === 'saved') success.current();
      else if (active) timer = setTimeout(() => { void poll(); }, 1500);
    }
    async function poll() {
      try { update((await request<Account>(`/accounts/${account.id}`, controller.signal)).login); }
      catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '登录状态读取失败。'); }
    }
    void (async () => {
      try {
        await cancelling.current; // A refresh must wait until the previous hidden browser has closed.
        update((await request<Account>(`/accounts/${account.id}/qr`, controller.signal, {})).login);
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '二维码获取失败。'); }
    })();
    return () => {
      controller.abort(); clearTimeout(timer);
      if (active) cancelling.current = request(`/accounts/${account.id}/login/cancel`, new AbortController().signal, {}).catch(() => {});
    };
  }, [account.id, generation]);
  const state = error ? 'error' : session?.state || 'starting';
  const ended = ['expired', 'failed', 'verify', 'cancelled', 'error'].includes(state);
  const message = error || session?.message || '正在准备二维码，大约需要 10 秒…';
  return <dialog ref={dialog} className="settings-dialog login-dialog" aria-labelledby="qr-login-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="qr-login-title">{account.name}扫码登录</h2>
    <div className="login-qr" aria-busy={state === 'starting'}>
      {session?.qr ? <img src={session.qr} alt={`使用${account.name}扫描此登录二维码`} width="256" height="256" />
        : <span aria-hidden="true">{state === 'starting' ? '正在获取二维码…' : state === 'scanned' || state === 'saving' || state === 'saved' ? '已扫码' : '二维码暂不可用'}</span>}
    </div>
    <p className="login-status" role="status" aria-live="polite" aria-atomic="true">{message}</p>
    <p className="notice">登录信息只保存在本机。手机上要求短信验证时，请改用浏览器登录。</p>
    <div className="login-actions">
      <button type="button" className={ended ? 'primary' : undefined} onClick={() => setGeneration(value => value + 1)} disabled={state === 'starting' || state === 'saving'}>刷新二维码</button>
      {(state === 'failed' || state === 'verify' || state === 'error') && <button type="button" onClick={onFallback}>改用浏览器登录</button>}
      <button type="button" onClick={onClose}>取消</button>
    </div>
  </dialog>;
}
