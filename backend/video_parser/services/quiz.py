"""Structured review quizzes: strict JSON parsing, Markdown rendering and Anki cards.

The `quiz` analysis template asks the model for one JSON object. Parsing is deliberately
strict: anything that cannot be validated is dropped instead of being shown as a question.
A record whose output does not parse keeps its raw text, so nothing is lost.
"""
import json
import math
import re

from video_parser.services import anki_export

MAX_QUESTIONS = 50
MAX_QUESTION = 1000
MAX_OPTION = 500
MAX_EXPLANATION = 2000
MAX_TITLE = 200
MAX_TIME = 31 * 86400
LETTERS = 'ABCDEF'
OPTION_PREFIX = re.compile(r'^\s*[A-Fa-f]\s*[.、):：]\s*')
LETTER_ANSWER = re.compile(r'^\s*([A-Fa-f])(?:\s*[.、):：]|\s|$)')


def _text(value, limit):
    if not isinstance(value, str):
        return ''
    return value.replace('\x00', '').strip()[:limit]


def _time(value):
    if type(value) not in (int, float):
        return None
    if not math.isfinite(value) or not 0 <= value <= MAX_TIME:
        return None
    return float(value)


def _answer(value, options):
    """Accept an index, a letter, or the exact option text; return an option index or None."""
    if type(value) is int:
        return value if 0 <= value < len(options) else None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    letter = LETTER_ANSWER.match(raw)
    if letter:
        index = LETTERS.index(letter[1].upper())
        if index < len(options):
            return index
    for index, option in enumerate(options):
        if raw.casefold() == option.casefold() or OPTION_PREFIX.sub('', raw).casefold() == option.casefold():
            return index
    return None


def _candidates(text):
    """Fenced blocks first, then the whole reply: models sometimes add prose around the JSON."""
    for match in re.finditer(r'```[A-Za-z]*\s*\n?(.*?)```', text, re.S):
        yield match.group(1)
    yield text


def _load(body):
    """Find the first JSON object carrying `questions` (or a bare list), tolerating prose."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(body):
        if char not in '{[':
            continue
        try:
            value, _ = decoder.raw_decode(body[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get('questions'), list):
            return value
        if isinstance(value, list):
            return value
    return None


def parse(text):
    """Model output → {'title': str, 'questions': [...]} or None when nothing is usable."""
    if not isinstance(text, str) or not text.strip():
        return None
    data = next((value for value in (_load(body.strip()) for body in _candidates(text.strip())) if value is not None), None)
    if data is None:
        return None
    if isinstance(data, dict):
        title = _text(data.get('title'), MAX_TITLE)
        rows = data.get('questions')
    else:
        title, rows = '', data
    if not isinstance(rows, list):
        return None
    questions = []
    for row in rows[:MAX_QUESTIONS]:
        if not isinstance(row, dict):
            continue
        question = _text(row.get('question'), MAX_QUESTION)
        options = []
        for option in row.get('options') or []:
            if not isinstance(option, str):
                continue
            option = OPTION_PREFIX.sub('', _text(option, MAX_OPTION)).strip()
            if option:
                options.append(option)
        if not question or not 2 <= len(options) <= len(LETTERS):
            continue
        answer = _answer(row.get('answer'), options)
        if answer is None:
            continue
        questions.append({'question': question, 'options': options, 'answer': answer,
                          'answer_text': options[answer], 'explanation': _text(row.get('explanation'), MAX_EXPLANATION),
                          'time': _time(row.get('time'))})
    if not questions:
        return None
    return {'title': title, 'questions': questions}


def clock(seconds):
    total = max(0, int(seconds or 0))
    hours, rest = divmod(total, 3600)
    return f'{hours}:{rest // 60:02d}:{rest % 60:02d}' if hours else f'{rest // 60:02d}:{rest % 60:02d}'


def markdown(quiz):
    """Readable export of a parsed quiz, used for Markdown/Word instead of raw JSON."""
    lines = []
    if quiz.get('title'):
        lines += [f"## {quiz['title']}", '']
    for index, item in enumerate(quiz['questions'], 1):
        stamp = f" [{clock(item['time'])}]" if item.get('time') is not None else ''
        lines += [f"### {index}. {item['question']}{stamp}", '']
        for option_index, option in enumerate(item['options']):
            lines.append(f"- {LETTERS[option_index]}. {option}")
        lines += ['', f"**答案：{LETTERS[item['answer']]}. {item['answer_text']}**"]
        if item.get('explanation'):
            lines += ['', item['explanation']]
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def cards(quiz, title='', url=''):
    """Anki Basic cards: question + options on the front, answer + explanation on the back."""
    source = anki_export.html(title)
    link = f"<div><a href='{anki_export.html(url)}'>{anki_export.html(url)}</a></div>" if re.match(r'^https?://', url or '') else ''
    rows = []
    for item in quiz['questions']:
        front = [f"<div><b>{anki_export.html(item['question'])}</b></div>"]
        front += [f"<div>{LETTERS[index]}. {anki_export.html(option)}</div>" for index, option in enumerate(item['options'])]
        back = [f"<div><b>答案：{LETTERS[item['answer']]}. {anki_export.html(item['answer_text'])}</b></div>"]
        if item.get('explanation'):
            back.append(f"<div>{anki_export.html(item['explanation'])}</div>")
        if item.get('time') is not None:
            back.append(f"<div>时间点：{clock(item['time'])}</div>")
        if source:
            back.append(f'<div>来源：{source}</div>')
        if link:
            back.append(link)
        rows.append({'front': ''.join(front), 'back': ''.join(back), 'tags': 'video-parser::quiz'})
    return rows


def csv_rows(quiz):
    return [[index, item['question'], ' | '.join(f'{LETTERS[position]}. {option}' for position, option in enumerate(item['options'])),
             f"{LETTERS[item['answer']]}. {item['answer_text']}", item.get('explanation', ''),
             clock(item['time']) if item.get('time') is not None else '']
            for index, item in enumerate(quiz['questions'], 1)]
