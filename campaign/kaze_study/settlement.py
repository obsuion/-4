"""One settlement verifier for live completion and crash recovery.

PID/time is never authority. Recovery additionally needs the independently
committed completion pin, and replays the exact CORE owned-cleanup receipts.
"""
import math
from pathlib import Path
import re

from .data import canonical, digest, fields, identity, inside, parse, read, read_bytes
from .errors import Refusal


def _saved_administrative_no_launch(state,store,summary,administrative):
    """Private historical ACKs for exact35/d66, never a current-owner waiver."""
    from types import SimpleNamespace
    from .ninety_cold_recovery import verified_prefix_exclusions
    from .ninety_no_launch import _profile_document,_store,verified_for_queue,doc
    from .ninety_direct_prefix import _core_runtime4_join_v1
    if (state.study.spec.get('ninety_contract',{}).get('direct_main_version')!='DIRECT90D_USER_SCOPE_V1'or
        _store(state)!=Path(store).resolve()):raise Refusal('CORE_SAVED_ADMINISTRATIVE_EXACT_DIRECT_STATE')
    profile=_profile_document(state);_core_runtime4_join_v1(profile,summary['runtime'])
    if profile['source_identity']!=summary['source_identity']:raise Refusal('CORE_SAVED_ADMINISTRATIVE_SOURCE')
    queue=SimpleNamespace(connection=state.connection,authority=state.study.authority);accepted={};seen=set()
    excluded=verified_prefix_exclusions(state)
    if type(excluded)is not list or not 1<=len(excluded)<=2:raise Refusal('CORE_SAVED_ADMINISTRATIVE_BOUNDED_ACKS')
    for item in excluded:
        if type(item)is not dict or set(item)!={'intent','ACK'}:raise Refusal('CORE_SAVED_ADMINISTRATIVE_EXACT_ACK_REFERENCE')
        iid=item.get('intent')
        if iid in seen:raise Refusal('CORE_SAVED_ADMINISTRATIVE_DUPLICATE_ACK')
        seen.add(iid);ack=doc(item['ACK'])
        if iid=='35d0952ef15d4a79b49e5df4e6ce16b8':reference=ack['proof']['disposition']
        elif iid=='d66b287c610a400888d8210ff802355d':reference=ack['proof']['original']['disposition']
        else:raise Refusal('CORE_SAVED_ADMINISTRATIVE_EXACT_ACK_ONLY')
        value=verified_for_queue(queue,reference,intent=iid,store=store,profile=profile)
        if value['job_id']in accepted:raise Refusal('CORE_SAVED_ADMINISTRATIVE_DUPLICATE_JOB')
        accepted[value['job_id']]=value
    from .ninety_prethread_recovery import exclusions as prethread_exclusions
    with state.connection()as c:
        anchors=list(c.execute('SELECT rowid FROM chain_entries WHERE study=?AND design=?AND job_id=?AND receipt_sha IS NOT NULL',
            (state.key,'D1_BALANCED',summary['parent_job_id'])))
    if len(anchors)!=1:raise Refusal('CORE_SAVED_ADMINISTRATIVE_EXACT_SETTLED_PARENT_ROW')
    for item in prethread_exclusions(state,before_entry=anchors[0][0]):
        # A historical saved receipt selects only its own original jobs.
        if item['CORE_job_id']not in administrative:continue
        value=verified_for_queue(queue,item['CORE_disposition'],intent=item['intent'],store=store,profile=profile)
        if value['job_id']in accepted:raise Refusal('CORE_SAVED_ADMINISTRATIVE_DUPLICATE_PRETHREAD_JOB')
        accepted[value['job_id']]=value
    if accepted!=administrative:raise Refusal('CORE_SAVED_ADMINISTRATIVE_PRIVATE_RECEIPTS')
    return accepted


