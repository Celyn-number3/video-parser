"""Normalize yt-dlp format metadata into the workbench quality menu.

yt-dlp reports every DASH/muxed rendition, including duplicate codecs and
frame rates. The workbench needs one entry per resolution, and it must never
expose the signed media URLs that ride along inside the same format records.
"""

# Compatibility order: H.264 merges into a broadly playable MP4, VP9/AV1 are the
# only renditions YouTube offers above 1080p.
_CODEC_LABELS = (('avc1', 'H.264'), ('h264', 'H.264'), ('hev1', 'H.265'), ('hvc1', 'H.265'),
                 ('vp9', 'VP9'), ('vp09', 'VP9'), ('vp8', 'VP8'), ('av01', 'AV1'))
_CODEC_RANK = {'H.264': 4, 'H.265': 3, 'VP9': 2, 'AV1': 1}


def codec_label(vcodec):
    value = str(vcodec or '').lower()
    for prefix, label in _CODEC_LABELS:
        if value.startswith(prefix):
            return label
    return value.split('.')[0].upper() or '未知'


def _candidates(formats):
    """Video renditions that can actually be archived, newest metadata wins."""
    for item in formats or []:
        if not isinstance(item, dict):
            continue
        width, height = item.get('width'), item.get('height')
        if str(item.get('vcodec') or 'none') == 'none' or not item.get('format_id'):
            continue
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            continue
        # Premium renditions need a paid login; HDR needs decoder support the
        # local player cannot guarantee.
        if 'premium' in str(item.get('format_note') or '').lower():
            continue
        if 'hdr' in str(item.get('dynamic_range') or '').lower():
            continue
        yield item


def _score(item):
    codec = codec_label(item.get('vcodec'))
    protocol = str(item.get('protocol') or '')
    # Direct HTTPS beats the SABR/HLS manifest variants YouTube now publishes at
    # the same resolution: no fragment playlist, no ffmpeg network access.
    # A higher frame rate wins within the same resolution.
    return (_CODEC_RANK.get(codec, 0), 1 if str(item.get('ext') or '') == 'mp4' else 0,
            1 if protocol in ('https', 'http') else 0, item.get('fps') or 0,
            1 if str(item.get('acodec') or 'none') == 'none' else 0, item.get('tbr') or 0)


def renditions(formats):
    """One URL-free option per resolution, highest first; 60fps wins over 30fps."""
    groups = {}
    for item in _candidates(formats):
        groups.setdefault(item['height'], []).append(item)
    options = []
    for height, items in groups.items():
        item = max(items, key=_score)
        width = item['width']
        codec = codec_label(item.get('vcodec'))
        # Label by the short side so a 1080x1920 portrait video reads as 1080p.
        options.append({
            'id': f'{height}p',
            'label': f'{min(width, height)}p' + ('' if codec == 'H.264' else f' · {codec}'),
            'width': width, 'height': height, 'fps': int(round(item.get('fps') or 0)) or None,
            'codec': codec, 'format_id': str(item['format_id']),
            'has_audio': str(item.get('acodec') or 'none') != 'none',
        })
    options.sort(key=lambda option: -option['height'])
    return options
