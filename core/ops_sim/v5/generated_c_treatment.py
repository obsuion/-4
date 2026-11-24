"""Conservative generated-C trailing whitespace treatment, before compilation.

Only spaces and tabs at physical line ends are removed. The transformation
refuses new phase-2 line splices, trigraphs, unclosed comments/literals and
unsupported lexical characters. It compares complete C preprocessing-token
streams after existing line splicing and retains every physical newline.
This is not a general C formatter or a compiler/preprocessor replacement.
"""
from hashlib import sha256
import re

METHOD = 'B66_GENERATED_C_TRAILING_WHITESPACE_V1'
EQUIVALENCE = 'SAME_PHASE2_PREPROCESSING_TOKENS_AND_PHYSICAL_NEWLINES_V1'
MAX_BYTES = 64 * 2**20
_PUNCTUATORS = tuple(sorted((
    b'%:%:', b'>>=', b'<<=', b'...', b'->', b'++', b'--', b'<<', b'>>',
    b'<=', b'>=', b'==', b'!=', b'&&', b'||', b'*=', b'/=', b'%=', b'+=',
    b'-=', b'&=', b'^=', b'|=', b'##', b'<:', b':>', b'<%', b'%>', b'%:',
    b'[', b']', b'(', b')', b'{', b'}', b'.', b'&', b'*', b'+', b'-', b'~',
    b'!', b'/', b'%', b'<', b'>', b'^', b'|', b'?', b':', b';', b'=', b',',
    b'#'), key=len, reverse=True))
_TRIGRAPHS = tuple(b'??' + bytes((c,)) for c in b"=/'()!<>-")
_IDENT_FIRST = b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'
_IDENT = _IDENT_FIRST + b'0123456789'


def _signature(raw):
    """Hash exact preprocessing tokens; no float/model/native operations."""
    if any(t in raw for t in _TRIGRAPHS):
        raise ValueError('generated-C treatment refuses trigraph ambiguity')
    # Translation phase 2 acts before comment/literal recognition. Existing
    # backslash-newline pairs are removed identically in both token streams.
    text = re.sub(rb'\\\r?\n', b'', raw)
    digest = sha256(); count = 0; i = 0; size = len(text)
    while i < size:
        c = text[i]
        if c in b' \t\r\n\v\f':
            i += 1; continue
        if text.startswith(b'/*', i):
            end = text.find(b'*/', i + 2)
            if end < 0:
                raise ValueError('generated-C treatment refuses unclosed comment')
            i = end + 2; continue
        if text.startswith(b'//', i):
            end = text.find(b'\n', i + 2)
            i = size if end < 0 else end + 1; continue
        start = i; kind = b'P'
        literal_prefix = next((p for p in (b'u8', b'u', b'U', b'L', b'')
            if text.startswith(p, i) and i + len(p) < size
            and text[i + len(p)] in (34, 39)), None)
        if literal_prefix is not None:
            i += len(literal_prefix); quote = text[i]; i += 1; kind = b'S'
            while i < size and text[i] != quote:
                if text[i] in (10, 13):
                    raise ValueError('generated-C treatment refuses newline in literal')
                if text[i] == 92:
                    i += 1
                    if i == size:
                        raise ValueError('generated-C treatment refuses incomplete escape')
                i += 1
            if i == size:
                raise ValueError('generated-C treatment refuses unclosed literal')
            i += 1
        elif c in _IDENT_FIRST:
            i += 1; kind = b'I'
            while i < size and text[i] in _IDENT:
                i += 1
        elif 48 <= c <= 57 or (c == 46 and i + 1 < size and 48 <= text[i + 1] <= 57):
            i += 1; kind = b'N'
            while i < size:
                if text[i] in _IDENT or text[i] == 46:
                    i += 1
                elif text[i] in (43, 45) and text[i - 1] in b'eEpP':
                    i += 1
                else:
                    break
        else:
            token = next((p for p in _PUNCTUATORS if text.startswith(p, i)), None)
            if token is None:
                raise ValueError('generated-C treatment refuses unsupported preprocessing character at byte ' + str(i))
            i += len(token)
        token = text[start:i]
        digest.update(kind); digest.update(len(token).to_bytes(8, 'big')); digest.update(token)
        count += 1
    return dict(preprocessing_tokens=count, preprocessing_sha256=digest.hexdigest())


def normalize_generated_c(raw):
    """Return new bytes and a deterministic equivalence report, atomically.

    No file is written here. Invalid input or failed proof returns no output.
    Raw bytes must be retained by the build caller before using the result.
    """
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES or b'\0' in raw:
        raise ValueError('generated-C treatment requires bounded exact bytes')
    if b'\r' in raw.replace(b'\r\n', b''):
        raise ValueError('generated-C treatment refuses lone carriage return')
    result = []; changed = 0; removed = 0
    for line in raw.splitlines(keepends=True):
        if line.endswith(b'\r\n'):
            body, ending = line[:-2], b'\r\n'
        elif line.endswith(b'\n'):
            body, ending = line[:-1], b'\n'
        else:
            body, ending = line, b''
        stripped = body.rstrip(b' \t')
        if stripped != body:
            if stripped.endswith(b'\\'):
                raise ValueError('generated-C treatment refuses new line splice')
            changed += 1; removed += len(body) - len(stripped)
        result.append(stripped + ending)
    normalized = b''.join(result)
    # Vertical-tab/form-feed are C whitespace, not physical line endings.
    # bytes.splitlines also splits there: refuse rather than silently altering.
    expected = re.sub(rb'[ \t]+(?=\r?\n|\Z)', b'', raw)
    if normalized != expected:
        raise ValueError('generated-C treatment refuses unsupported line separator')
    before = _signature(raw); after = _signature(normalized)
    if before != after or re.findall(rb'\r?\n', raw) != re.findall(rb'\r?\n', normalized):
        raise ValueError('generated-C token/preprocessing equivalence failure')
    return normalized, dict(format=METHOD, equivalence=EQUIVALENCE,
        raw_sha256=sha256(raw).hexdigest(), raw_bytes=len(raw),
        normalized_sha256=sha256(normalized).hexdigest(), normalized_bytes=len(normalized),
        changed_lines=changed, removed_bytes=removed,
        physical_lines=raw.count(b'\n') + int(not raw.endswith(b'\n')), **before)