def _saved_administrative_raw(root,jid,value,summary,plan):
    """Rehash old no-start DATA only after private ACK authentication above."""
    boundary_raw=read_bytes(root/'no-launch-boundary.json',8192)
    proof_raw=read_bytes(root/'no-launch-proof.json',8192)
    request_raw=read_bytes(root/'request.json',16*2**20)
    b=fields(parse(boundary_raw),('format','job_id','request_sha256','root_identity','source_identity','runtime','input_sha256','intent','dispatch_sha256','owner','reserved_bytes'))
    p=fields(parse(proof_raw),('format','boundary','reason','thread_start_attempted','scientific_launch_attempted','scientific_authority'))
    request=parse(request_raw)
    if (canonical(b)!=boundary_raw or canonical(p)!=proof_raw or b['format']!='YEAR_V3_RUNNER_PRE_THREAD_BOUNDARY_V1'or
        p['format']!='YEAR_V3_RUNNER_NO_LAUNCH_PROOF_V1'or p['boundary']!=b or
        any(p[k]is not False for k in('thread_start_attempted','scientific_launch_attempted','scientific_authority'))or
        any(b[k]!=request[k]for k in('job_id','root_identity','source_identity','runtime','input_sha256','intent'))or
        b['job_id']!=jid or b['request_sha256']!=digest(request_raw)or type(b['reserved_bytes'])is not int or b['reserved_bytes']!=24576 or
        b['root_identity']!=plan['root_identity']or b['input_sha256']!=plan['input_sha256']or
        b['source_identity']!=summary['source_identity']or b['runtime']!=summary['runtime']or
        (root/'thread-attempt.json').exists()):raise Refusal('CORE_SAVED_ADMINISTRATIVE_RAW_NO_START_BINDING')
    pins={name:dict(path=str(root/name),sha256=digest(raw),bytes=len(raw))for name,raw in(
        ('no-launch-proof.json',proof_raw),('no-launch-boundary.json',boundary_raw),('request.json',request_raw))}
    if pins!=value['raw_pins']:raise Refusal('CORE_SAVED_ADMINISTRATIVE_RAW_PIN_DRIFT')
    return b,pins


