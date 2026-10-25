import { useEffect, useId, useMemo, useState } from 'react';
import type { TextareaHTMLAttributes } from 'react';
import MathText from './MathText';
import { protectMath } from './markdownMath';

type Props = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'defaultValue' | 'onChange'> & { value: string };
/** Read-only results get math reading, while the exact source remains selectable/copyable. */
export default function MathTextArea({ value, ...props }: Props) {
  const hasMath = useMemo(() => protectMath(value).expressions.size > 0, [value]);
  const [source, setSource] = useState(false);
  const generatedId = useId();
  const sourceId = props.id || generatedId;
  useEffect(() => { setSource(false); }, [value]);
  if (!hasMath) return <textarea {...props} value={value} readOnly />;
  return <div className="math-text-area">
    <div className="math-reading-toolbar"><span>公式阅读</span><button type="button" aria-expanded={source} aria-controls={sourceId}
      onClick={() => setSource(current => !current)}>{source ? '返回公式阅读' : '查看原始文本'}</button></div>
    <div className="math-reading-body" role="region" aria-label={String(props['aria-label'] || '公式阅读') + ' · 公式阅读'} tabIndex={0} hidden={source}><MathText text={value} /></div>
    <textarea {...props} id={sourceId} value={value} readOnly hidden={!source} />
  </div>;
}
