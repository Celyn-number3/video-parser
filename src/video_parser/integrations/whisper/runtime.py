from __future__ import annotations

import json
import os
import site
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MODEL_DIR = ROOT / "models" / "whisper" / "large-v3-turbo"
_DLL_HANDLES = []


def configure_runtime():
    """Load project-local NVIDIA DLLs without modifying global PATH."""
    os.environ["TEMP"] = str(ROOT / "cache" / "whisper" / "temp")
    os.environ["TMP"] = os.environ["TEMP"]
    (ROOT / "cache" / "whisper" / "temp").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "whisper" / "hf-cache"))
    os.environ.setdefault("GRADIO_TEMP_DIR", str(ROOT / "cache" / "whisper" / "gradio-temp"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    if os.name == "nt":
        local_config = ROOT / ".local" / "whisper-runtime.json"
        if local_config.exists():
            directory = Path(json.loads(local_config.read_text(encoding="utf-8-sig"))["cuda_dll_dir"])
            if not directory.is_absolute():
                directory = ROOT / directory
            if not directory.is_dir():
                raise RuntimeError(f"CUDA DLL 目录不存在：{directory}")
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        for package_root in site.getsitepackages():
            nvidia = Path(package_root) / "nvidia"
            if nvidia.exists():
                for directory in sorted({p.parent for p in nvidia.rglob("*.dll")}):
                    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
                    _DLL_HANDLES.append(os.add_dll_directory(str(directory)))


def load_model():
    configure_runtime()
    from faster_whisper import WhisperModel
    if not (MODEL_DIR / "model.bin").exists():
        raise RuntimeError("模型尚未下载，请运行 scripts/setup-local-tools.ps1 -DownloadModel")
    return WhisperModel(str(MODEL_DIR), device="cuda", compute_type="int8_float16", cpu_threads=8, num_workers=1, local_files_only=True)