def core_cleanup(store, summary, plan, owner, prior=None, *, saved_job_ids=None, no_launch_receipts=None, venv_executable=None, core_abi_version=None,saved_no_launch_state=None,reviewed_failed_receipts=None,reviewed_failed_state=None):
    prior = prior or {}
    if core_abi_version is not None and (type(core_abi_version)is not int or core_abi_version!=6):raise Refusal('CORE_EXPLICIT_SUPPORTED_CLEANUP_ABI_REQUIRED')
    store_plan = read(Path(store) / "lifetime-plan.json", 65536)
    if (store_plan.get("plan_identity") != summary["plan_identity"] or
            store_plan["plan_identity"] != identity({k: v for k, v in store_plan.items() if k != "plan_identity"}) or
            any(store_plan.get(k) != plan.get(k) for k in ("root_identity", "input_sha256", "execution_contract_sha256", "policy_identity")) or
            store_plan.get("execution_authority_sha256") != summary["execution_authority_sha256"] or
            store_plan.get("backend_binding") != summary["backend_binding"] or store_plan.get("runtime") != summary["runtime"]):
        raise Refusal("CORE_STORE_PLAN_COMPLETION_BINDING")
    contract = read(Path(store) / "portable-execution.json", 2 * 2**20)
    authority_raw = read_bytes(Path(store) / "execution-authority.json", 16384)
    if (digest(read_bytes(Path(store) / "input.json", 8 * 2**20)) != plan["input_sha256"] or
            identity(contract) != plan["execution_contract_sha256"] or contract.get("input_sha256") != plan["input_sha256"] or
            contract.get("source_manifest_sha256") != plan["source_manifest_sha256"] or
            contract.get("backend_binding") != summary["backend_binding"] or
            digest(authority_raw) != summary["execution_authority_sha256"] or parse(authority_raw) != plan["execution_authority"]):
        raise Refusal("CORE_STORE_INPUT_SOURCE_AUTHORITY_PINS")
    directory = Path(store) / "jobs"
    if not directory.is_dir():
        raise Refusal("CORE_OWNED_RECEIPTS_MISSING")
    names = []
    for p in directory.iterdir():
        if len(names) >= 8200 or not re.fullmatch(r"[0-9a-f]{32}", p.name) or not p.is_dir():
            raise Refusal("CORE_JOB_DIRECTORY_POPULATION")
        names.append(p.name)
    if saved_job_ids is not None:
        # Read-only reports first authenticate the historical receipt against
        # the independent completion ledger. Verify that receipt's exact jobs;
        # later jobs grant no authority and are not declared cleaned up here.
        selected=set(saved_job_ids)
        if len(selected)!=len(saved_job_ids)or not selected<=set(names):
            raise Refusal('CORE_SAVED_RECEIPT_JOB_POPULATION')
        names=sorted(selected)
    if len(names) != summary["jobs"] or summary["parent_job_id"] not in names or not set(prior) <= set(names):
        raise Refusal("CORE_JOB_SUMMARY_OR_PRIOR_BINDING")
    proofs = {}
    administrative=no_launch_receipts or{}
    if not set(administrative)<=set(names):raise Refusal('CORE_NO_LAUNCH_JOB_POPULATION')
    saved_administrative={}
    if saved_no_launch_state is not None:
        if saved_job_ids is None or not administrative or core_abi_version!=6:
            raise Refusal('CORE_SAVED_ADMINISTRATIVE_EXPLICIT_READ_ONLY_SCOPE')
        saved_administrative=_saved_administrative_no_launch(saved_no_launch_state,store,summary,administrative)
    reviewed=reviewed_failed_receipts or {}
    if reviewed and (reviewed_failed_state is None or core_abi_version!=6 or not set(reviewed)<=set(names) or set(reviewed)&set(administrative)):
        raise Refusal('CORE_REVIEWED_FAILED_EXPLICIT_INDEPENDENT_SCOPE')
    for jid in sorted(names):
        root = inside(store, "jobs/" + jid)
        if jid in reviewed:
            from .ninety_failed_initial import validate_reviewed_job
            validate_reviewed_job(reviewed_failed_state,store,jid,reviewed[jid])
            if jid in prior:raise Refusal('CORE_FAILED_JOB_NEVER_PREVIOUS_SETTLED_SCIENCE')
            continue
        if jid in administrative:
            # Callers derive this set from independent private SQL receipts.
            # Recheck owner raw DATA here; never waive an unknown attempt.
            v=administrative[jid]
            if(v['job_id']!=jid or v['source_identity']!=summary['source_identity']or v['store']!=str(Path(store).resolve())or
               v['scientific_authority']is not False or v['numerical_child_created']is not False or jid in prior):raise Refusal('CORE_NO_LAUNCH_ADMINISTRATIVE_BINDING')
            from .year_no_launch import evidence
            p=read(root/'no-launch-proof.json',8192);b=p['boundary']
            job={k:b[k]for k in('job_id','root_identity','source_identity','runtime','input_sha256','intent')}
            if jid in saved_administrative:
                # A later legitimate suffix can own this store. These exact
                # old jobs have private State ACKs and owner-committed proofs;
                # read their saved bytes without adopting the later owner.
                b,pins=_saved_administrative_raw(root,jid,v,summary,plan)
            else:
                # Live completion keeps the original no-active-owner guard.
                _,pins=evidence(store,job,dict(source_identity=summary['source_identity']))
            if b['root_identity']!=plan['root_identity']or b['input_sha256']!=plan['input_sha256']or b['runtime']!=summary['runtime']or pins!=v['raw_pins']:raise Refusal('CORE_NO_LAUNCH_REQUEST_ROOT_OR_PROOF_DRIFT')
            continue
        raw = read_bytes(root / "owned-settlement.json", 65536)
        owned = fields(parse(raw), ("format", "job_id", "root_identity", "launch"), "CORE owned settlement")
        back_raw = read_bytes(root / "backend-settlement.json", 32768)
        backend = parse(back_raw)
        fields(backend, ("format", "job_id", "root_identity", "source_identity", "launch_command", "root_launch_PID",
            "worker_identity", "owned_seen_PIDs", "execution_start_monotonic", "envelope_to_completed_cleanup_seconds", "scope", "cleanup"), "CORE backend settlement")
        if (owned["format"] != "B59_PARENT_OWNED_SETTLEMENT_V1" or owned["job_id"] != jid or
                owned["root_identity"] != plan["root_identity"] or backend.get("format") != "B60_DURABLE_BACKEND_SETTLEMENT_V1" or
                backend.get("job_id") != jid or backend.get("root_identity") != plan["root_identity"] or
                backend.get("source_identity") != summary["source_identity"] or
                backend.get("scope") != "LAUNCH_TO_COMPLETED_OWNED_CLEANUP_NOT_LATER_PARENT_REPORTING"):
            raise Refusal("CORE_SETTLEMENT_JOB_SOURCE_BINDING")
        launch = owned["launch"]
        if type(launch) is not dict or type(backend) is not dict:
            raise Refusal("CORE_SETTLEMENT_LAUNCH_DATA")
        cleanup = launch.get("cleanup")
        if (launch.get("ownership_valid") is not True or launch.get("forced_interruption") is not False or
                launch.get("timeout") is not False or launch.get("unexpected") is not None or
                launch.get("incomplete_tail_bytes") != 0 or type(cleanup) is not dict):
            raise Refusal("CORE_UNKNOWN_OR_FORCED_SUFFIX")
        for flag in ("owned_job_empty", "root_signaled", "root_status_captured", "root_reaped", "handles_closed", "cleanup_within_two_seconds"):
            if cleanup.get(flag) is not True:
                raise Refusal("CORE_DESCENDANT_CLEANUP_UNPROVEN", flag)
        if cleanup.get("errors") != [] or type(cleanup.get("root_exit_code")) is not int or cleanup["root_exit_code"] != 0 or backend.get("cleanup") != cleanup:
            raise Refusal("CORE_CLEANUP_ERRORS_OR_BACKEND_BINDING")
        values = [cleanup.get(k) for k in ("cleanup_started_monotonic", "cleanup_wall_seconds", "cleanup_deadline_monotonic")]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            raise Refusal("CORE_FINITE_CLEANUP_DEADLINE")
        start, wall, end = values
        if not 0 <= wall <= 2 or start + wall > end or start > end or cleanup.get("cleanup_within_deadline", True) is not True:
            raise Refusal("CORE_CLEANUP_DEADLINE")
        wi = launch.get("worker_identity")
        if (type(wi) is not dict or wi.get("runtime") != summary["runtime"] or
                type(wi.get("worker_PID")) is not int or type(wi.get("worker_PPID")) is not int or
                wi.get("worker_PID") not in launch.get("owned_seen_PIDs", []) or
                backend.get("worker_identity") != wi or backend.get("launch_command") != launch.get("command") or
                backend.get("owned_seen_PIDs") != launch.get("owned_seen_PIDs")):
            raise Refusal("CORE_WORKER_OWNER_BINDING")
        from .year_topology import numerical_pid
        numeric=numerical_pid(backend,venv_executable=venv_executable)
        redirected=numeric!=backend['root_launch_PID']
        launch_pins={}
        if redirected:
            if core_abi_version==6:
                launch_pins=_v6_parent_launch_binding(root,jid,summary,plan,owner,launch,backend,prior_job=jid in prior)
            else:
                boundary=read(root/'no-launch-boundary.json',8192)
                if(boundary['source_identity']!=summary['source_identity']or boundary['root_identity']!=plan['root_identity']or
                   boundary['job_id']!=jid or(jid not in prior and boundary['owner']['PID']!=owner['pid'])or launch['root_PID']!=backend['root_launch_PID']):raise Refusal('CORE_V3_VENV_ORIGINAL_PARENT_BOUNDARY')
        pin = dict(owned_sha256=digest(raw), backend_sha256=digest(back_raw),**launch_pins)
        if jid in prior:
            if pin != prior[jid]:
                raise Refusal("CORE_PREVIOUS_SETTLEMENT_DRIFT")
        elif not redirected and wi.get("worker_PPID") != owner.get("pid"):
            raise Refusal("CORE_NEW_WORKER_PARENT_OWNER_BINDING")
        proofs[jid] = pin
    return proofs


