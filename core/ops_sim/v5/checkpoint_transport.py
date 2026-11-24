"""Versioned lossless checkpoint transport; canonical bytes retain authority.

This module imports no model/checkpoint owner. Its output must still pass the
existing strict checkpoint admission. The encoded receipt is administrative
DATA, never an execution or restoration permission.
"""
from hashlib import sha256
from pathlib import Path
import json
import re
import struct
import zlib

FORMAT = 'YEAR_V4_LOSSLESS_CHECKPOINT_TRANSPORT_V1'
LEGACY_FORMAT = 'YEAR_V4_LEGACY_CANONICAL_CHECKPOINT_RAW_V1'
MAGIC = b'KAZE-CP\x00\x01'
PREFIX = struct.Struct('>I')
MAX_HEADER_BYTES = 16384
MAX_DECODED_BYTES = 64 * 2**20
MAX_FRAMING_BYTES = len(MAGIC) + PREFIX.size + MAX_HEADER_BYTES
RAW = 'RAW_V1'
ZLIB3 = 'ZLIB_LEVEL3_V1'
ZSTD = 'ZSTD_LEVEL3_SINGLE_THREAD_V1'
CODECS = (RAW, ZLIB3, ZSTD)
HEADER_FIELDS = frozenset(('format', 'version', 'codec', 'role', 'bindings',
    'checkpoint_format', 'decoded_maximum_bytes', 'decoded_bytes',
    'decoded_sha256', 'payload_bytes', 'payload_sha256'))
RECEIPT_FIELDS = frozenset(('format', 'codec', 'role', 'bindings',
    'decoded_bytes', 'decoded_sha256', 'encoded_bytes', 'encoded_sha256'))


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('checkpoint transport duplicate header field')
        out[key] = value
    return out


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('checkpoint transport exact integer: ' + name)
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('checkpoint transport SHA256')
    return value


def _bindings(value):
    if type(value) is not dict or not value or len(_raw(value)) > 8192:
        raise ValueError('checkpoint transport bounded bindings')
    _hash(value.get('root_identity'))
    _hash(value.get('source_identity'))
    # Freeze caller-owned dictionaries in the returned DATA receipt.
    return json.loads(_raw(value), object_pairs_hook=_pairs)


def _role(value):
    if type(value) is not str or re.fullmatch('[A-Z][A-Z0-9_]{0,63}', value) is None:
        raise ValueError('checkpoint transport role')
    return value


def _checkpoint_format(raw):
    # Canonical checkpoints put format before graph. Decode only preceding
    # top-level members, avoiding a second materialization of the dynamic graph.
    text = raw.decode('utf8')
    decoder = json.JSONDecoder(object_pairs_hook=_pairs)
    if not text.startswith('{'):
        raise ValueError('checkpoint transport canonical checkpoint object')
    pos = 1
    while pos < len(text):
        key, pos = decoder.raw_decode(text, pos)
        if type(key) is not str or text[pos:pos + 1] != ':':
            raise ValueError('checkpoint transport canonical checkpoint member')
        value, pos = decoder.raw_decode(text, pos + 1)
        if key == 'format':
            if type(value) is not str or re.fullmatch('[A-Z0-9_]{1,160}', value) is None:
                raise ValueError('checkpoint transport scientific format')
            return value
        if text[pos:pos + 1] != ',':
            break
        pos += 1
    raise ValueError('checkpoint transport missing scientific format')


def is_transport(value):
    return type(value) is bytes and value.startswith(MAGIC)


def _receipt(encoded, header):
    return dict(format=FORMAT, codec=header['codec'], role=header['role'],
        bindings=header['bindings'], decoded_bytes=header['decoded_bytes'],
        decoded_sha256=header['decoded_sha256'], encoded_bytes=len(encoded),
        encoded_sha256=sha256(encoded).hexdigest())


def encode_checkpoint(raw, bindings, role, *, codec=ZLIB3,
                      maximum_decoded_bytes=MAX_DECODED_BYTES):
    """Return bounded transport and receipt; incompressible input uses RAW_V1.

    zstd is optional and imported only on an explicit codec request. No extra
    compressor threads are requested. The producer selects one independent frame.
    """
    limit = _integer(maximum_decoded_bytes, 'decoded maximum', 1, MAX_DECODED_BYTES)
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ValueError('checkpoint transport producer byte limit')
    binding = _bindings(bindings)
    _role(role)
    if type(codec) is not str or codec not in CODECS:
        raise ValueError('checkpoint transport codec/version')
    if codec == ZLIB3:
        payload = zlib.compress(raw, 3)
    elif codec == ZSTD:
        from compression import zstd
        payload = zstd.compress(raw, level=3)
    else:
        payload = raw
    if len(payload) >= len(raw):
        codec, payload = RAW, raw
    header = dict(format=FORMAT, version=1, codec=codec, role=role,
        bindings=binding, checkpoint_format=_checkpoint_format(raw),
        decoded_maximum_bytes=len(raw), decoded_bytes=len(raw),
        decoded_sha256=sha256(raw).hexdigest(), payload_bytes=len(payload),
        payload_sha256=sha256(payload).hexdigest())
    hraw = _raw(header)
    if len(hraw) > MAX_HEADER_BYTES:
        raise ValueError('checkpoint transport header byte limit')
    encoded = MAGIC + PREFIX.pack(len(hraw)) + hraw + payload
    if len(encoded) > len(raw) + MAX_FRAMING_BYTES:
        raise ValueError('checkpoint transport worst-case framing bound')
    return encoded, _receipt(encoded, header)


