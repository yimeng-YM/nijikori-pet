"""Shared, strict text IO for the desktop pet and its editing tools."""
import codecs
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from collections import deque

MAX_EDIT_BYTES = 16 * 1024 * 1024
BINARY_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.bmp', '.psd',
    '.exe', '.dll', '.zip', '.7z', '.rar', '.gz', '.tar', '.pyz', '.pyc',
    '.pdf', '.docx', '.xlsx', '.pptx', '.mp3', '.mp4', '.avi', '.mov',
    '.wav', '.flac', '.ttf', '.otf', '.woff', '.woff2', '.db', '.sqlite',
    '.class', '.jar', '.so', '.dylib', '.bin', '.dat', '.onnx', '.pt',
}


def _bom_encoding(raw):
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return 'utf-32'
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return 'utf-16'
    if raw.startswith(codecs.BOM_UTF8):
        return 'utf-8-sig'
    return None


def is_probably_binary(path):
    if os.path.splitext(path)[1].lower() in BINARY_EXTS:
        return True
    with open(path, 'rb') as f:
        sample = f.read(8192)
    # UTF-16/32 text legitimately contains NUL bytes.
    return not _bom_encoding(sample) and b'\x00' in sample


def detect_encoding(path):
    """Validate complete streams, including multibyte characters at block edges."""
    with open(path, 'rb') as f:
        bom = _bom_encoding(f.read(4))
    if bom:
        return bom
    for encoding in ('utf-8', 'gb18030'):
        decoder = codecs.getincrementaldecoder(encoding)(errors='strict')
        try:
            with open(path, 'rb') as f:
                for block in iter(lambda: f.read(262144), b''):
                    decoder.decode(block, final=False)
                decoder.decode(b'', final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError('无法可靠解码文本；请指定正确编码，文件未修改')


def read_text_file(path, encoding='auto', max_bytes=MAX_EDIT_BYTES):
    """Return a complete (text, encoding, original bytes) snapshot or fail."""
    if is_probably_binary(path):
        raise ValueError('疑似二进制文件，拒绝按文本处理')
    with open(path, 'rb') as f:
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f'文件超过可编辑上限（{max_bytes} 字节），文件未修改')
    enc = str(encoding or 'auto').strip()
    if enc.lower() in ('auto', 'detect'):
        enc = _bom_encoding(raw)
        if not enc:
            for candidate in ('utf-8', 'gb18030'):
                try:
                    return raw.decode(candidate), candidate, raw
                except UnicodeDecodeError:
                    continue
            raise UnicodeError('无法可靠解码文本；请指定正确编码，文件未修改')
    return raw.decode(enc), enc, raw


def read_text_auto(path, max_bytes=MAX_EDIT_BYTES, encoding='auto'):
    try:
        text, enc, _ = read_text_file(path, encoding, max_bytes)
        return text, enc
    except (OSError, ValueError, UnicodeError, LookupError) as exc:
        return None, str(exc)


def read_text_prefix(path, max_bytes=2_000_000):
    """Bounded search-only prefix; never use the returned text for a rewrite."""
    if is_probably_binary(path):
        raise ValueError('疑似二进制文件，拒绝按文本读取')
    with open(path, 'rb') as f:
        raw = f.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]
    bom = _bom_encoding(raw)
    for enc in ((bom,) if bom else ('utf-8', 'gb18030')):
        try:
            decoder = codecs.getincrementaldecoder(enc)(errors='strict')
            return decoder.decode(raw, final=not truncated), enc, truncated
        except UnicodeDecodeError:
            continue
    raise UnicodeError('无法可靠解码搜索内容')


