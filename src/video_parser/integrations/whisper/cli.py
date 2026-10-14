"""Local GPU transcription CLI; no Gradio server or import required."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__:
    from .runtime import ROOT, load_model
else:
    from runtime import ROOT, load_model


def timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{milliseconds:03}"


def formats_arg(value: str) -> list[str]:
    formats = list(dict.fromkeys(item.strip().lower() for item in value.split(",")))
    if not formats or any(item not in {"txt", "srt", "json"} for item in formats):
        raise argparse.ArgumentTypeError("格式必须为 txt、srt、json，多个格式用逗号分隔")
    return formats


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="video-parser-whisper", description="本地 GPU 语音转文字，无需启动 Gradio。")
    commands = result.add_subparsers(dest="command", required=True)
    transcribe = commands.add_parser("transcribe", help="转录一个或多个本地音频文件")
    transcribe.add_argument("files", nargs="+", type=Path, help="输入文件路径（含空格时用引号包裹）")
    transcribe.add_argument("--language", choices=["auto", "zh", "en"], default="zh", help="识别语言，默认 zh")
    transcribe.add_argument("--format", type=formats_arg, default=["txt", "srt"], help="导出 txt,srt,json；默认 txt,srt")
    transcribe.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "transcriptions", help="输出目录，默认项目 work/exports/cli")
    transcribe.add_argument("--timestamps", action="store_true", help="在终端和 TXT 中显示片段起止时间")
    transcribe.add_argument("--no-vad", action="store_true", help="关闭静音过滤")
    transcribe.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出，仍禁止覆盖输入文件")
    return result


def plan_outputs(args):
    """Reject invalid paths and collisions before loading the GPU model."""
    inputs = [path.expanduser().resolve() for path in args.files]
    outdir = args.output_dir.expanduser().resolve()
    if outdir.exists() and not outdir.is_dir():
        raise ValueError(f"输出路径不是目录：{outdir}")
    seen = set()
    jobs = []
    for source in inputs:
        if not source.is_file():
            raise ValueError(f"输入文件不存在或不是文件：{source}")
        outputs = {}
        for fmt in args.format:
            target = outdir / f"{source.stem}.{fmt}"
            if target.resolve() in inputs:
                raise ValueError(f"输出不能覆盖输入文件：{target}")
            if target in seen:
                raise ValueError(f"批量输入存在同名输出：{target}；请分开运行或重命名输入")
            if target.exists() and (not args.overwrite or not target.is_file()):
                raise ValueError(f"输出已存在：{target}；换目录或使用 --overwrite")
            seen.add(target)
            outputs[fmt] = target
        jobs.append((source, outputs))
    return outdir, jobs


def render(segments, with_timestamps=False):
    lines = []
    for segment in segments:
        text = segment.text.strip()
        if with_timestamps:
            text = f"[{timestamp(segment.start, '.')} --> {timestamp(segment.end, '.')}] {text}"
        lines.append(text)
    text = "\n".join(lines)
    srt = "\n\n".join(
        f"{i}\n{timestamp(segment.start)} --> {timestamp(segment.end)}\n{segment.text.strip()}"
        for i, segment in enumerate(segments, 1)
    )
    return text, srt


def main(argv=None, model=None, initial_load_seconds=0.0):
    args = parser().parse_args(argv)
    try:
        outdir, jobs = plan_outputs(args)
        outdir.mkdir(parents=True, exist_ok=True)
        print("加载 large-v3-turbo（CUDA / int8_float16）…", file=sys.stderr, flush=True)
        started = time.perf_counter()
        provided=model is not None
        if model is None:model=load_model()
        load_seconds=initial_load_seconds if provided else time.perf_counter()-started
        print(f"模型加载：{load_seconds:.2f} 秒", file=sys.stderr, flush=True)
        failures=0
        for source, outputs in jobs:
            try:
                print(f"转录：{source}", file=sys.stderr, flush=True)
                started = time.perf_counter()
                segments, info = model.transcribe(
                    str(source), language=None if args.language == "auto" else args.language,
                    beam_size=5, vad_filter=not args.no_vad, condition_on_previous_text=False,
                    # Auto-detect listens to up to 3 x 30 s of speech, stopping early once a language passes 0.7.
                    language_detection_segments=3, language_detection_threshold=0.7,
                )
                segments = list(segments)
                elapsed = time.perf_counter() - started
                text, srt = render(segments, args.timestamps)
                record = {
                    "source": str(source), "model": "large-v3-turbo", "device": "cuda",
                    "compute_type": "int8_float16", "language": info.language,
                    "duration_seconds": info.duration, "transcription_seconds": elapsed,
                    "model_load_seconds": load_seconds,
                    "text": "\n".join(s.text.strip() for s in segments),
                    "segments": [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments],
                }
                content = {"txt": text, "srt": srt, "json": json.dumps(record, ensure_ascii=False, indent=2)}
                for fmt, target in outputs.items():
                    # Exclusive creation by default also protects files created after preflight.
                    with target.open("w" if args.overwrite else "x", encoding="utf-8", newline="\n") as output:
                        output.write(content[fmt] + ("\n" if content[fmt] else ""))
                    print(f"已保存：{target}", file=sys.stderr, flush=True)
                print(text, flush=True)
                print(f"完成：音频 {info.duration:.2f} 秒，转录 {elapsed:.2f} 秒", file=sys.stderr, flush=True)
            except Exception as error:
                failures+=1
                if 'out of memory' in str(error).lower():print('CUDA out of memory',file=sys.stderr,flush=True)
                print(f"当前文件失败（{type(error).__name__}），继续后续文件。",file=sys.stderr,flush=True)
        return 1 if failures else 0
    except KeyboardInterrupt:
        print("已取消。此前完成的输出会保留。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
