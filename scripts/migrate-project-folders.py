"""Explicit offline migration of flat Bilibili episode folders into course/Pnnn directories."""
import argparse
import json
from pathlib import Path
import socket

from video_parser.services import library, library_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', type=Path, help='只读预览并保存完整清单，不移动内容')
    mode.add_argument('--apply', type=Path, help='应用已经检查的预览清单')
    mode.add_argument('--resume', help='恢复已记录的迁移 ID')
    mode.add_argument('--undo', help='按迁移 ID 回退；内容有变化时拒绝')
    parser.add_argument('--offline', action='store_true', help='确认本项目服务与所有写入已停止')
    parser.add_argument('--web-port', type=int, default=15001)
    args = parser.parse_args()
    if args.plan:
        result = library_migration.plan()
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        with args.plan.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    else:
        if not args.offline:
            parser.error('先停止服务和所有写入，再指定 --offline；不要在服务运行时迁移。')
        # Do not accept an assertion of offline mode while the official web port is still in use.
        with socket.socket() as probe:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', args.web_port))
        if args.apply:
            result = json.loads(args.apply.read_text(encoding='utf-8'))
        else:
            result = library_migration.read_journal(args.resume or args.undo)
        result = library_migration.execute(result, undo=bool(args.undo), offline=True)
    print(json.dumps({'id': result['id'], 'state': result['state'], 'total_projects': result['total_projects'],
                      'moving_episodes': len(result['entries']),
                      'course_directories': len({str(Path(row['new']).parent) for row in result['entries']}),
                      'files': sum(len(row['inventory']['files']) for row in result['entries']),
                      'bytes': sum(file['size'] for row in result['entries'] for file in row['inventory']['files'].values()),
                      'moves': [{key: row[key] for key in ('project_id', 'old', 'new')} for row in result['entries']],
                      'journal': str(library_migration.journal_path(result['id'])) if result['state'] != 'planned' else None},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
