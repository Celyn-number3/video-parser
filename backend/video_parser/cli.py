"""Command-line adapter: arguments, output formatting and exit codes only."""
import argparse
from contextlib import redirect_stdout
import json
import re
import sys

from video_parser.services import videos

COMMANDS = videos.COMMANDS


def execute(args):
    if args.command=='doctor':
        result=videos.doctor()
        if args.deep:
            from video_parser.services import diagnostics
            result['environment_checks']=diagnostics.checks(deep=True)
        return result
    if args.command=='transcribe-batch':
        from video_parser.services import transcription
        return transcription.transcribe_batch(args.files,args.language,args.output_dir,args.timestamps)
    options = {name: value for name, value in vars(args).items() if name != 'json'}
    return videos.execute(videos.VideoRequest(**options))


def positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('需要正整数。')
    if number < 1:
        raise argparse.ArgumentTypeError('需要正整数。')
    return number


def quality_argument(value):
    if value in ('best', 'default'): return value
    if re.fullmatch(r'[1-9]\d{1,4}p?', value): return value.rstrip('p') + 'p'
    # High frame-rate renditions keep their exact identifier, e.g. 1080p60.
    if re.fullmatch(r'[1-9]\d{1,4}p(?:24|25|30|48|50|60)', value): return value
    raise argparse.ArgumentTypeError('清晰度应为best/default或实际可用画质，例如720p、1080p60。')


def build_parser():
    parser = argparse.ArgumentParser(description='视频解析、下载和画面分析 CLI（无需启动 Web 服务）')
    parser.add_argument('--json', action='store_true', help='输出供程序读取的 JSON')
    commands = parser.add_subparsers(dest='command', required=True)
    for name, description in COMMANDS.items():
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
        if name in ('parse', 'download', 'cover', 'frames', 'analyze', 'play', 'transcribe'):
            command.add_argument('source', help='本地音频或视频文件路径' if name == 'transcribe' else '分享链接/文本，或命令支持的本地视频路径')
        if name in ('download', 'cover', 'frames', 'analyze'):
            command.add_argument('--output', '-o', help='输出文件；frames 命令中为新的画面目录')
        if name in ('parse', 'download', 'analyze'):
            command.add_argument('--quality', type=quality_argument, default='best', help='best 或实际可用清晰度，例如720p、1080p60；平台未提供的画质会被拒绝')
        if name in ('download', 'cover', 'analyze', 'transcribe'):
            command.add_argument('--output-dir', default=None, help='显式指定输出目录；转录默认使用 outputs/transcriptions，其余默认按视频归档到 outputs')
        if name=='doctor':
            command.add_argument('--deep',action='store_true',help='离线完整校验模型哈希、CUDA、浏览器与可写空间；不联网')
        if name=='transcribe-batch':
            command.add_argument('files',nargs='+',help='多个本地音视频文件；失败隔离，输出分别归档')
            command.add_argument('--output-dir',default=None,help='批次输出目录；不会覆盖已有文件')
        if name in ('transcribe','transcribe-batch'):
            command.add_argument('--language', choices=('auto', 'zh', 'en'), default='auto', help='识别语言，默认自动检测')
            command.add_argument('--timestamps', action='store_true', help='在 TXT 中显示片段级时间戳')
        if name == 'frames':
            command.add_argument('--count', type=positive_int, default=8, help='提取帧数（默认 8）')
        if name == 'analyze':
            command.add_argument('--frames', type=positive_int, help='分析帧数（默认 MAX_FRAMES 或 8）')
            command.add_argument('--prompt', help='自定义画面分析问题')
        if name == 'list':
            command.add_argument('--directory', help='仅列出该目录下的视频')
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = build_parser().parse_args(argv)
    try:
        # 现有解析器与 AI 工具会打印进度；stdout 仅留给最终结果。
        with redirect_stdout(sys.stderr):
            videos.load_environment()
            result = execute(args)
        output = {'ok': not (args.command=='transcribe-batch' and result.get('failed')), 'command': args.command, **result}
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        message = str(error) or type(error).__name__
        print(f'错误：{message}', file=sys.stderr)
        if args.json:
            print(json.dumps({'ok': False, 'command': args.command, 'error': message}, ensure_ascii=False))
        return 1
    if args.json:
        print(json.dumps(output, ensure_ascii=False))
    else:
        for key, value in result.items():
            print(f'{key}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)}')
    return 1 if args.command=='transcribe-batch' and result.get('failed') else 0
