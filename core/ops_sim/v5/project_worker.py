"""Allowlisted offline fresh actual/paid causal M8 worker. No HTTP or shell API."""
from pathlib import Path
from dataclasses import asdict
from hashlib import sha256
import argparse,json,os,sys,time,traceback
from .project_store import ProjectStore,RESULT,file_sha,runtime_identity,identifier
from .spacecraft_project import materialize_project,project_source_identity
from .spacecraft_project_document import loads_project
from .design_repair import ConstructorLedger
from .design_repair_study import metrics_from_science
from .rolling_execution import start_rolling,step_rolling,paid_scientific_bytes,scientific_projection,work_projection
from .rolling_document import save_continuation,restore_continuation
from .command_document import inputs_to_json as root_to_json,PACKET
from .rolling_physics import digest
from .long_mission_document import canonical_json
from .long_mission_continuation import _scientific
from .rolling_cache import canonical_size
from .experiment_codec import object_fields,parse_json
from .project_intents import validate_intent,DIRECT
from .rolling_snapshot import capture_snapshot,restore_snapshot,admit_snapshot,METHOD as SNAPSHOT_METHOD
from .mission_report import MissionReport
from .mission_report_document import dumps_report
from .project_diagnostics import RestoreWatch,validate_window,returned_detail
from .rolling_snapshot_document import CONTROL_ALLOWANCE

PROGRESS='M8_VALIDATED_BOUNDARY_JOURNAL_V1'

def job_path(root,jid,name):
    identifier(jid)
    allowed=('request.json','project-input.json','preview.json','root.json','science.json','work.json',
        'checkpoint.rolling.json','checkpoint-summary.json','terminal.json','progress.jsonl','failure.json',
        'snapshot-136.json','snapshot-200.json','snapshots.json','report.json','report-state.json',
        'details.jsonl','direct-restore.json','snapshot-work.json','window-report.json')
    if name not in allowed:raise ValueError('fixed worker artifact name')
    root=Path(root).absolute();p=root/'jobs'/jid/name
    ProjectStore._reject_links(p)
    if not p.resolve().is_relative_to(root.resolve()):raise ValueError('worker path containment')
    return p

class Journal:
    def __init__(self,path,identity,limit):
        self.path=path;self.identity=identity;self.limit=limit;self.bytes=0;self.seq=0
        self.file=path.open('xb');self.terminal_reserve=16384
    def emit(self,kind,data,*,terminal=False):
        raw=canonical_json(dict(format=PROGRESS,sequence=self.seq+1,kind=kind,identity=self.identity,data=data)).encode()+b'\n'
        if len(raw)>16384 or self.bytes+len(raw)>self.limit-(0 if terminal else self.terminal_reserve):
            raise ValueError('M8_PROGRESS_PUBLICATION_ADMISSION')
        self.file.write(raw);self.file.flush();self.seq+=1;self.bytes+=len(raw)
    def close(self):self.file.close()

def write_new(path,raw,cap):
    if type(raw) is not bytes or len(raw)>cap:raise ValueError('M8_OUTPUT_BEFORE_WRITE')
    with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return sha256(raw).hexdigest()

