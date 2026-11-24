"""Actual Windows local PILOT capability, separate from Linux production.

This is a read-only build/runtime/source check, not day acceptance or dispatch.
Each actual store still passes the existing execution-authority gate.
"""
from pathlib import Path
from hashlib import sha256
import sys
from .lifecycle_backend import runtime_binding
from .lifecycle_typed_platform import (METHOD, WINDOWS, admit_build_data, admit_typed_build)
from .lifetime_policy import QUALIFICATION
from .lifetime_execution_authority import (PILOT_SECONDS, PILOT_PRIMARY_SEGMENTS,
    PILOT_DIAGNOSTIC_SLOTS, PILOT_HARD_SECONDS)
from .portable_job import canonical, source_manifest

FORMAT = 'B66_WINDOWS_LOCAL_EXECUTION_CAPABILITY_V1'


def local_capability(build=None, *, source=None, backend=METHOD):
    source = Path(__file__).resolve().parents[2] if source is None else Path(source).resolve()
    manifest = source_manifest(source)
    if type(backend) is not str or backend not in ('REFERENCE', METHOD):
        raise ValueError('explicit local reference or typed backend; no implicit fallback')
    receipt = module = None
    if backend == 'REFERENCE':
        if build is not None:
            raise ValueError('reference cannot claim a native build')
        ready = sys.platform == 'win32'
        reason = 'WINDOWS_REFERENCE_LOCAL_PILOT_NO_NATIVE_CLAIM'
    elif build is None:
        ready = False
        reason = 'NATIVE_BUILD_MISSING_NO_FALLBACK'
    else:
        receipt = admit_build_data(build)
        module = admit_typed_build(receipt, source=source)
        ready = sys.platform == 'win32' and receipt['profile'] == WINDOWS
        reason = 'WINDOWS_ONLY_LOCAL_QUALIFICATION' if ready else 'USE_SEPARATE_LINUX_SERVER_TARGET_QUALIFICATION'
    return dict(format=FORMAT, backend=backend, source_manifest_sha256=sha256(canonical(manifest)).hexdigest(),
        runtime=runtime_binding(), profile=None if receipt is None else receipt['profile'],
        artifact=None if receipt is None else receipt['artifact'],
        build_sha256=None if receipt is None else sha256(canonical(receipt)).hexdigest(),
        hardware_caps=None if receipt is None else receipt['capabilities']['limits'],
        current_native_entry_counts=None if module is None else module.native_entry_counts(),
        policy_namespace=QUALIFICATION, entrypoint='m8_lifetime_campaign_cli.py',
        operations=['prepare', 'admit', 'chain-run', 'status', 'stop', 'resume', 'diagnostic', 'export-result', 'inspect-result'],
        ready_for_local_pilot=ready, ready_for_linux_production=False, long_dispatch=False,
        pilot_limits=dict(duration_seconds=PILOT_SECONDS, primary_segments=PILOT_PRIMARY_SEGMENTS,
            diagnostic_slots=PILOT_DIAGNOSTIC_SLOTS, hard_seconds=PILOT_HARD_SECONDS, cleanup_seconds=2),
        store_gate='Actual immutable input/source/build/runtime/policy/owned-settlement required at every dispatch',
        qualification='METADATA_ONLY_NOT_SCIENCE_OR_LINUX_ACCEPTANCE', checkpoint_migration=False,
        reason=reason)
