import type { ReactNode } from 'react';

type Props = { htmlFor: string; label: ReactNode; children: ReactNode;
  className?: string; labelClassName?: string };
export default function FormField({ htmlFor, label, children, className = '', labelClassName }: Props) {
  return <div className={['form-field', className].filter(Boolean).join(' ')}>
    <label htmlFor={htmlFor} className={labelClassName}>{label}</label>{children}
  </div>;
}
