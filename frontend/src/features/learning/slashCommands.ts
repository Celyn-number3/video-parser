export type SlashCommand = { name: string; prefix: string; description?: string };
export type SlashToken = { start: number; end: number; query: string };

export function slashToken(text: string, caret: number, selectionEnd = caret): SlashToken | null {
  if (caret !== selectionEnd || caret < 0 || caret > text.length) return null;
  const before = text.slice(0, caret), match = /^[\t ]*\/([^\s/]*)$/u.exec(before);
  // `$` may match before a final newline; a completed token must not reopen suggestions.
  if (!match || match[0].length !== before.length) return null;
  let end = caret;
  while (end < text.length && !/[\s/]/u.test(text[end])) end++;
  return { start: before.indexOf('/'), end, query: match[1] };
}

export function matchingCommands(commands: SlashCommand[], query: string): SlashCommand[] {
  const term = query.toLowerCase();
  const rank = (command: SlashCommand) => command.name.toLowerCase().startsWith(term) ? 0
    : command.name.toLowerCase().includes(term) ? 1 : 2;
  return commands.filter(command => (command.prefix === '/' || command.prefix === '$') && /^[A-Za-z0-9_:-]{1,120}$/.test(command.name))
    .filter(command => command.name.toLowerCase().includes(term) || (command.description || '').toLowerCase().includes(term))
    .sort((a, b) => rank(a) - rank(b));
}

export function completeCommand(text: string, token: SlashToken, command: SlashCommand) {
  const head = text.slice(0, token.start) + command.prefix + command.name;
  const tail = text.slice(token.end), separator = /^\s/u.test(tail) ? '' : ' ';
  return { text: head + separator + tail, caret: head.length + 1 };
}
