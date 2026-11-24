"""Current source metadata checks, not native or Linux qualification."""
from pathlib import Path
import sys
import pytest
from ops_sim.v5.lifetime_local_capability import local_capability, FORMAT


def test_explicit_reference_and_missing_native_are_separate_permissions():
    source = Path(__file__).resolve().parents[1]
    reference = local_capability(backend='REFERENCE', source=source)
    typed = local_capability(source=source)
    assert reference['format'] == typed['format'] == FORMAT
    assert reference['ready_for_local_pilot'] is (sys.platform == 'win32')
    assert typed['ready_for_local_pilot'] is False
    assert typed['reason'] == 'NATIVE_BUILD_MISSING_NO_FALLBACK'
    assert reference['source_manifest_sha256'] == typed['source_manifest_sha256']
    for result in (reference, typed):
        assert result['ready_for_linux_production'] is False
        assert result['long_dispatch'] is False and result['checkpoint_migration'] is False
        assert result['artifact'] is None and result['current_native_entry_counts'] is None
        assert result['pilot_limits']['hard_seconds'] == 240


def test_reference_cannot_claim_build_and_unknown_backend_has_no_fallback():
    with pytest.raises(ValueError, match='reference cannot claim'):
        local_capability({}, backend='REFERENCE')
    with pytest.raises(ValueError, match='no implicit fallback'):
        local_capability(backend='AUTO')


def test_local_cli_exposes_real_reference_namespace(capsys):
    from m8_lifetime_campaign_cli import main
    result = main(['local-capability', '--backend', 'REFERENCE'])
    assert result['backend'] == 'REFERENCE' and result['long_dispatch'] is False
    assert 'B66_WINDOWS_LOCAL_EXECUTION_CAPABILITY_V1' in capsys.readouterr().out
