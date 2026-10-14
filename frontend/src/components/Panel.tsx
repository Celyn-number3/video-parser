import type { HTMLAttributes, ReactNode } from 'react';

type Props = HTMLAttributes<HTMLElement> & { as?: 'section' | 'aside' | 'div' };
export default function Panel({ as: Element = 'section', className = '', ...props }: Props) {
  return <Element className={['panel', className].filter(Boolean).join(' ')} {...props} />;
}
export function PanelTitle({ id, secondary = false, children }: {
  id?: string; secondary?: boolean; children: ReactNode;
}) {
  return <h2 id={id} className={'panel-title' + (secondary ? ' panel-title-secondary' : '')}>{children}</h2>;
}
