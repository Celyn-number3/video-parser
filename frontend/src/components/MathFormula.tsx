import { useMemo } from 'react';
import katex from 'katex';
import type { MathExpression } from './markdownMath';
import 'katex/dist/katex.min.css';
import './math-formula.css';

export default function MathFormula({ expression }: { expression: MathExpression }) {
  const { source, tex, display } = expression;
  const html = useMemo(() => {
    if (tex.length > 16384) return null;
    try {
      return katex.renderToString(tex, {
        displayMode: display, output: 'htmlAndMathml', throwOnError: true,
        trust: false, strict: 'ignore', maxExpand: 1000, maxSize: 10,
        // Fresh macros for every expression: never retain a model's global definitions.
        macros: {},
      });
    } catch { return null; }
  }, [tex, display]);
  if (html === null) return <code className="md-math-fallback" title="公式暂时无法排版，保留原文">{source}</code>;
  // Only KaTeX's trust:false output enters HTML, never the original model text.
  return <span className={'md-math' + (display ? ' md-math-display' : '')} dangerouslySetInnerHTML={{ __html: html }} />;
}
