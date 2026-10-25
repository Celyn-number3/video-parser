import { useMemo } from 'react';
import MathFormula from './MathFormula';
import { protectMath } from './markdownMath';

/** Math only: safe inside a button, heading or paragraph. Never emits links/buttons/blocks. */
export default function MathText({ text, className = '' }: { text: string; className?: string }) {
  const parts = useMemo(() => {
    const math = protectMath(text);
    if (!math.expressions.size) return [text];
    const pattern = new RegExp('(' + math.prefix + '\\d+\uE001)', 'g');
    return math.text.split(pattern).map((part, index) => {
      const expression = math.expressions.get(part);
      return expression ? <MathFormula key={index} expression={{ ...expression, display: false }} /> : part;
    });
  }, [text]);
  return <span className={'math-text ' + className} translate="no">{parts}</span>;
}

/** Native title/aria attributes are text, not a place for generated HTML. */
export function mathTextLabel(text: string): string {
  const math = protectMath(text);
  let label = math.text;
  for (const [token, expression] of math.expressions) label = label.replace(token, () => expression.tex);
  return label;
}
