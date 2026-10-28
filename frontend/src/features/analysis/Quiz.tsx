import { useState } from 'react';
import type { Quiz } from '../../lib/api';
import { formatClock } from '../../lib/format';
import './quiz.css';

const LETTERS = 'ABCDEF';

type Props = { quiz: Quiz; onSeek?: (seconds: number) => void };

export default function QuizView({ quiz, onSeek }: Props) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const answered = Object.keys(answers).length;
  const correct = quiz.questions.reduce((sum, item, index) => answers[index] === item.answer ? sum + 1 : sum, 0);
  return <section className="quiz" aria-label="复习自测题">
    <div className="quiz-heading">
      <div>
        <strong>{quiz.title || '复习自测题'}</strong>
        <span className="quiz-score">{`答对 ${correct} / ${answered} 题 · 共 ${quiz.questions.length} 题`}</span>
      </div>
      {answered > 0 && <button type="button" onClick={() => setAnswers({})}>重新作答</button>}
    </div>
    <ol className="quiz-list">
      {quiz.questions.map((item, index) => {
        const chosen = answers[index];
        const done = chosen !== undefined;
        const time = item.time;
        return <li key={index} className={done ? (chosen === item.answer ? 'is-correct' : 'is-wrong') : ''}>
          <div className="quiz-question">
            <span className="quiz-index" aria-hidden="true">{index + 1}</span>
            <p>{item.question}</p>
            {time !== null && <button type="button" className="quiz-time" disabled={!onSeek}
              aria-label={`跳到第 ${index + 1} 题的时间点 ${formatClock(time)}`} onClick={() => onSeek?.(time)}>{formatClock(time)}</button>}
          </div>
          <div className="quiz-options" role="group" aria-label={`第 ${index + 1} 题选项`}>
            {item.options.map((option, optionIndex) => {
              const state = !done ? '' : optionIndex === item.answer ? ' correct' : optionIndex === chosen ? ' wrong' : '';
              return <button type="button" key={optionIndex} className={'quiz-option' + state} aria-pressed={chosen === optionIndex}
                onClick={() => setAnswers(current => ({ ...current, [index]: optionIndex }))}>
                <span>{LETTERS[optionIndex]}</span>{option}
              </button>;
            })}
          </div>
          {done && <div className="quiz-answer" role="status">
            <p><strong>{chosen === item.answer ? '回答正确' : '回答错误'}</strong>{` · 正确答案 ${LETTERS[item.answer]}. ${item.answer_text}`}</p>
            {item.explanation && <p><span className="quiz-answer-label">解析</span>{item.explanation}</p>}
          </div>}
        </li>;
      })}
    </ol>
  </section>;
}