def decode_checkpoint(encoded, expected_sha256, expected_bindings,
                      maximum_decoded_bytes=MAX_DECODED_BYTES, expected_role=None):
    """Decode with bounded output, then verify raw SHA and complete bindings.

    Legacy raw JSON is deliberately a separate branch. This function does not
    replace strict scientific schema/graph admission in lifecycle_checkpoint.
    """
    limit = _integer(maximum_decoded_bytes, 'decoded maximum', 1, MAX_DECODED_BYTES)
    _hash(expected_sha256)
    binding = _bindings(expected_bindings)
    if expected_role is not None:
        _role(expected_role)
    if type(encoded) is not bytes or not 0 < len(encoded) <= limit + MAX_FRAMING_BYTES:
        raise ValueError('checkpoint transport encoded byte limit')
    if not is_transport(encoded):
        if len(encoded) > limit or not encoded.startswith(b'{') or sha256(encoded).hexdigest() != expected_sha256:
            raise ValueError('checkpoint transport legacy raw SHA/byte admission')
        return encoded, dict(format=LEGACY_FORMAT, codec='RAW_LEGACY_V1',
            role=expected_role or 'LEGACY_UNSPECIFIED', bindings=binding,
            decoded_bytes=len(encoded), decoded_sha256=expected_sha256,
            encoded_bytes=len(encoded), encoded_sha256=expected_sha256)
    start = len(MAGIC)
    if len(encoded) < start + PREFIX.size:
        raise ValueError('checkpoint transport truncated prefix')
    size = PREFIX.unpack_from(encoded, start)[0]
    if not 1 <= size <= MAX_HEADER_BYTES or start + PREFIX.size + size >= len(encoded):
        raise ValueError('checkpoint transport header length')
    start += PREFIX.size
    hraw = encoded[start:start + size]
    try:
        header = json.loads(hraw, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('checkpoint transport header JSON') from error
    if type(header) is not dict or set(header) != HEADER_FIELDS or _raw(header) != hraw:
        raise ValueError('checkpoint transport exact canonical header')
    if header['format'] != FORMAT or type(header['version']) is not int or header['version'] != 1:
        raise ValueError('checkpoint transport format/version')
    if type(header['codec']) is not str or header['codec'] not in CODECS:
        raise ValueError('checkpoint transport codec/version')
    _role(header['role'])
    if expected_role is not None and header['role'] != expected_role:
        raise ValueError('checkpoint transport foreign checkpoint role')
    if _bindings(header['bindings']) != binding:
        raise ValueError('checkpoint transport foreign root/source/bindings')
    declared_max = _integer(header['decoded_maximum_bytes'], 'declared maximum', 1, limit)
    size = _integer(header['decoded_bytes'], 'decoded length', 1, declared_max)
    _hash(header['decoded_sha256']); _hash(header['payload_sha256'])
    if header['decoded_sha256'] != expected_sha256:
        raise ValueError('checkpoint transport foreign checkpoint SHA')
    payload = encoded[start + len(hraw):]
    if _integer(header['payload_bytes'], 'payload length', 1, size) != len(payload) or sha256(payload).hexdigest() != header['payload_sha256']:
        raise ValueError('checkpoint transport encoded length/SHA')
    if header['codec'] == RAW:
        raw = payload
    elif header['codec'] == ZLIB3:
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(payload, size + 1)
        except zlib.error as error:
            raise ValueError('checkpoint transport invalid zlib frame') from error
        if len(raw) > size or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
            raise ValueError('checkpoint transport truncated/extra/oversized zlib frame')
    else:
        from compression import zstd
        decoder = zstd.ZstdDecompressor(options={
            zstd.DecompressionParameter.window_log_max: max(10, (limit - 1).bit_length())})
        try:
            raw = decoder.decompress(payload, max_length=size + 1)
        except zstd.ZstdError as error:
            raise ValueError('checkpoint transport invalid zstd frame') from error
        if len(raw) > size or not decoder.eof or decoder.unused_data:
            raise ValueError('checkpoint transport truncated/extra/oversized zstd frame')
    if len(raw) != size or sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('checkpoint transport decoded exact length/SHA')
    if _checkpoint_format(raw) != header['checkpoint_format']:
        raise ValueError('checkpoint transport scientific format binding')
    return raw, _receipt(encoded, header)


def read_checkpoint(path_or_bytes, root, expected_sha256, expected_bindings,
                    expected_role=None):
    """Bound the file read; retain the original bytes/str/Path public domain."""
    limit = min(MAX_DECODED_BYTES, root.policy.max_checkpoint_bytes,
                root.policy.max_working_bytes)
    if type(path_or_bytes) is bytes:
        data = path_or_bytes
    else:
        if type(path_or_bytes) is not str and not isinstance(path_or_bytes, Path):
            raise TypeError('checkpoint transport bytes or explicit local path required')
        path = Path(path_or_bytes)
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit + MAX_FRAMING_BYTES:
            raise ValueError('checkpoint transport bounded existing file required')
        with path.open('rb') as stream:
            data = stream.read(limit + MAX_FRAMING_BYTES + 1)
    return decode_checkpoint(data, expected_sha256, expected_bindings, limit, expected_role)