def validate_completion(study, record, intent, result, recorded_owner):
    fields(result, ("outcome", "parent_settled", "safe_no_submission", "process", "summary", "reason"), "process result")
    if type(result["parent_settled"]) is not bool or type(result["safe_no_submission"]) is not bool:
        raise Refusal("EXACT_RECEIPT_SETTLEMENT_FLAGS")
    process = result["process"]
    if type(process) is not dict:
        raise Refusal("RECEIPT_PROCESS_EVIDENCE")
    if result["safe_no_submission"]:
        if (result["parent_settled"] or result["outcome"] != "PROCESS_FAILURE" or result["summary"] is not None or
                recorded_owner is not None or process.get("owner") is not None or
                process.get("reason") != "NOT_CREATED" or process.get("returncode") is not None or process.get("reaped") is not True):
            raise Refusal("NOT_CREATED_NO_OWNER_PROOF_REQUIRED")
        if study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
            from .year_execution import validate_no_launch
            validate_no_launch(study,record,intent,result)
        return True
    if not result["parent_settled"]:
        return False
    if study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
        from .year_execution import validate_completion as year
        return year(study,record,intent,result,recorded_owner)
    if study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
        from .named_execution import validate_completion as named
        return named(study,record,intent,result,recorded_owner)
    if (recorded_owner is None or process.get("owner") != recorded_owner or
            process.get("returncode") != 0 or process.get("reason") is not None or process.get("reaped") is not True):
        raise Refusal("EXACT_REAPED_PROCESS_OWNER_PROOF_REQUIRED")
    raw = read_bytes(record["plan_path"])
    plan = parse(raw)
    if digest(raw) != intent["plan_sha256"] or record["plan_sha"] != intent["plan_sha256"]:
        raise Refusal("RECEIPT_EXACT_PLAN_BINDING")
    from .engine_adapter import validate_summary_data
    summary = validate_summary_data(result["summary"], plan, study)
    terminal = summary["typed_terminal"]
    if terminal is None or terminal["kind"] != result["outcome"] or result["outcome"] in ("UNKNOWN", "PROCESS_FAILURE") or summary["reserved_unknown_seconds"] != 0:
        raise Refusal("SETTLED_TERMINAL_OR_UNKNOWN_SUFFIX")
    stdout = process.get("stdout_text", "").encode("utf-8")
    if digest(stdout) != process.get("stdout_sha256") or len(stdout) != process.get("stdout_bytes"):
        raise Refusal("COMPLETION_STDOUT_RAW_PIN")
    response = fields(parse(stdout), ("store", "result", "billing_still_active"), "run completion")
    if (Path(response["store"]).absolute() != Path(intent["store"]).absolute() or response["result"] != summary or
            response["billing_still_active"] is not True):
        raise Refusal("COMPLETION_STORE_SUMMARY_BINDING")
    if study.spec["mode"] != "PROTOCOL_FIXTURE_NO_SCIENCE":
        proof = core_cleanup(intent["store"], summary, plan, recorded_owner, intent.get("prior_cleanup", {}))
        if process.get("core_cleanup") != proof or process.get("envelope", {}).get("format") != "KAZE_OBSERVED_CGROUP_V2_V1":
            raise Refusal("CORE_CLEANUP_OR_AGGREGATE_ENVELOPE_REQUIRED")
    return True


