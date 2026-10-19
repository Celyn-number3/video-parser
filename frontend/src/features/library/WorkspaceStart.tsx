import type { ReactNode } from 'react';
import Icon from '../../components/Icon';

type Props = { children: ReactNode; onContinue: () => void };

export default function WorkspaceStart({ children, onContinue }: Props) {
  return <section className="workspace-start" aria-labelledby="workspace-start-title">
    <div className="workspace-start-intro">
      <h2 id="workspace-start-title">从一个链接开始</h2>
    </div>
    {children}
    <div className="workspace-continue">
      <h3>已经有归档资料？</h3>
      <button type="button" onClick={onContinue}><Icon name="book-open" />继续已有学习</button>
    </div>
  </section>;
}
