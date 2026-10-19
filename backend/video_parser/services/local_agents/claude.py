"""Claude Code's structured stdio protocol, without copying credentials or bundling its SDK."""
import time
import json
from uuid import UUID, uuid4

from .transport import Wire, AgentError, RpcError
from .types import Result, Progress, command_entries


class Runtime:
    def __init__(self, workspace, target=None, turn=None, session_id=None, persistent=False):
        target = target or {}
        self.turn = turn
        arguments = ['-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
            '--include-partial-messages', '--permission-prompt-tool', 'stdio', '--permission-mode', 'default',
            '--tools', 'Skill' if turn and turn.purpose == 'chat' else '',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--setting-sources', 'user']
        if turn:
            arguments += ['--append-system-prompt', turn.instructions]
        if session_id:
            try:
                UUID(session_id)
            except (ValueError, TypeError, AttributeError):
                raise ValueError('无效 Claude Code 会话标识。') from None
            arguments += ['--resume', session_id]
        elif not persistent:
            arguments += ['--no-session-persistence']
        if target.get('model') and target['model'] != 'default':
            arguments += ['--model', target['model']]
        if target.get('effort'):
            arguments += ['--effort', target['effort']]
        self.wire = Wire('claude', workspace, arguments)
        self.metadata = {}
        try:
            self.wire.send({'type': 'control_request', 'request_id': 'initialize', 'request': {'subtype': 'initialize'}})
            deadline = time.monotonic() + 30
            while True:
                message = self.wire.read(deadline)
                if message.get('type') == 'control_response':
                    response = message.get('response', {})
                    if response.get('request_id') == 'initialize':
                        if response.get('subtype') != 'success':
                            raise AgentError()
                        self.metadata = response.get('response', {})
                        break
                self.control(message)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.wire.close()

    def catalog(self):
        models = []
        for item in self.metadata.get('models', [])[:100]:
            if item.get('value') and item['value'] != 'default':
                models.append({'id': item['value'], 'label': item.get('displayName') or item['value'],
                    'efforts': item.get('supportedEffortLevels', []) if item.get('supportsEffort') else [],
                    'images': None})
        # Interactive-only CLI controls are not embeddable slash commands. User/project Skills are.
        commands = [item for item in self.metadata.get('commands', [])
                    if any(marker in item.get('description', '') for marker in ('(user)', '(project)', '(plugin:'))]
        return {'models': models, 'commands': command_entries(commands)}

    def control(self, message):
        if message.get('type') != 'control_request':
            return
        request = message.get('request', {})
        known = {item['name'] for item in self.catalog()['commands']}
        allowed = (self.turn and self.turn.purpose == 'chat' and request.get('subtype') == 'can_use_tool'
                   and request.get('tool_name') == 'Skill' and request.get('input', {}).get('skill') in known)
        response = {'behavior': 'allow', 'updatedInput': request.get('input', {})} if allowed else {
            'behavior': 'deny', 'message': 'Only installed Skills are permitted; files, shell and external tools are disabled in learning mode.'}
        self.wire.send({'type': 'control_response', 'response': {'subtype': 'success',
            'request_id': message.get('request_id'), 'response': response}})

    def run(self, turn, target, directory, session_id=None, rebuild=None):
        if turn.purpose == 'chat' and turn.question.lstrip().startswith('/'):
            command = turn.question.strip().split()[0][1:]
            if command not in {item['name'] for item in self.catalog()['commands']}:
                raise AgentError('这个命令不能在学习会话中运行，请使用对话或模型菜单。')
        parts = [{'type': 'text', 'text': turn.text}]
        parts.extend({'type': 'image', 'source': {'type': 'base64', 'media_type': image['mime'], 'data': image['data']}}
                     for image in turn.images)
        self.wire.send({'type': 'user', 'message': {'role': 'user', 'content': parts if turn.images else turn.text},
                        'parent_tool_use_id': None, 'session_id': session_id or '', 'uuid': str(uuid4())})
        progress = Progress('Claude Code')
        deadline = time.monotonic() + 900
        answer, streamed, identifier, model = '', '', session_id, target.get('model', '')
        try:
            while True:
                message = self.wire.read(deadline)
                kind = message.get('type')
                if kind == 'control_request':
                    self.control(message)
                elif kind == 'system' and message.get('subtype') == 'init':
                    identifier, model = message.get('session_id'), message.get('model') or model
                elif kind == 'stream_event':
                    event = message.get('event', {})
                    delta = event.get('delta', {})
                    if event.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta':
                        value = delta.get('text', '')
                        streamed += value
                        progress.text(value)
                elif kind == 'assistant':
                    chunks = message.get('message', {}).get('content', [])
                    text = '\n'.join(item.get('text', '') for item in chunks if item.get('type') == 'text')
                    if text:
                        answer = text
                elif kind == 'result':
                    if message.get('is_error') or message.get('subtype') not in ('success', None):
                        raise RpcError(message.get('api_error_status') or -32000, json.dumps(message.get('errors') or message.get('error') or message.get('result') or message.get('subtype')))
                    text = (message.get('result') or answer or streamed).strip()
                    if not text:
                        raise AgentError('本地 agent 没有返回可保存的回答，请检查模型能力。')
                    usage = message.get('usage', {})
                    return Result(text, message.get('session_id') or identifier,
                        {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens')}, model)
        except BaseException:
            try:
                self.wire.send({'type': 'control_request', 'request_id': 'cancel', 'request': {'subtype': 'interrupt'}})
            except AgentError:
                pass
            raise