def atomic_write_bytes(path, data, expected_bytes=None):
    """Write in the destination directory; never truncate the existing file."""
    target = os.path.realpath(os.path.abspath(path))
    folder = os.path.dirname(target)
    fd, temporary = tempfile.mkstemp(prefix='.nijikori-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if expected_bytes is not None:
            with open(target, 'rb') as f:
                if f.read() != expected_bytes:
                    raise RuntimeError('文件在读取后已被其他操作修改，请重新读取后再编辑')
        if os.path.exists(target):
            os.chmod(temporary, os.stat(target).st_mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_text(path, text, encoding='utf-8', expected_bytes=None):
    enc = codecs.lookup(encoding).name
    original = expected_bytes
    if original is None and enc in ('utf-16', 'utf-32') and os.path.isfile(path):
        with open(path, 'rb') as f:
            original = f.read(4)
    # Keep the original UTF-16/32 endianness and BOM on edits.
    if enc == 'utf-16' and original and original.startswith(codecs.BOM_UTF16_BE):
        data = codecs.BOM_UTF16_BE + text.encode('utf-16-be')
    elif enc == 'utf-32' and original and original.startswith(codecs.BOM_UTF32_BE):
        data = codecs.BOM_UTF32_BE + text.encode('utf-32-be')
    else:
        data = text.encode(enc, errors='strict')
    atomic_write_bytes(path, data, expected_bytes)
    return len(data)


def backup_file(path):
    try:
        digest = hashlib.sha256(os.path.normcase(os.path.abspath(path)).encode('utf-8')).hexdigest()[:24]
        directory = os.path.join(tempfile.gettempdir(), 'nijikori_backups', digest)
        os.makedirs(directory, exist_ok=True)
        name = f'{time.time_ns():020d}-{uuid.uuid4().hex}.bak'
        target = os.path.join(directory, name)
        shutil.copy2(path, target)
        for old in sorted(os.listdir(directory))[:-10]:
            if old.endswith('.bak'):
                try:
                    os.unlink(os.path.join(directory, old))
                except OSError:
                    pass
        return target
    except OSError:
        return None


def read_text_page(path, max_chars=12000, offset=None, limit=None,
                   tail=False, encoding='auto', char_offset=0):
    if is_probably_binary(path):
        raise ValueError('疑似二进制文件，拒绝按文本读取')
    enc = detect_encoding(path) if str(encoding or 'auto').lower() in ('auto', 'detect') else encoding
    cap = max(200, min(int(max_chars or 12000), 40000))
    start = max(1, int(offset or 1))
    column = max(0, int(char_offset or 0))
    count_limit = max(0, int(limit or 0))
    tail_rows = deque()
    tail_size = 0
    total = 0
    with open(path, 'r', encoding=enc, errors='strict', newline='') as f:
        for total, raw in enumerate(f, 1):
            if tail and offset is None:
                line = raw.rstrip('\r\n')
                tail_rows.append((total, line))
                tail_size += len(line) + 9
                while len(tail_rows) > 1 and (tail_size > cap or
                        (count_limit and len(tail_rows) > count_limit)):
                    _, removed = tail_rows.popleft()
                    tail_size -= len(removed) + 9
    if tail and offset is None and tail_rows:
        start, first = tail_rows[0]
        column = max(0, len(first) - (cap - 8)) if len(tail_rows) == 1 else 0
    rendered = []
    used = 0
    end = start - 1
    next_offset = None
    next_column = 0
    with open(path, 'r', encoding=enc, errors='strict', newline='') as f:
        for number, raw in enumerate(f, 1):
            if number < start:
                continue
            line = raw.rstrip('\r\n')
            skip = column if number == start else 0
            if skip > len(line):
                raise ValueError('char_offset 超过该行长度，请重新读取该行')
            prefix = f'{number:>6}| '
            room = cap - used - len(prefix) - bool(rendered)
            if room <= 0 or (count_limit and len(rendered) >= count_limit):
                next_offset = number
                break
            piece = line[skip:skip + room]
            rendered.append(prefix + piece)
            used += len(prefix) + len(piece) + (len(rendered) > 1)
            end = number
            if skip + len(piece) < len(line):
                next_offset, next_column = number, skip + len(piece)
                break
    truncated = next_offset is not None
    result = {'status': 'success', 'path': os.path.abspath(path),
              'size': os.path.getsize(path), 'encoding': enc, 'total_lines': total,
              'content': '\n'.join(rendered), 'truncated': truncated,
              'start_line': start, 'end_line': end, 'char_offset': column,
              'next_offset': next_offset, 'next_char_offset': next_column}
    if truncated:
        result['hint'] = (f'共 {total} 行，本次显示第 {start}-{end} 行；'
                          f'续读请带 offset={next_offset}, char_offset={next_column}')
    return result


def fit_text_page(result, serialized_cap):
    """Shrink a page for the model while keeping its continuation cursor exact."""
    page = dict(result)
    while len(json.dumps(page, ensure_ascii=False)) > serialized_cap:
        rows = page['content'].split('\n')
        if len(rows) > 1:
            removed = rows.pop()
            page['next_offset'] = int(removed.partition('| ')[0])
            page['next_char_offset'] = 0
            page['content'] = '\n'.join(rows)
            page['end_line'] = int(rows[-1].partition('| ')[0])
        else:
            prefix, separator, value = rows[0].partition('| ')
            if not separator or len(value) <= 1:
                raise ValueError('分页元数据超过工具输出上限，请使用更短的路径')
            keep = max(1, len(value) // 2)
            page['content'] = prefix + separator + value[:keep]
            page['next_offset'] = int(prefix)
            page['next_char_offset'] = page.get('char_offset', 0) + keep
        page['truncated'] = True
        page['hint'] = (f"续读请带 offset={page['next_offset']}, "
                        f"char_offset={page['next_char_offset']}")
    return page


def copy_destination(source, destination):
    src = os.path.abspath(source)
    dst = os.path.abspath(destination)
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    real_src, real_dst = os.path.realpath(src), os.path.realpath(dst)
    if os.path.normcase(real_src) == os.path.normcase(real_dst):
        raise ValueError('源与目标是同一文件，已取消复制')
    if os.path.isdir(src):
        try:
            inside = os.path.commonpath([real_src, real_dst]) == real_src
        except ValueError:
            inside = False
        if inside:
            raise ValueError('不能把目录复制进自身')
    return dst


def copy_conflicts(source, destination):
    dst = copy_destination(source, destination)
    if not os.path.isdir(source):
        return [dst] if os.path.exists(dst) else []
    conflicts = []
    for folder, _, files in os.walk(source):
        relative = os.path.relpath(folder, source)
        target = os.path.normpath(os.path.join(dst, relative))
        if os.path.exists(target) and not os.path.isdir(target):
            raise ValueError(f'目标文件与目录冲突: {target}')
        for name in files:
            candidate = os.path.join(target, name)
            if os.path.exists(candidate):
                conflicts.append(candidate)
    return conflicts


def safe_copy_file(source, destination, approved_overwrites, backups):
    target = os.path.abspath(destination)
    if os.path.exists(target):
        if os.path.normcase(target) not in approved_overwrites:
            raise FileExistsError(f'目标已存在且未确认覆盖: {target}')
        saved = backup_file(target)
        if not saved:
            raise OSError(f'无法备份目标文件，已取消覆盖: {target}')
        backups[target] = saved
    fd, temporary = tempfile.mkstemp(prefix='.nijikori-copy-', dir=os.path.dirname(target))
    os.close(fd)
    try:
        shutil.copy2(source, temporary)
        # Refuse a destination created after preflight as well.
        if os.path.exists(target) and os.path.normcase(target) not in approved_overwrites:
            raise FileExistsError(f'目标在复制前已出现，已取消覆盖: {target}')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
