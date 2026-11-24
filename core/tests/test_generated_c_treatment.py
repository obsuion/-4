"""Precompile byte treatment proofs; these tests never build/load native code."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import pytest

from ops_sim.v5.generated_c_treatment import normalize_generated_c, METHOD, EQUIVALENCE
from ops_sim.v5 import lifecycle_typed_platform as platform


def test_only_terminal_spaces_change_and_complete_token_stream_is_preserved():
    raw = (b'#define M(a) a \\\n  + 1  \n'
           b'const char *s = "inside  ";  \n'
           b'/* comment  */ \t\n// comment \t\nint value = M(2);\t\n')
    normalized, proof = normalize_generated_c(raw)
    assert normalized == (b'#define M(a) a \\\n  + 1\n'
                          b'const char *s = "inside  ";\n'
                          b'/* comment  */\n// comment\nint value = M(2);\n')
    assert proof['format'] == METHOD and proof['equivalence'] == EQUIVALENCE
    assert proof['raw_sha256'] == sha256(raw).hexdigest()
    assert proof['normalized_sha256'] == sha256(normalized).hexdigest()
    assert proof['raw_bytes'] - proof['normalized_bytes'] == proof['removed_bytes']
    assert proof['changed_lines'] == 5 and proof['physical_lines'] == 6
    assert proof['preprocessing_tokens'] > 0
    twice, second = normalize_generated_c(normalized)
    assert twice == normalized and second['removed_bytes'] == second['changed_lines'] == 0
    assert second['preprocessing_sha256'] == proof['preprocessing_sha256']


@pytest.mark.parametrize('raw,expected', [
    (b'int x; \r\n\t\r\n', b'int x;\r\n\r\n'),
    (b'int x; \t', b'int x;'),
    (b'const char *s = "escaped\\\"  "; \n', b'const char *s = "escaped\\\"  ";\n'),
    (b'// existing splice \\\nnot_a_token \nint x;\n', b'// existing splice \\\nnot_a_token\nint x;\n'),
    (b'#include <Python.h> \n#define F(x) #x \n', b'#include <Python.h>\n#define F(x) #x\n'),
])
def test_line_endings_literals_comments_and_directives(raw, expected):
    actual, proof = normalize_generated_c(raw)
    assert actual == expected
    assert raw.count(b'\n') == actual.count(b'\n')
    assert proof['raw_bytes'] == len(raw) and proof['normalized_bytes'] == len(expected)


@pytest.mark.parametrize('raw', [
    b'#define X \\  \nnext\n',
    b'// comment \\ \nnext\n',
    b'const char *x = "invalid  \n";\n',
    b'char x = \'invalid  \n\';\n',
    b'/* never closed \n',
    b'const char *x = "never closed',
    b'const char *x = "trigraph ??/";\n',
    b'int x;\rint y;\n',
    b'int \xffname;\n',
    b'int x;\0\n',
    b'',
])
def test_unsafe_cases_refuse_without_returning_rewritten_bytes(raw):
    before = sha256(raw).digest()
    with pytest.raises(ValueError):
        normalize_generated_c(raw)
    assert sha256(raw).digest() == before


@pytest.mark.parametrize('bad', [bytearray(b'int x;\n'), 'int x;\n', None])
def test_exact_byte_input_required(bad):
    with pytest.raises(ValueError):
        normalize_generated_c(bad)


def _build_data():
    source = Path(__file__).resolve().parents[1]
    raw = (source / 'tests/fixtures/b65_native_receipt_historical.json').read_bytes()
    assert sha256(raw).hexdigest() == '24a66bf3ab5cfbe655e972337f615cafe8e4c87f3bcc49a06b39703ccd5f985d'
    build = json.loads(raw)
    # The test constructs DATA admission only, never a claim that the historical
    # binary was rebuilt. Actual load/build checks have their own native gate.
    build['format'] = platform.TREATED_BUILD_FORMAT
    transform = source / platform.TREATMENT_PATH
    binding = dict(path=platform.TREATMENT_PATH, bytes=transform.stat().st_size,
                   sha256=sha256(transform.read_bytes()).hexdigest())
    build['support_sources'][platform.TREATMENT_PATH] = binding
    normalized, proof = normalize_generated_c(b'int x;  \n')
    proof.update(transform_source=binding, raw_artifact='raw-generated/lifecycle_typed65.c')
    build['generated_c'] = dict(path=platform.GENERATED_PATH, bytes=len(normalized),
                                sha256=sha256(normalized).hexdigest())
    build['generated_c_treatment'] = proof
    return build


def test_new_receipt_requires_complete_treatment_binding():
    build = _build_data()
    assert platform.admit_build_data(build) == build
    old = deepcopy(build); old['format'] = platform.BUILD_FORMAT
    with pytest.raises(ValueError):
        platform.admit_build_data(old)
    missing = deepcopy(build); del missing['generated_c_treatment']
    with pytest.raises(ValueError):
        platform.admit_build_data(missing)


@pytest.mark.parametrize('key,value', [
    ('format', 'other'), ('equivalence', 'claimed'), ('removed_bytes', 0),
    ('changed_lines', True), ('physical_lines', 0), ('preprocessing_tokens', False),
    ('raw_sha256', 'no'), ('normalized_sha256', '0' * 64),
    ('raw_artifact', '../raw.c'),
])
def test_receipt_treatment_drift_refuses(key, value):
    build = _build_data(); build['generated_c_treatment'][key] = value
    with pytest.raises(ValueError):
        platform.admit_build_data(build)


def test_legacy_receipt_reader_stays_strict_and_does_not_invent_treatment():
    source = Path(__file__).resolve().parents[1]
    historical = json.loads((source / 'tests/fixtures/b65_native_receipt_historical.json').read_bytes())
    assert historical['format'] == platform.BUILD_FORMAT
    assert platform.admit_build_data(historical) == historical
    historical['generated_c_treatment'] = {}
    with pytest.raises(ValueError):
        platform.admit_build_data(historical)
