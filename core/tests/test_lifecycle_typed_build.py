"""Build admission/recipe tests only; no compiler, Cython or model launches."""
from copy import deepcopy
from pathlib import Path

import pytest

from ops_sim.v5 import lifecycle_typed_build as owner
from ops_sim.v5 import lifecycle_typed_backend as backend
from test_lifecycle_typed_backend import receipt


def prepared(tmp_path):
    root=tmp_path/'isolated-build-source';here=root/'ops_sim'/'v5';here.mkdir(parents=True)
    (here/'lifecycle_typed.pyx').write_text(''.join('include "'+Path(name).name+'"\n'
        for name in backend.INCLUDE_PATHS),encoding='utf8')
    for name in owner.BUILD_SUPPORT_PATHS:(root/name).write_bytes(b'# synthetic support input only\n')
    (here/'lifecycle_typed_world.pxi').write_text('include "lifecycle_typed_world65.pxi"\n',encoding='utf8')
    return root,here,tmp_path/'new-build-evidence',receipt()['runtime']


def test_admission_has_no_writes_and_uses_new_distinct_output_paths(tmp_path):
    root,here,evidence,runtime=prepared(tmp_path)
    before={p.relative_to(root).as_posix():p.read_bytes()for p in root.rglob('*')if p.is_file()}
    outputs=owner.admit_attempt(here,evidence,runtime,backend.FULL_DOMAIN,160)
    assert [p.name for p in outputs]==['lifecycle_typed.c','_lifecycle_typed.cp314-win_amd64.pyd','lifecycle_typed_build_receipt.json']
    assert not evidence.exists() and not any(p.exists()for p in outputs)
    assert before=={p.relative_to(root).as_posix():p.read_bytes()for p in root.rglob('*')if p.is_file()}
    assert owner.admit_attempt(here,evidence,runtime,backend.SUPPORT_DOMAIN,1)==outputs


@pytest.mark.parametrize('which',('evidence','generated','artifact','receipt'))
def test_any_existing_attempt_is_preserved_without_overwrite(tmp_path,which):
    root,here,evidence,runtime=prepared(tmp_path)
    outputs=owner.output_paths(here,runtime)
    if which=='evidence':evidence.mkdir();path=evidence/'old-log.txt'
    else:path=outputs[('generated','artifact','receipt').index(which)]
    path.write_bytes(b'KEEP ORIGINAL FAILED ATTEMPT')
    with pytest.raises(ValueError,match='refuses overwrite'):
        owner.admit_attempt(here,evidence,runtime,backend.FULL_DOMAIN,160)
    assert path.read_bytes()==b'KEEP ORIGINAL FAILED ATTEMPT'


@pytest.mark.parametrize('seconds',(True,False,0,161,1.0,'160',None))
def test_build_deadline_is_exact_and_finite(tmp_path,seconds):
    root,here,evidence,runtime=prepared(tmp_path)
    with pytest.raises(ValueError,match='compiler deadline'):
        owner.admit_attempt(here,evidence,runtime,backend.FULL_DOMAIN,seconds)
    assert not evidence.exists()


@pytest.mark.parametrize('domain',(None,True,'PREPARED_NATIVE','B63_PREPARED_NATIVE_V1'))
def test_no_implicit_build_execution_domain(tmp_path,domain):
    root,here,evidence,runtime=prepared(tmp_path)
    with pytest.raises(ValueError,match='build domain'):owner.admit_attempt(here,evidence,runtime,domain,160)
    assert not evidence.exists()


def test_compiler_command_has_exact_ordered_no_fast_math_or_fma_recipe(tmp_path):
    command=owner.compiler_command(tmp_path/'zig.exe',tmp_path/'lifecycle_typed.c',tmp_path/'typed.pyd',tmp_path/'python')
    assert command[1:1+len(backend.FLAGS)]==list(backend.FLAGS)
    assert command==[str(tmp_path/'zig.exe'),*backend.FLAGS,'-I',str(tmp_path/'python'/'include'),
        str(tmp_path/'lifecycle_typed.c'),str(tmp_path/'python'/'libs/python314.lib'),'-o',str(tmp_path/'typed.pyd')]
    assert '-fno-fast-math'in command and '-ffp-contract=off'in command and '-fno-associative-math'in command
    assert not any(flag in command for flag in ('-ffast-math','-Ofast','-ffp-contract=fast'))


@pytest.mark.parametrize('declaration',(
    'include "lifecycle_typed_quiet.pxi"\ninclude "lifecycle_typed_world.pxi"\n',
    'include "lifecycle_typed_world.pxi"\ninclude "outside.pxi"\n',
    'include "lifecycle_typed_world.pxi"\n',
    'include SOME_DYNAMIC_PATH\n'))
def test_unknown_missing_reordered_or_nonliteral_include_fails_before_outputs(tmp_path,declaration):
    root,here,evidence,runtime=prepared(tmp_path)
    (here/'lifecycle_typed.pyx').write_text(declaration,encoding='utf8')
    with pytest.raises(ValueError,match='include'):
        owner.admit_attempt(here,evidence,runtime,backend.FULL_DOMAIN,160)
    assert not evidence.exists() and not any(p.exists()for p in owner.output_paths(here,runtime))


@pytest.mark.parametrize('include',backend.INCLUDE_PATHS)
def test_unbound_transitive_include_refused_before_outputs(tmp_path,include):
    root,here,evidence,runtime=prepared(tmp_path)
    (root/include).write_text('include "unbound.pxi"\n',encoding='utf8')
    with pytest.raises(ValueError,match='transitive'):
        owner.admit_attempt(here,evidence,runtime,backend.FULL_DOMAIN,160)
    assert not evidence.exists()


@pytest.mark.parametrize('missing',owner.BUILD_SUPPORT_PATHS)
def test_missing_support_source_refuses_before_build_outputs(tmp_path,missing):
    root,here,evidence,runtime=prepared(tmp_path);(root/missing).unlink()
    with pytest.raises(ValueError,match='support source missing'):
        owner.admit_attempt(here,evidence,runtime,backend.FULL_DOMAIN,160)
    assert not evidence.exists() and not any(p.exists()for p in owner.output_paths(here,runtime))
