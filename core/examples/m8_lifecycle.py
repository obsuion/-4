"""Explicit offline lifecycle start/resume/report/loupe/export consumer.

Every scientific execution uses the same private-Job production runner as the
workbench. Reopen/report/export do not dispatch a calculation.
"""
from pathlib import Path
import argparse,json,time
from ops_sim.v5.lifecycle_application import LifecycleStore,LifecycleRunner,make_intent,requested_lifecycle_root
from ops_sim.v5.lifecycle_document import loads_root,dumps_root
from ops_sim.v5.lifecycle_runner_policy import SEGMENTED,requested_runner_policy
from ops_sim.v5.lifecycle_service import POWER_SERVICE_METHOD,requested_service_policy
from ops_sim.v5.lifecycle_compact import METHOD as COMPACT_METHOD,requested_profile
from ops_sim.v5.solar_attitude import METHOD as SOLAR_METHOD,requested_energy_policy
from ops_sim.v5.battery_port import METHOD as PORT_METHOD,requested_port_policy


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True,help='New or existing external B52 store; never a B51 directory')
    commands=p.add_subparsers(dest='command',required=True)
    create=commands.add_parser('create');create.add_argument('--input',type=Path,required=True)
    create.add_argument('--service-policy',choices=('LEGACY',POWER_SERVICE_METHOD),help='Verify the named policy already frozen in input; never changes input or a saved store')
    create.add_argument('--battery-port-policy',choices=('LEGACY',PORT_METHOD),help='Verify frozen new port input; never migrate native state')
    create.add_argument('--energy-attitude-policy',choices=('LEGACY',SOLAR_METHOD),help='Verify frozen optional paid solar policy; never migrate input')
    create.add_argument('--runner-store-policy',choices=('LEGACY',SEGMENTED),default='LEGACY',help='Immutable wrapper policy selected only for this new store')
    create.add_argument('--publication-profile',choices=('LEGACY_RAW',COMPACT_METHOD),default='LEGACY_RAW')
    configure=commands.add_parser('configure',help='Freeze a new initial root; no worker is launched')
    configure.add_argument('--service-policy',choices=('LEGACY',POWER_SERVICE_METHOD),default='LEGACY',help='Explicit immutable operational policy for this new experiment only')
    configure.add_argument('--battery-port-policy',choices=('LEGACY',PORT_METHOD),default='LEGACY')
    configure.add_argument('--energy-attitude-policy',choices=('LEGACY',SOLAR_METHOD),default='LEGACY',help='Explicit ASSUMED onboard paid Sun-point/charge policy for new root only')
    configure.add_argument('--runner-store-policy',choices=('LEGACY',SEGMENTED),default='LEGACY',help='New-store population/reservation contract; never migrates an existing store')
    configure.add_argument('--publication-profile',choices=('LEGACY_RAW',COMPACT_METHOD),default='LEGACY_RAW')
    configure.add_argument('--base-input',type=Path,required=True,help='Existing immutable root at its original initial authority')
    configure.add_argument('--duration-seconds',type=int,required=True)
    configure.add_argument('--study',choices=('LEGACY','COMMON_ASSUMED_V1'),default='COMMON_ASSUMED_V1')
    configure.add_argument('--ageing-multiplier',type=float,choices=(.5,1.,2.),default=1.)
    configure.add_argument('--integration',choices=('ADAPTIVE','DETAILED','FINER'),default='ADAPTIVE')
    configure.add_argument('--latency-seconds',type=int,default=1)
    configure.add_argument('--cadence-seconds',type=int,default=900)
    configure.add_argument('--quiet-maximum-seconds',type=int,default=60)
    configure.add_argument('--quiet-energy-error-wh',type=float,default=2e-5)
    configure.add_argument('--quiet-temperature-error-k',type=float,default=.002)
    configure.add_argument('--quiet-retention-error',type=float,default=1e-9)
    configure.add_argument('--quiet-relative-error',type=float,default=1e-7)
    configure.add_argument('--status-minimum-wall-seconds',type=float,default=1.)
    configure.add_argument('--working-checkpoint-events',type=int,default=1024)
    configure.add_argument('--save-input',type=Path,help='Optional new external exact root document; fails if it already exists')
    for name in ('start','resume','diagnostic'):
        run=commands.add_parser(name);run.add_argument('--intent-key',required=True,help='Persist and reuse this exact key after response loss')
        run.add_argument('--execution-seconds',type=int,default=420);run.add_argument('--maximum-output-bytes',type=int,default=None)
        if name!='start':run.add_argument('--parent-job',required=True);run.add_argument('--snapshot-sha256',required=True)
        if name=='diagnostic':run.add_argument('--until-seconds',type=int,required=True);run.add_argument('--verbose',action='store_true')
    report=commands.add_parser('report');report.add_argument('--job')
    export=commands.add_parser('export');export.add_argument('--job',required=True)
    history=commands.add_parser('checkpoints');history.add_argument('--job',required=True);history.add_argument('--before',type=int);history.add_argument('--limit',type=int,default=16)
    chain=commands.add_parser('chain-create',help='Freeze a finite automatic same-policy continuation plan; no dispatch')
    chain.add_argument('--chain-id',required=True);chain.add_argument('--execution-seconds',type=int,default=1550)
    chain.add_argument('--soft-stop-seconds',type=int,default=1250);chain.add_argument('--maximum-primary-segments',type=int,default=6)
    chain.add_argument('--maximum-observed-seconds',type=int,default=9600);chain.add_argument('--maximum-output-bytes',type=int,default=128*2**20)
    for name in ('chain-run','chain-stop','chain-status'):
        c=commands.add_parser(name);c.add_argument('--chain-id',required=True)
        if name=='chain-run':c.add_argument('--command-key',required=True,help='Reuse exact durable key after response loss')
    args=p.parse_args(argv)
    if args.command=='create':
        root=loads_root(args.input.read_bytes())
        if args.service_policy is not None and root.service_policy!=requested_service_policy(args.service_policy):raise ValueError('input operational policy differs; create never migrates or retags it')
        if args.battery_port_policy is not None and root.battery_port_policy!=requested_port_policy(args.battery_port_policy):raise ValueError('input port policy differs')
        if args.energy_attitude_policy is not None and root.energy_attitude_policy!=requested_energy_policy(args.energy_attitude_policy):raise ValueError('input solar policy differs; create never migrates')
        store=LifecycleStore(args.store,root,create=True,runner_policy=requested_runner_policy(args.runner_store_policy),publication_profile=requested_profile(args.publication_profile))
        print(json.dumps(store.snapshot(),ensure_ascii=False,allow_nan=False));return
    if args.command=='configure':
        from dataclasses import asdict
        prior=loads_root(args.base_input.read_bytes())
        policy=dict(quiet_step_seconds=60,detailed_step_seconds=2,lighting_step_seconds=60,contact_integration_level=2,latency_seconds=args.latency_seconds)
        if args.integration=='ADAPTIVE':
            policy['quiet_solver']=dict(maximum_macro_seconds=args.quiet_maximum_seconds,absolute_energy_wh=args.quiet_energy_error_wh,
                absolute_temperature_k=args.quiet_temperature_error_k,absolute_retention=args.quiet_retention_error,relative_tolerance=args.quiet_relative_error)
        elif args.integration=='DETAILED':policy.update(quiet_step_seconds=2)
        else:policy.update(quiet_step_seconds=30,detailed_step_seconds=1,contact_integration_level=3)
        root=requested_lifecycle_root(prior.base,args.duration_seconds,policy_data=policy,
            scenario_data=dict(cadence_seconds=args.cadence_seconds),sun_mode=prior.sun_mode,
            study_preset=args.study,ageing_multiplier=args.ageing_multiplier,
            service_policy=args.service_policy,
            energy_attitude_policy=args.energy_attitude_policy,battery_port_policy=args.battery_port_policy,
            output_data=dict(publication_minimum_wall_seconds=args.status_minimum_wall_seconds,working_checkpoint_every_events=args.working_checkpoint_events))
        if args.save_input is not None:
            if any((p/'.git').exists() for p in (args.save_input.parent,*args.save_input.parents)):raise ValueError('input export must remain outside repositories')
            with args.save_input.open('xb') as stream:stream.write(dumps_root(root))
        store=LifecycleStore(args.store,root,create=True,runner_policy=requested_runner_policy(args.runner_store_policy),publication_profile=requested_profile(args.publication_profile));print(json.dumps(store.snapshot(),ensure_ascii=False,allow_nan=False));return
    store=LifecycleStore(args.store)
    if args.command.startswith('chain-'):
        from ops_sim.v5.lifecycle_chain import LifecycleChain,make_plan
        from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
        plan=None
        if args.command=='chain-create':
            budget=ExecutionBudget(args.execution_seconds,args.soft_stop_seconds,args.execution_seconds-args.soft_stop_seconds)
            if store.root_input.energy_attitude_policy is None:
                plan=make_plan(store,chain_id=args.chain_id,execution_budget=budget,maximum_primary_segments=args.maximum_primary_segments,maximum_output_bytes=args.maximum_output_bytes,maximum_observed_seconds=args.maximum_observed_seconds)
            else:
                from m8_battery_chain_cli import create_for_store as battery_create_for_store
                from m8_compact_chain_cli import create_for_store
                if store.root_input.battery_port_policy is not None:create_for_store=battery_create_for_store
                chain=create_for_store(store,args.chain_id,budget,args.maximum_primary_segments,args.maximum_output_bytes,args.maximum_observed_seconds)
        if store.root_input.energy_attitude_policy is None:chain=LifecycleChain(store,args.chain_id,plan=plan)
        elif args.command!='chain-create':
            from m8_battery_chain_cli import ResourceChain as BatteryResourceChain
            from m8_compact_chain_cli import ResourceChain
            if store.root_input.battery_port_policy is not None:ResourceChain=BatteryResourceChain
            chain=ResourceChain(store,args.chain_id)
        try:
            if args.command=='chain-run':result=chain.run(args.command_key)
            elif args.command=='chain-stop':result=chain.stop()
            else:result=chain.snapshot()
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        except KeyboardInterrupt:
            chain.stop();raise
        finally:chain.runner.close()
        return
    if args.command=='report':
        result=store.snapshot() if args.job is None else store.job(args.job)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return
    if args.command=='export':
        print(json.dumps(store.export(args.job),ensure_ascii=False,allow_nan=False));return
    if args.command=='checkpoints':
        print(json.dumps(store.checkpoint_history(args.job,before=args.before,limit=args.limit),ensure_ascii=False,allow_nan=False));return
    intent=make_intent(store.root_input.identity,key=args.intent_key,
        parent_job_id=None if args.command=='start' else args.parent_job,
        snapshot_sha256=None if args.command=='start' else args.snapshot_sha256,
        mode='MAIN' if args.command!='diagnostic' else 'DIAGNOSTIC_VERBOSE' if args.verbose else 'DIAGNOSTIC_NORMAL',
        window_end_seconds=args.until_seconds if args.command=='diagnostic' else None,
        publication_profile=store.publication_profile,profile_bound=store.publication_profile is not None,execution_seconds=args.execution_seconds,maximum_output_bytes=args.maximum_output_bytes if args.maximum_output_bytes is not None else (256 if store.root_input.output_policy is not None else 128)*2**20)
    runner=LifecycleRunner(store)
    try:
        job=runner.submit(intent)
        # A known duplicate returns its saved identity and never restarts it.
        if runner.thread is not None:runner.thread.join(args.execution_seconds+3)
        if runner.thread is not None and runner.thread.is_alive():raise RuntimeError('owned lifecycle dispatch did not settle inside execution/cleanup envelope')
        result=store.job(job['job_id']);print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        if result['status']!='COMPLETED':raise SystemExit(2)
    except KeyboardInterrupt:
        if runner.active is not None:runner.stop(runner.active)
        raise
    finally:runner.close()


if __name__=='__main__':main()