def execute(store,jid,expected_request_sha):
    request_path=job_path(store,jid,'request.json')
    if request_path.stat().st_size>16*2**20 or file_sha(request_path)!=expected_request_sha:raise ValueError('external worker request SHA')
    q=object_fields(parse_json(request_path.read_text(encoding='utf-8')),('format','job_id','project_id','revision',
        'source_identity','root_identity','project_input_sha256','preview_sha256','constructor_before','constructor_reserved','runtime','resume','intent'))
    if q['format']!='M8_ALLOWLISTED_PROJECT_WORKER_REQUEST_V2' or q['job_id']!=jid:raise ValueError('worker request identity')
    intent=validate_intent(q['intent'])
    raw=job_path(store,jid,'project-input.json').read_bytes()
    if sha256(raw).hexdigest()!=q['project_input_sha256']:raise ValueError('immutable job input SHA')
    project=loads_project(raw.decode(),expected_identity=q['revision'],expected_source_identity=q['source_identity'])
    from .spacecraft_project import require_short_project
    require_short_project(project)
    if project.source_identity!=project_source_identity() or q['runtime']!=runtime_identity():raise ValueError('pinned runtime/source admission')
    if file_sha(job_path(store,jid,'preview.json'))!=q['preview_sha256']:raise ValueError('frozen preview SHA')
    snapshot_raw=None;prevalidation_reserved=0
    if q['resume'] is not None and q['resume']['kind']==DIRECT:
        cp=q['resume']['snapshot'];snapshot_raw=job_path(store,q['resume']['job_id'],cp['file']).read_bytes()
        # Advanced authority and runtime admitted before materialization/reservation.
        expected=dict(root_identity=q['root_identity'],revision=q['revision'],source_identity=q['source_identity'],runtime=q['runtime'],
            project_input_sha256=q['project_input_sha256'],method=SNAPSHOT_METHOD,clock=cp['clock'])
        prevalidation_reserved+=CONTROL_ALLOWANCE
        admit_snapshot(snapshot_raw,expected_sha256=cp['sha256'],expected_bindings=expected)
        validate_window(intent,cp['clock'])
    journal=Journal(job_path(store,jid,'progress.jsonl'),{n:q[n] for n in ('job_id','revision','source_identity','root_identity')},project.limits.maximum_progress_bytes)
    report=dict(constructor=None,control_reserved=prevalidation_reserved,progress_records=0,packet_bytes=0,scientific_bytes=0,
        reconstruction=None,worker_cpu_seconds=0.,status='RUNNING')
    cpu=time.process_time();state=None;checkpoint=None;snapshots=[];snapshot_work=[];stream=None;window_stream=None
    details=job_path(store,jid,'details.jsonl').open('xb');detail_bytes=0
    try:
        journal.emit('identity',dict(worker_PID=os.getpid(),worker_PPID=os.getppid(),runtime=runtime_identity()))
        # Same accepted offline audit guard, copied byte-for-byte.
        from .project_offline_guard import block_network
        block_network()
        ledger=ConstructorLedger(**q['constructor_before'])
        root,_,_=materialize_project(project,ledger)
        if digest(root)!=q['root_identity'] or asdict(ledger)!=q['constructor_reserved']:
            raise ValueError('actual numeric construction/root/work binding')
        report['constructor']=asdict(ledger)
        write_new(job_path(store,jid,'root.json'),root_to_json(root).encode(),16*2**20)
        if q['resume'] is None:
            state=start_rolling(root);stream=MissionReport(root)
        elif q['resume']['kind']==DIRECT:
            cp=q['resume']['snapshot']
            with RestoreWatch(globals()) as watch:
                report['control_reserved']+=CONTROL_ALLOWANCE
                state,report_state,proof=restore_snapshot(snapshot_raw,root,expected_sha256=cp['sha256'],expected_bindings=expected)
            proof.update(watch.proof());report['reconstruction']=proof
            if report_state is None:raise ValueError('direct application snapshot requires generated report state')
            stream=MissionReport(root,state=report_state)
            if stream.state['end_seconds']!=proof['restored_clock'] or stream.state['cursor']+stream.state['base_cursor']!=state.physical.cursor:raise ValueError('snapshot report/physical cursor mismatch')
            window_stream=MissionReport(root,start_context=state.physical.context,start_cursor=state.physical.cursor)
            write_new(job_path(store,jid,'direct-restore.json'),canonical_json(proof).encode(),project.limits.maximum_metadata_bytes)
            journal.emit('direct_restore',dict(method=proof['method'],restored_clock=proof['restored_clock'],prefix_actual_calls=proof['prefix_actual_calls'],
                prefix_forecast_calls=proof['prefix_forecast_calls'],prefix_force_calls=proof['prefix_force_calls'],
                validation_control_units=proof['validation_control_units'],prior_work_retained=True))
        else:
            resume=object_fields(q['resume'],('kind','job_id','checkpoint','expected_complete_science','report_snapshot'))
            prior=object_fields(resume['checkpoint'],('file','sha256','bytes','clock','pending','partial_bits','completed_decisions'))
            if prior['file']!='checkpoint.rolling.json':raise ValueError('fixed checkpoint file')
            old_path=job_path(store,resume['job_id'],prior['file'])
            if old_path.stat().st_size!=prior['bytes'] or old_path.stat().st_size>project.limits.maximum_packet_bytes:
                raise ValueError('causal packet project bytes')
            state,proof=restore_continuation(old_path,expected_packet_sha256=prior['sha256'],expected_root_identity=digest(root))
            # Physical continuation remains the unchanged paid B48 replay. The
            # report sidecar is restored as trusted data, not used as physics.
            meta=q['resume'].get('report_snapshot')
            if meta is not None:
                from .rolling_snapshot_document import GraphCodec
                saved=job_path(store,resume['job_id'],meta['file']).read_bytes()
                doc=admit_snapshot(saved,expected_sha256=meta['sha256'],expected_bindings=meta['bindings'])
                stream=MissionReport(root,state=GraphCodec(root).decode(doc['graph'])['report'])
            else:stream=None
            report['reconstruction']=proof
            journal.emit('reconstruction',dict(method=proof['method'],replay_completed_decisions=proof['replay_completed_decisions'],
                scientific_equal=proof['scientific_equal'],prior_work_retained=True,additional_work_charged=True))
        while state.status=='ACTIVE':
            state=step_rolling(state)
            clock=state.physical.context.simulation_time_seconds
            detail=stream.consume(state) if stream is not None else dict(scope='CAUSAL_PREFIX_REPORT_UNAVAILABLE')
            if window_stream is not None:window_stream.consume(state)
            detail_record=dict(sequence=len(state.decisions),mode=intent['mode'],data=detail)
            if intent['mode']=='DIAGNOSTIC_VERBOSE':
                detail_record['actual_returned']=returned_detail(state.physical.outcomes[-1],state.physical.context)
                detail_record['returned_cuts']=[dict(start=str(c.start_seconds),end=str(c.end_seconds),actuator_draw_w=c.actuator_draw_w,
                    kinetic_start_j=c.kinetic_start_j,kinetic_end_j=c.kinetic_end_j) for c in state.physical.outcomes[-1].cuts]
                detail_record['received_packet_id']=state.knowledge.observation.packet_id
            detail_raw=canonical_json(detail_record).encode()+b'\n'
            if len(detail_raw)>2**20 or detail_bytes+len(detail_raw)>32*2**20:raise ValueError('B51_DETAIL_CHUNK_QUOTA')
            details.write(detail_raw);details.flush();detail_bytes+=len(detail_raw)
            if stream is not None:stream.state['detail_bytes']+=len(detail_raw)
            journal.emit('boundary',dict(validated=True,clock=float(clock),clock_exact=_scientific(clock),
                completed_decisions=len(state.decisions),status=state.status,
                pending=[c.kind for c in state.knowledge.pending()],
                partial_bits=[p.transmitted_equivalent_bits for p in state.physical.context.ground_data_delivery_state.partial_transfers],
                received_at=float(state.knowledge.observation.observed_at_seconds),
                received_credit_scope='RECEIVED_OBSERVATION_ONLY',forecast_scope='PRIVATE_UNCONFIRMED_COMMAND_ESTIMATE',
                work={n:getattr(state.work,n) for n in ('decisions','forecast_invocations','actual_physical_reserved','control_reserved','reconstructions')}))
            if q['resume'] is None and checkpoint is None and state.physical.context.ground_data_delivery_state.partial_transfers and any(c.kind=='CONTACT' for c in state.knowledge.pending()):
                # Admission before constructing/encoding packet. 1024 bytes bound
                # decimal growth in the old fixed-point publication counters.
                report['control_reserved']+=2*((project.limits.maximum_packet_bytes+63)//64)+2**20
                data=dict(format=PACKET,version=1,inputs=parse_json(root_to_json(root)),root_identity=digest(root),
                    completed_decisions=len(state.decisions),scientific=_scientific(scientific_projection(state)),paid_work=work_projection(state))
                canonical_size(data,project.limits.maximum_packet_bytes-1024)
                path=job_path(store,jid,'checkpoint.rolling.json');h=save_continuation(path,state)
                if path.stat().st_size>project.limits.maximum_packet_bytes:raise ValueError('packet exceeded preadmitted project cap')
                checkpoint=dict(file='checkpoint.rolling.json',sha256=h,bytes=path.stat().st_size,clock=float(clock),
                    pending=[c.kind for c in state.knowledge.pending()],partial_bits=[p.transmitted_equivalent_bits for p in state.physical.context.ground_data_delivery_state.partial_transfers],
                    completed_decisions=len(state.decisions))
                report['packet_bytes']=path.stat().st_size
                write_new(job_path(store,jid,'checkpoint-summary.json'),canonical_json(checkpoint).encode(),16384)
                journal.emit('checkpoint',checkpoint)
            if q['resume'] is None and clock in (136,200):
                report['control_reserved']+=CONTROL_ALLOWANCE
                bindings=dict(root_identity=digest(root),revision=q['revision'],source_identity=q['source_identity'],runtime=q['runtime'],
                    project_input_sha256=q['project_input_sha256'],method=SNAPSHOT_METHOD,clock=clock)
                snap,paid=capture_snapshot(state,bindings,report_state=stream.state)
                name='snapshot-'+str(clock)+'.json';h=write_new(job_path(store,jid,name),snap,128*2**20)
                meta=dict(file=name,sha256=h,bytes=len(snap),clock=clock,bindings=bindings,pending=[c.kind for c in state.knowledge.pending()],
                    partial_bits=[p.transmitted_equivalent_bits for p in state.physical.context.ground_data_delivery_state.partial_transfers],
                    queued_packet_ids=[p.packet_id for p in state.queued],completed_decisions=len(state.decisions))
                snapshots.append(meta);snapshot_work.append(paid);journal.emit('snapshot',meta)
            if intent['method']==DIRECT and clock>=intent['window_end_seconds']:
                if clock!=intent['window_end_seconds']:raise ValueError('DIAGNOSTIC_NEEDS_COMMITTED_ACTION_BOUNDARY')
                break
        if state.status!='COMPLETE' and not (intent['method']==DIRECT and state.physical.context.simulation_time_seconds==intent['window_end_seconds']):raise ValueError('ACTUAL_TERMINAL_'+state.status)
        report['control_reserved']+=2*((project.limits.maximum_science_bytes+63)//64)+2**20
        canonical_size(_scientific(scientific_projection(state)),project.limits.maximum_science_bytes)
        science=paid_scientific_bytes(state);report['scientific_bytes']=len(science)
        h=write_new(job_path(store,jid,'science.json'),science,project.limits.maximum_science_bytes)
        metrics=metrics_from_science(science,root,expected_scientific_sha256=h)
        summary=None if stream is None else stream.finish()
        report['control_reserved']+=4*2**20
        if summary is not None and (summary['totals']['credits']!=metrics['credited_products'] or summary['totals']['executed_point_seconds']!=metrics['actual_slew_seconds']):
            raise ValueError('incremental actual report credit/execution disagreement')
        if summary is not None and (summary['totals']['minimum_energy_wh']!=metrics['minimum_energy_wh'] or summary['totals']['maximum_temperature_k']!=metrics['maximum_temperature_k']):
            raise ValueError('incremental returned extrema disagreement')
        report_value=summary if summary is not None else dict(method='B48_CAUSAL_PREFIX_REPORT_UNAVAILABLE')
        report_sha=write_new(job_path(store,jid,'report.json'),dumps_report(report_value),2**20)
        if stream is not None:write_new(job_path(store,jid,'report-state.json'),dumps_report(stream.state),2**20)
        write_new(job_path(store,jid,'snapshots.json'),canonical_json(snapshots).encode(),2**20)
        write_new(job_path(store,jid,'snapshot-work.json'),canonical_json(snapshot_work).encode(),project.limits.maximum_metadata_bytes)
        window_summary=None if window_stream is None else window_stream.finish()
        if window_summary is not None:
            window_raw=dumps_report(window_summary)
            window_sha=write_new(job_path(store,jid,'window-report.json'),window_raw,2**20)
        if project.source_identity!=project_source_identity():raise ValueError('PROJECT_SOURCE_CHANGED_DURING_EXECUTION')
        equal=None
        if q['resume'] is not None and q['resume']['expected_complete_science'] is not None and state.status=='COMPLETE':
            equal=h==q['resume']['expected_complete_science']
            if not equal:raise ValueError('CURRENT_PROJECT_SAME_ENVIRONMENT_RESTART_MISMATCH')
        report.update(progress_records=journal.seq+1,worker_cpu_seconds=time.process_time()-cpu,status='COMPLETED')
        work=dict(project=report,unchanged_root_work=work_projection(state),ceiling_admission='UNCHANGED_COMPLETE_ROOT_QUOTAS',
            restart_extra='Prior root work retained; direct snapshot validation and report/encoding separately paid; causal replay separate.',
            report_control_units=None if stream is None else stream.state['control_units'],detail_bytes=detail_bytes,snapshot_encoding=snapshot_work,
            report_control_reserved_units=None if stream is None else stream.state['control_reserved_units'],
            window_report_control_units=None if window_stream is None else window_stream.state['control_units'],
            window_report_control_reserved_units=None if window_stream is None else window_stream.state['control_reserved_units'],
            diagnostic_scope=intent['mode'],restore=report['reconstruction'])
        write_new(job_path(store,jid,'work.json'),canonical_json(work).encode(),project.limits.maximum_metadata_bytes)
        record=dict(format=RESULT,job_id=jid,revision=q['revision'],source_identity=q['source_identity'],root_identity=digest(root),
            comparison_identity=project.comparison_identity,scientific_sha256=h,scientific_bytes=len(science),metrics=metrics,
            checkpoint=checkpoint,runtime=runtime_identity(),same_environment_resume_equal=equal,
            qualification='UNRESOLVED_SYNTHETIC600S',work_sha256=file_sha(job_path(store,jid,'work.json')),
            snapshots=snapshots,report=dict(file='report.json',sha256=report_sha,bytes=len(dumps_report(report_value)),totals=None if summary is None else summary['totals']),
            window_report=None if window_summary is None else dict(file='window-report.json',sha256=window_sha,bytes=len(window_raw),totals=window_summary['totals'],
                scope='NEW_WINDOW_EVENTS_ONLY_CARRIED_IN_REQUESTS_NOT_OFFERED_AGAIN'),
            continuation_method=intent['method'],diagnostic_scope=intent['mode'])
        req=project.requirements
        reasons=[]
        if metrics['credited_products']<req.minimum_credited_products:reasons.append('REQUIRED_ACTUAL_OUTPUT')
        if metrics['priority_weighted_delivery_score']<req.minimum_priority_score:reasons.append('REQUIRED_PRIORITY_SCORE')
        if metrics['unmet_load_wh']>req.maximum_unmet_load_wh:reasons.append('RETURNED_UNMET_LOAD')
        if metrics['actual_refusals']>req.maximum_actual_refusals:reasons.append('RETURNED_ACTION_REFUSALS')
        if metrics['actual_full_service_shortfalls']:reasons.append('RETURNED_ELECTRICAL_SERVICE')
        if metrics['returned_temperature_violations']:reasons.append('RETURNED_TEMPERATURE_PROTECTION')
        record['requirements_evaluation']=dict(satisfied=not reasons,reasons=reasons,
            scope='DECLARED_SYNTHETIC_MISSION_REQUIREMENTS_NOT_FLIGHT_QUALIFICATION')
        write_new(job_path(store,jid,'terminal.json'),canonical_json(record).encode(),project.limits.maximum_metadata_bytes)
        journal.emit('completed',dict(terminal_sha256=file_sha(job_path(store,jid,'terminal.json')),scientific_sha256=h,clock=float(state.physical.context.simulation_time_seconds)),terminal=True)
    except BaseException as error:
        failure=dict(type=type(error).__name__,reason=str(error),traceback=traceback.format_exc(),
            status='PROCESS_FAILED',last_recorded_validated_boundary_only=True,
            physical_completion='NOT_ESTABLISHED',checkpoint=checkpoint,project_work=report)
        try:
            write_new(job_path(store,jid,'failure.json'),canonical_json(failure).encode(),project.limits.maximum_metadata_bytes)
            journal.emit('failure',dict(type=type(error).__name__,reason=str(error),final_physics='NOT_ESTABLISHED'),terminal=True)
        except BaseException:traceback.print_exc()
        raise
    finally:journal.close();details.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--store',required=True);p.add_argument('--job',required=True);p.add_argument('--request-sha256',required=True)
    a=p.parse_args();execute(a.store,a.job,a.request_sha256)
if __name__=='__main__':main()
