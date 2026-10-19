"""OpenCode ACP adapter with a process-local, restricted learning agent. Global config is not edited."""
import json
import os
import time

from .transport import Wire, AgentError, RpcError
from .types import Result, Progress, SAFE_INSTRUCTIONS, command_entries, valid_session

ROLE = 'video-parser-learning'


def launch_environment(instructions, allow_skills=False):
    try:
        config = json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT', '{}'))
        if not isinstance(config, dict):
            raise ValueError()
    except ValueError:
        raise AgentError('本机 OpenCode 的环境配置不是有效 JSON，未覆盖原配置。') from None
    tools = {'*': False, 'skill': bool(allow_skills)}
    permissions = {'*': 'deny', 'skill': 'allow' if allow_skills else 'deny'}
    # Preserve provider/auth routing in inherited configuration; override only this process's role and permissions.
    config.update(permission=permissions, tools=tools, share='disabled', default_agent=ROLE)
    config['agent'] = {**config.get('agent', {}), ROLE: {
        'description': 'Restricted course learning assistant', 'mode': 'primary',
        'prompt': instructions, 'permission': permissions, 'tools': tools}}
    return {'OPENCODE_CONFIG_CONTENT': json.dumps(config, ensure_ascii=False)}


def options(config, category):
    item = next((entry for entry in config if entry.get('category') == category or entry.get('id') == category), None)
    if not item:
        return None, []
    flat = []
    for entry in item.get('options', []):
        flat.extend(entry.get('options', [entry]))
    return item, flat


class Runtime:
    def __init__(self, workspace, turn=None):
        self.workspace = workspace
        self.session_id = None
        self.config = []
        self.commands = []
        self.parts = []
        instructions = turn.instructions if turn else SAFE_INSTRUCTIONS
        self.wire = Wire('opencode', workspace, ['acp', f'--cwd={workspace}'], launch_environment(instructions, bool(turn and turn.purpose == 'chat')))
        self.wire.on_event = self.event
        self.wire.on_request = self.request
        self.progress = Progress('OpenCode')
        self.accept_text = False
        try:
            self.init = self.rpc('initialize', {'protocolVersion': 1,
                'clientInfo': {'name': 'video-parser', 'version': '3.0.0'},
                'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}})
        except BaseException:
            self.close()
            raise

    def close(self):
        self.wire.close()

    def rpc(self, method, params, timeout=30):
        aliases = {'session/new': 'new_session', 'session/load': 'load_session', 'session/prompt': 'prompt',
                   'session/set_config_option': 'session/setConfigOption'}
        try:
            return self.wire.request(method, params, timeout)
        except RpcError as error:
            if error.rpc_code != -32601 or method not in aliases:
                raise
            return self.wire.request(aliases[method], params, timeout)

    def event(self, message):
        if message.get('method') not in ('session/update', 'sessionUpdate'):
            return
        params = message.get('params', {})
        if self.session_id and params.get('sessionId') not in (None, self.session_id):
            return
        update = params.get('update', {})
        kind = update.get('sessionUpdate')
        if kind == 'available_commands_update':
            self.commands = command_entries(update.get('availableCommands', []))
        elif kind == 'config_option_update':
            self.config = update.get('configOptions', self.config)
        elif kind == 'agent_message_chunk' and self.accept_text:
            content = update.get('content', {})
            if content.get('type') == 'text':
                text = content.get('text', '')
                self.parts.append(text)
                self.progress.text(text)

    @staticmethod
    def request(method, params):
        if method in ('session/request_permission', 'request_permission', 'session/requestPermission'):
            return {'outcome': {'outcome': 'cancelled'}}
        raise RpcError(-32601)

    def set_option(self, category, value):
        item, choices = options(self.config, category)
        if not item or value not in {entry.get('value') for entry in choices}:
            raise AgentError('所选模型或推理设置不在本地 agent 提供的能力列表中，请刷新。')
        result = self.rpc('session/set_config_option', {'sessionId': self.session_id,
            'configId': item['id'], 'type': 'select', 'value': value})
        self.config = result.get('configOptions', self.config)

    def ensure_session(self, session_id=None):
        session_id = valid_session(session_id)
        self.accept_text = False
        if session_id:
            try:
                response = self.rpc('session/load', {'sessionId': session_id, 'cwd': str(self.workspace), 'mcpServers': []})
            except RpcError as error:
                if not error.missing_session():
                    raise
                session_id = None
        if not session_id:
            response = self.rpc('session/new', {'cwd': str(self.workspace), 'mcpServers': []})
        # ACP load responses can omit sessionId: the request's accepted ID remains authoritative.
        self.session_id = valid_session(response.get('sessionId') or session_id)
        if not self.session_id:
            raise AgentError()
        self.config = response.get('configOptions', [])
        # Fail closed if an incompatible version ignores the process-local restricted role.
        self.set_option('mode', ROLE)
        return bool(session_id and session_id == self.session_id)

    def catalog(self, target=None):
        self.ensure_session()
        if target and target.get('model'):
            self.set_option('model', target['model'])
        model_option, model_choices = options(self.config, 'model')
        effort_option, effort_choices = options(self.config, 'thought_level')
        if not effort_option:
            effort_option, effort_choices = options(self.config, 'effort')
        current = model_option.get('currentValue') if model_option else None
        efforts = [entry['value'] for entry in effort_choices if isinstance(entry.get('value'), str)]
        return {'models': [{'id': entry['value'], 'label': entry.get('name') or entry['value'],
            'efforts': efforts if entry['value'] == current else [], 'images': None}
            for entry in model_choices[:100] if isinstance(entry.get('value'), str)], 'commands': self.commands}

    def run(self, turn, target, directory, session_id=None, rebuild=None):
        resumed = self.ensure_session(session_id)
        if session_id and not resumed:
            turn = rebuild or turn
        if target.get('model'):
            self.set_option('model', target['model'])
        if target.get('effort'):
            item, _ = options(self.config, 'thought_level')
            self.set_option('thought_level' if item else 'effort', target['effort'])
        if turn.images and not self.init.get('agentCapabilities', {}).get('promptCapabilities', {}).get('image'):
            raise AgentError('这个本地 agent 不支持图片输入，请选择支持画面的模型。')
        if turn.purpose == 'chat' and turn.question.lstrip().startswith('/'):
            command = turn.question.strip().split()[0][1:]
            if command not in {item['name'] for item in self.commands}:
                raise AgentError('这个命令不能在学习会话中运行，请使用对话或模型菜单。')
        blocks = [{'type': 'text', 'text': turn.text}]
        blocks.extend({'type': 'image', 'data': image['data'], 'mimeType': image['mime']} for image in turn.images)
        self.parts = []
        self.accept_text = True
        try:
            response = self.rpc('session/prompt', {'sessionId': self.session_id, 'prompt': blocks}, timeout=900)
        except BaseException:
            try:
                self.wire.notify('session/cancel', {'sessionId': self.session_id})
            except AgentError:
                pass
            raise
        finally:
            self.accept_text = False
        text = ''.join(self.parts).strip()
        if not text or response.get('stopReason') in ('cancelled', 'refusal'):
            raise AgentError('本地 agent 没有返回可保存的回答，请检查模型能力。')
        if response.get('stopReason') not in ('end_turn', None):
            text += '\n\n（本次回答因模型限制提前结束。）'
        usage = response.get('usage') or {}
        item, _ = options(self.config, 'model')
        return Result(text, self.session_id,
            {'prompt_tokens': usage.get('inputTokens'), 'completion_tokens': usage.get('outputTokens')},
            item.get('currentValue', '') if item else target.get('model', ''))