def _v6_parent_launch_binding(root,jid,summary,plan,owner,launch,backend,*,prior_job=False):
    """ABI6 CLASSIC uses its actual immutable parent launch authority.

    The source-bound adapter selects this ABI. A saved prior job must retain
    the same authority/request pins; a new job also binds the original private
    manager PID. This is process cleanup only, never scientific progress.
    """
    authority_raw=read_bytes(root/'parent-launch-authority.json',16384)
    request_raw=read_bytes(root/'request.json',16384)
    authority=parse(authority_raw);request=parse(request_raw);token=authority.get('dispatch_token')or{}
    root_PID=backend['root_launch_PID'];wi=backend['worker_identity'];cleanup=backend['cleanup']
    expected_command=[summary['runtime']['executable'],'-B','-m','ops_sim.v5.lifecycle_application','worker',
        '--store',str(root.parent.parent.resolve()),'--job',jid,'--request-sha256',digest(request_raw)]
    if(authority.get('format')!='B63_IMMUTABLE_PARENT_LAUNCH_AUTHORITY_V1'or
       request.get('format')!='B55R2_OWNED_BUDGET_JOB_V2'or
       any(x.get('job_id')!=jid or x.get('root_identity')!=plan['root_identity']or
           x.get('source_identity')!=summary['source_identity']or x.get('runtime')!=summary['runtime']for x in(authority,request))or
       request.get('input_sha256')!=plan['input_sha256']or
       authority.get('request_sha256')!=digest(request_raw)or authority.get('command')!=expected_command or
       authority.get('command')!=launch.get('command')or authority.get('command')!=backend.get('launch_command')or
       token.get('format')!='B52_EXCLUSIVE_DISPATCH_OWNER_V1'or token.get('source_identity')!=summary['source_identity']or
       type(token.get('PID'))is not int or token['PID']<=0 or type(token.get('owner'))is not str or
       re.fullmatch(r'[0-9a-f]{32}',token['owner'])is None or(not prior_job and token['PID']!=owner.get('pid'))or
       launch.get('root_PID')!=root_PID or root_PID not in backend['owned_seen_PIDs']or wi['worker_PID']not in backend['owned_seen_PIDs']or
       wi['worker_PPID']!=root_PID or cleanup.get('after',{}).get('job_active_count')!=0 or cleanup['after'].get('job_active_PIDs')!=[]or
       any(cleanup.get(k,{}).get('assigned_suspended_before_execution')is not True or
           cleanup[k].get('root_launch_PID')!=root_PID for k in('before','after'))):
        raise Refusal('CORE_V6_REAL_IMMUTABLE_PARENT_LAUNCH_BINDING')
    return dict(parent_launch_authority_sha256=digest(authority_raw),request_sha256=digest(request_raw))
