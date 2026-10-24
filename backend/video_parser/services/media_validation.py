"""Bounded full-integrity cache for repeated video Range requests, never for writes."""
from collections import OrderedDict
import os
from pathlib import Path
import stat
from threading import Lock
import time
from video_parser.services import library

MAX_ENTRIES = 256
TTL = 300
_cache = OrderedDict()
_lock = Lock()


def identity(path):
    """Include NTFS ChangeTime: Windows st_ctime is creation time, not change time."""
    with Path(path).open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode): raise ValueError('Not a regular media file')
        changed = info.st_ctime_ns
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            import msvcrt
            class BasicInfo(ctypes.Structure):
                _fields_ = [('CreationTime', ctypes.c_longlong), ('LastAccessTime', ctypes.c_longlong),
                            ('LastWriteTime', ctypes.c_longlong), ('ChangeTime', ctypes.c_longlong),
                            ('FileAttributes', wintypes.DWORD)]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            handle = msvcrt.get_osfhandle(stream.fileno())
            volume = kernel.GetVolumeInformationByHandleW
            volume.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
            volume.restype = wintypes.BOOL
            filesystem = ctypes.create_unicode_buffer(32)
            if (not volume(handle, None, 0, None, None, None, filesystem, len(filesystem))
                    or filesystem.value not in ('NTFS', 'ReFS')):
                return None  # FAT/network/unknown timestamp semantics must not bypass hashing.
            query = kernel.GetFileInformationByHandleEx
            query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            query.restype = wintypes.BOOL
            basic = BasicInfo()
            if not query(handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)):
                return None  # Unknown filesystem/identity: full verification, never a cache hit.
            if not basic.ChangeTime or not info.st_ino: return None
            changed = basic.ChangeTime
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, changed


def resource(project, relative):
    info = project['resources'].get(relative)
    if not info or info.get('kind') != 'video':
        return library.resource_from_project(project, relative)
    # Always recheck containment, symlinks/junctions and manifest identity before cache lookup.
    path = library.resource_path(project, relative)
    before = identity(path)
    if before is None:
        return library.resource_from_project(project, relative)
    if before[2] != info.get('size_bytes'): raise ValueError('Media size changed')
    key = (str(path.resolve()), before, info.get('sha256'))
    now = time.monotonic()
    with _lock:
        verified = _cache.get(key)
        if verified is not None and now - verified < TTL:
            _cache.move_to_end(key)
            return path
        _cache.pop(key, None)
    path = library.resource_from_project(project, relative)
    # Do not cache a file which changed while its hash was being computed.
    if identity(path) != before: raise ValueError('Media changed during verification')
    with _lock:
        _cache[key] = time.monotonic()
        while len(_cache) > MAX_ENTRIES: _cache.popitem(last=False)
    return path
