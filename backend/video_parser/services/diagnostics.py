"""Offline environment checks; no credentials are read or returned."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from video_parser.core.paths import ROOT, CACHE_DIR
from video_parser.services import library,transcription


def write_probe(path):
    try:
        path.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.doctor-',dir=path):pass
        disk=shutil.disk_usage(path)
        return {'writable':True,'free_bytes':disk.free,'low_space':disk.free<2*1024**3}
    except OSError as error:return {'writable':False,'error_type':type(error).__name__}


def checks(deep=False):
    directories={'library':library.LIBRARY_ROOT,'cache':CACHE_DIR,'transcriptions':transcription.OUTPUT_ROOT,'.local':ROOT/'.local'}
    model=transcription.model_directory();manifest_path=transcription.BUNDLED_ROOT/'model-manifest.json'
    try:
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'));files=[]
        for item in manifest['files']:
            path=model/item['path'];present=path.is_file() and not path.is_symlink()
            row={'name':item['path'],'present':present,'size_matches':present and path.stat().st_size==item['size']}
            if deep:row['sha256_matches']=present and library.digest(path)==item['sha256']
            files.append(row)
        model_result={'ready':all(row['size_matches'] and row.get('sha256_matches',True) for row in files),'verification':'full-sha256' if deep else 'presence-and-size-only','files':files}
    except (OSError,ValueError,KeyError):model_result={'ready':False,'error_code':'model_manifest_unavailable'}
    browser={'ready':False}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as manager:
            browser['ready']=Path(manager.chromium.executable_path).is_file()
            if deep and browser['ready']:
                instance=manager.chromium.launch(headless=True);instance.close();browser['launch_verified']=True
    except Exception as error:browser={'ready':False,'error_type':type(error).__name__}
    gpu={'checked':False,'note':'使用 doctor --deep 校验 CUDA 运行时；不切换 CPU。'}
    if deep:
        try:
            script="import json,sys;sys.path.insert(0,sys.argv[1]);from runtime import configure_runtime;configure_runtime();import ctranslate2;print(json.dumps({'device_count':ctranslate2.get_cuda_device_count(),'compute_types':sorted(ctranslate2.get_supported_compute_types('cuda'))}))"
            result=subprocess.run([str(transcription.runtime_python()),'-X','utf8','-c',script,str(transcription.TOOL_ROOT)],capture_output=True,text=True,encoding='utf-8',timeout=30)
            gpu={'checked':True,'ready':False}
            if result.returncode==0:
                gpu.update(json.loads(result.stdout));gpu['ready']=gpu['device_count']>0 and 'int8_float16' in gpu['compute_types']
            else:gpu['error_code']='cuda_runtime_unavailable'
        except (OSError,ValueError,subprocess.SubprocessError):gpu={'checked':True,'ready':False,'error_code':'cuda_probe_failed'}
    return {'storage':{name:write_probe(path) for name,path in directories.items()},'whisper_model':model_result,
            'browser':browser,'cuda':gpu,'network_used':False,
            'note':'普通检查只检查文件存在与大小，不代表哈希完整性；--deep 会完整校验模型 SHA-256、启动无网页浏览器并检查本机 CUDA。'}
