"""Finite 90-day DATA preparation using the existing V5 serial executor.

P64/P96 are fresh-store proposals, not migration, completion or disk-capacity
proofs. This module does not implement a numerical engine or a launcher.
"""
from dataclasses import asdict
from hashlib import sha256
import json

FORMAT = 'CORE_90D_V6_PREPARED_SERIAL_JOB_V1'
CAPACITY = 'CORE_90D_V6_FINITE_CAPACITY_PROPOSAL_V1'
GROUP = 'CORE_90D_V6_FIVE_STUDY_CAPACITY_V1'
DAY_OBSERVATION = 'CORE_90D_V6_BOUND_DAY_OBSERVATION_V1'
DURATION = 90 * 86400
ANCHOR = 128
TARGET = ANCHOR + DURATION
MAX_BYTES = 32 * 2**20
PROFILES = ('P64', 'P96')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf8')


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names) or any(type(k) is not str for k in value):
        raise ValueError('90D exact DATA fields')


def _integer(value, name, low=0, high=2**63-1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('90D finite exact integer: ' + name)
    return value


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('90D exact SHA256 identity')
    return value


def policy_for(profile_id):
    """Construct an existing exact policy; never change an existing store."""
    from .lifetime_policy import LifetimeCampaignPolicyV2, METHOD_PACKED, WINDOWS_USER
    if type(profile_id) is not str or profile_id not in PROFILES:
        raise ValueError('90D explicit P64 or P96 proposal required')
    primary = 64 if profile_id == 'P64' else 96
    return LifetimeCampaignPolicyV2(method=METHOD_PACKED, mode=WINDOWS_USER,
        maximum_primary_segments=primary, reserved_diagnostic_slots=2,
        hard_seconds=900, soft_seconds=840, finalization_seconds=60, cleanup_seconds=2,
        maximum_observed_primary_seconds=primary*902, maximum_diagnostic_seconds=2*902,
        maximum_journal_records=512, maximum_journal_record_bytes=4096)


def capacity_proposal(profile_id):
    """Read finite dimensions from actual owners, with no capacity guarantee."""
    from . import lifetime_physical_storage as physical
    from . import lifetime_packed_status as packed
    from . import lifetime_incremental_pool as pool
    from . import lifetime_result as result
    policy = policy_for(profile_id)
    contract = physical.contract(policy)
    jobs = policy.maximum_jobs
    return dict(format=CAPACITY, profile=profile_id, policy=asdict(policy),
        policy_identity=policy.identity, duration_seconds=DURATION,
        original_anchor_seconds=ANCHOR, target_seconds=TARGET,
        physical_contract=contract,
        scientific_jobs=jobs,
        coarse_output=dict(all_jobs_at_full_output_bytes=jobs*policy.maximum_output_bytes,
            policy_sum_with_initial_and_metadata_bytes=policy.maximum_reserved_job_output_bytes,
            all_full_job_outputs_fit_retained_cap=jobs*policy.maximum_output_bytes <= contract['global_retained_cap_bytes'],
            interpretation='Independent per-job maxima do not prove completion under the smaller cumulative retained cap; settled actual bytes and each next reservation remain binding.'),
        journal=dict(maximum_records=policy.maximum_journal_records,
            maximum_record_bytes=policy.maximum_journal_record_bytes,
            reserved_payload_bytes=policy.maximum_journal_records*policy.maximum_journal_record_bytes,
            minimum_policy_admission_records=2*jobs+16,
            actual_extra_controls_and_recovery_records='RUNTIME_GUARDED_NOT_ASSUMED_FREE'),
        namespace=dict(maximum_operations=physical.MAX_OPERATIONS,
            maximum_cumulative_file_names=physical.MAX_FILES,
            maximum_owner_pages=physical.MAX_DATABASE_PAGES,
            owner_page_bytes=physical.DATABASE_PAGE_BYTES,
            prospective_file_slots_per_active_segment=physical.PACKED_SEGMENT_FILES,
            mutable_names_per_segment=physical.PACKED_MUTABLE_FILES,
            reserved_metadata_pages_per_unsettled_segment=physical.PACKED_SEGMENT_METADATA_PAGES,
            all_jobs_at_full_file_grant=jobs*physical.PACKED_SEGMENT_FILES,
            all_full_file_grants_fit=jobs*physical.PACKED_SEGMENT_FILES <= physical.MAX_FILES,
            all_full_file_grants_are_not_a_completion_bound=True,
            normal_settlement='Original page escrow is released after all three mutable names exist; SEALED alone is not sufficient.',
            actual_admission='Cumulative claimed/retired names + mutable names + outstanding reservations + next grant; actual pages + outstanding page escrow + next grant.'),
        per_job_packed=dict(maximum_objects=packed.MAX_OBJECTS,
            terminal_objects=packed.TERMINAL_OBJECTS, maximum_blocks=packed.MAX_BLOCKS,
            block_bytes=packed.BLOCK_BYTES, maximum_packed_bytes=packed.MAX_BYTES,
            maximum_index_pages=packed.INDEX_PAGES, index_page_bytes=packed.INDEX_PAGE_BYTES,
            maximum_index_bytes=packed.INDEX_BYTES,
            terminal_blocks=packed.TERMINAL_BLOCKS, terminal_bytes=packed.TERMINAL_BYTES,
            terminal_index_pages=packed.TERMINAL_INDEX_PAGES),
        readonly_export=dict(physical_public_operation_cap_bytes=contract['maximum_export_operation_bytes'],
            result_reader_hard_cap_bytes=result.MAX_BYTES, maximum_result_files=result.MAX_FILES,
            manifest_reserve_bytes=result.MAX_MANIFEST,
            maximum_scientific_endpoint_members=jobs,
            required_check='Initial DATA + every retained per-job scientific endpoint + view + manifest must fit the physical public cap; a 512MiB reader cap does not grant 512MiB export.'),
        shared_pool=dict(maximum_studies=pool.MAX_STUDIES,
            conservative_metadata_bytes=pool.POOL_METADATA_BYTES),
        status='FINITE_PROPOSAL_WITH_ENFORCED_HALT_NOT_COMPLETION_PROOF',
        unknown_terms=['Future actions, physical regimes and per-segment work/duration.',
            'Actual cumulative names/operations/page growth and packed publication density.',
            'Cumulative retained scientific bytes, endpoint export size and additional control journal records.',
            'Current free space and commitments of other stores in the real shared pool.'],
        runtime_admission_required=True, unknown_producer_requires_halt=True,
        backup='RESERVED_NOT_CREATED', completion_proved=False,
        year_capacity='NOT_ESTABLISHED')


def group_capacity_proposal(profile_ids):
    """Conservative commitment for five studies; no allocation or disk query."""
    if type(profile_ids) not in (tuple, list) or len(profile_ids) != 5:
        raise ValueError('90D exactly five explicitly selected profiles')
    rows = [capacity_proposal(p) for p in profile_ids]
    studies = sum(p['physical_contract']['whole_study_commitment_bytes'] for p in rows)
    metadata = max(p['shared_pool']['conservative_metadata_bytes'] for p in rows)
    return dict(format=GROUP, profiles=list(profile_ids), study_count=5,
        whole_study_commitments_bytes=studies, shared_metadata_added_bytes=metadata,
        conservative_group_commitment_bytes=studies+metadata,
        per_study_commitment_bytes=[p['physical_contract']['whole_study_commitment_bytes'] for p in rows],
        metadata_scope='Conservatively added once without subtracting any overlap in per-owner metadata reserves.',
        status='PROSPECTIVE_COMMITMENT_NOT_FREE_SPACE_OR_COMPLETION_PROOF',
        existing_foreign_pool_commitments='MUST_BE_ADDED_BY_ACTUAL_POOL_ADMISSION',
        backup='RESERVED_NOT_CREATED', completion_proved=False)


def estimate_from_day(profile_id, observation):
    """Explicitly bound day DATA yields estimates, never a horizon guarantee.

    The caller must preserve and verify the raw evidence named by its SHA.
    This function validates the declared record, not undocumented measurement.
    """
    names=('format','source_identity','specification_identity','root_identity',
        'evidence_sha256','duration_seconds','original_anchor_seconds','target_seconds',
        'parent_E2E_ns','worker_wall_ns','worker_CPU_ns','retained_file_data_bytes',
        'cumulative_file_names','owner_database_pages','public_export_bytes')
    _fields(observation,names)
    if observation['format'] != DAY_OBSERVATION:
        raise ValueError('90D explicit day observation identity')
    for key in ('source_identity','specification_identity','root_identity','evidence_sha256'):
        _hash(observation[key])
    for key in ('duration_seconds','original_anchor_seconds','target_seconds'):
        _integer(observation[key],key)
    if (observation['duration_seconds'],observation['original_anchor_seconds'],observation['target_seconds']) != (86400,ANCHOR,ANCHOR+86400):
        raise ValueError('90D complete original-anchor day evidence required')
    for key in names[8:]:
        _integer(observation[key],key)
    if observation['parent_E2E_ns'] <= 0 or observation['worker_wall_ns'] <= 0:
        raise ValueError('90D positive completed day clocks required')
    proposal=capacity_proposal(profile_id)
    if (observation['cumulative_file_names']>proposal['namespace']['maximum_cumulative_file_names'] or
            observation['owner_database_pages']>proposal['namespace']['maximum_owner_pages'] or
            observation['retained_file_data_bytes']>proposal['physical_contract']['global_retained_cap_bytes'] or
            observation['public_export_bytes']>proposal['readonly_export']['physical_public_operation_cap_bytes']):
        raise ValueError('90D day observation exceeds its declared owner bounds')
    # Integer arithmetic and rounding up only; no alteration of physical grids.
    wall90=90*observation['parent_E2E_ns']
    needed=(wall90+840*10**9-1)//(840*10**9)
    dimensions=[('retained_file_data',90*observation['retained_file_data_bytes'],proposal['physical_contract']['global_retained_cap_bytes']),
        ('cumulative_file_names',90*observation['cumulative_file_names']+proposal['namespace']['prospective_file_slots_per_active_segment']+proposal['namespace']['mutable_names_per_segment'],proposal['namespace']['maximum_cumulative_file_names']),
        ('owner_pages_with_next_segment_escrow',90*observation['owner_database_pages']+proposal['namespace']['reserved_metadata_pages_per_unsettled_segment'],proposal['namespace']['maximum_owner_pages']),
        ('public_export_plus_manifest',90*observation['public_export_bytes']+proposal['readonly_export']['manifest_reserve_bytes'],proposal['readonly_export']['physical_public_operation_cap_bytes'])]
    return dict(format='CORE_90D_V6_ESTIMATE_FROM_BOUND_DAY_V1',profile=profile_id,
        observation=dict(observation),status='ESTIMATED_FROM_DAY_WITH_ENFORCED_HALT',
        stationary_parent_wall_ns=wall90, stationary_worker_wall_ns=90*observation['worker_wall_ns'],
        stationary_worker_CPU_ns=90*observation['worker_CPU_ns'],
        stationary_primary_segments_at_soft840=needed,
        twofold_wall_margin_primary_segments=2*needed,
        selected_profile_primary_cap=proposal['policy']['maximum_primary_segments'],
        estimate_with_twofold_margin_fits=2*needed<=proposal['policy']['maximum_primary_segments'],
        stationary_retained_file_data_bytes=90*observation['retained_file_data_bytes'],
        stationary_cumulative_file_names=90*observation['cumulative_file_names'],
        stationary_owner_pages=90*observation['owner_database_pages'],
        stationary_public_export_bytes=90*observation['public_export_bytes'],
        stationary_dimension_screens=[dict(name=name,estimate=value,cap=cap,fits=value<=cap)for name,value,cap in dimensions],
        assumptions=['Every later day costs and retains the same as the one recorded day.',
            'The single-design sample is not a measurement of the other four designs.',
            'The twofold margin is an explicit planning assumption, not a proved error bound.',
            'Actual namespace/page/output/journal/pool guards and safe terminal refusal remain authoritative.'],
        measurement_truth='CALLER_MUST_VERIFY_RAW_EVIDENCE_BINDING',completion_proved=False)


def _unpack(raw):
    from .portable_job import parse
    from . import year_project as year
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('90D bounded exact job bytes')
    data=parse(raw)
    _fields(data,('format','version','profile','duration_seconds','original_anchor_seconds',
        'target_seconds','year_job_document','year_job_sha256','policy_identity','capacity','digest'))
    if data['format'] != FORMAT or type(data['version']) is not int or data['version'] != 1:
        raise ValueError('90D exact job version')
    body={k:v for k,v in data.items()if k!='digest'}
    if canonical(data)!=raw or data['digest']!=sha256(canonical(body)).hexdigest():
        raise ValueError('90D canonical content identity')
    for key,expected in (('duration_seconds',DURATION),('original_anchor_seconds',ANCHOR),('target_seconds',TARGET)):
        if type(data[key]) is not int or data[key] != expected:
            raise ValueError('90D fixed original-anchor horizon')
    policy=policy_for(data['profile'])
    if data['policy_identity']!=policy.identity or canonical(data['capacity'])!=canonical(capacity_proposal(data['profile'])):
        raise ValueError('90D policy/capacity proposal drift')
    if type(data['year_job_document']) is not str:
        raise ValueError('90D embedded owner job text')
    inner=data['year_job_document'].encode('utf8')
    if not 0<len(inner)<=year.MAX_BYTES or sha256(inner).hexdigest()!=data['year_job_sha256']:
        raise ValueError('90D owner job raw binding')
    job=parse(inner)
    if type(job)is not dict or type(job.get('world'))is not dict or type(job.get('execution'))is not dict:
        raise ValueError('90D existing owner DATA objects required')
    if (job.get('format')!=year.FORMAT_V5 or type(job.get('duration_seconds'))is not int or job.get('duration_seconds')!=DURATION or
            job.get('world',{}).get('start_seconds')!=ANCHOR or job.get('world',{}).get('end_seconds')!=TARGET or
            canonical(job.get('execution',{}).get('policy'))!=canonical(asdict(policy))):
        raise ValueError('90D exact existing V5 horizon/policy')
    return data,inner


def compile_job(project,profile_id,ledger,build_bytes):
    from . import year_project as year
    policy=policy_for(profile_id)
    inner=year.compile_job_v5(project,DURATION,ledger,policy,build_bytes)
    job=json.loads(inner)
    if job['world']['start_seconds']!=ANCHOR or job['world']['end_seconds']!=TARGET:
        raise ValueError('90D original anchor required')
    body=dict(format=FORMAT,version=1,profile=profile_id,duration_seconds=DURATION,
        original_anchor_seconds=ANCHOR,target_seconds=TARGET,
        year_job_document=inner.decode('utf8'),year_job_sha256=sha256(inner).hexdigest(),
        policy_identity=policy.identity,capacity=capacity_proposal(profile_id))
    raw=canonical(dict(body,digest=sha256(canonical(body)).hexdigest()))
    _unpack(raw)
    return raw


def admit_job(raw,ledger):
    from . import year_project as year
    _,inner=_unpack(raw)
    return year.admit_job(inner,ledger)


def create_store(raw,project_directory,workspace_directory,ledger):
    """Delegate one existing creation path; report its actual returned path."""
    from . import year_project as year
    data,inner=_unpack(raw)
    result=year.create_store(inner,project_directory,workspace_directory,ledger)
    return dict(result,profile=data['profile'],policy_identity=data['policy_identity'],
        ninety_day_job_sha256=sha256(raw).hexdigest(),year_job_sha256=data['year_job_sha256'],
        duration_seconds=DURATION,target_seconds=TARGET,dispatch=False)


def run(directory,*,maximum_segments):
    _integer(maximum_segments,'maximum_segments',1,96)
    from .lifetime_supervisor import run as execute
    return execute(directory,explicit_continue=False,maximum_segments=maximum_segments)


def resume(directory,*,maximum_segments):
    _integer(maximum_segments,'maximum_segments',1,96)
    from .lifetime_supervisor import run as execute
    return execute(directory,explicit_continue=True,maximum_segments=maximum_segments)


def status(directory):
    from .year_project import status as current
    return current(directory)


def stop(directory):
    from .year_project import stop as current
    return current(directory)


def export_result(directory,output):
    from .lifetime_supervisor import export_result as current
    return current(directory,output)
