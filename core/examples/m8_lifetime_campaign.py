"""No calculation: show the explicit new B63 bounded PILOT policy."""
from dataclasses import asdict
import json
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,PRODUCTION
if __name__=='__main__':
    p=LifetimeCampaignPolicyV2(mode=PRODUCTION,maximum_primary_segments=8,reserved_diagnostic_slots=2,
        hard_seconds=240,soft_seconds=210,finalization_seconds=30,maximum_journal_records=64)
    print(json.dumps(dict(policy=asdict(p),backend='REFERENCE',execution_mode='PILOT',maximum_pilot_duration_seconds=86400,
        retained_store_reservation_bytes=p.maximum_reserved_job_output_bytes,pool_with_backup_bytes=p.pool_commitment_bytes,
        qualification='SERVER_ACCEPTANCE_PENDING',dispatch=False,
        note='Doctor and immutable common execution admission are required; this does not run a mission or qualify LONG.'),indent=2))
