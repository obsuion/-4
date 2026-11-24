"""Reproduce Task05E tables, refinement screens, conservation checks and figures."""
from fractions import Fraction
from dataclasses import replace
import argparse
import csv
import hashlib
import json
from math import fsum
import os
from pathlib import Path

from .v5_design_trade_study import encode, output_directory, read_matching
from ops_sim.v5.experiment_codec import decode_content


def prepare_mass_screen(directory):
    """Freeze a layout-only mass uncertainty check before main outcomes."""
    from ops_sim.v5.design_trade_design import DesignAssumptions, enumerate_designs, design_record
    declaration=directory/'pilot-declaration.json'
    value=json.loads(declaration.read_text(encoding='utf-8'))
    if (directory/'protocol.json').exists(): raise ValueError('mass screen must be declared before protocol freeze')
    screen={'scope':'design feasibility only; no additional mission simulations or nominal reselection',
        'core_mass_kg':[68.,72.],'mass_ceiling_kg':78.,'source':value['source'],
        'designs':{str(m):[design_record(d) for d in enumerate_designs(replace(DesignAssumptions(),core_mass_kg=m))]
            for m in (68.,72.)}}
    path=directory/'mass-screen.json'
    with path.open('x',encoding='utf-8',newline='\n') as stream: stream.write(encode(screen))
    value['mass_screen_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    declaration.write_text(encode(value),encoding='utf-8')
    print(encode({'mass_screen_sha256':value['mass_screen_sha256'],'layout_cases':24,'mission_runs':0}))
    return 0


def score(result):
    return Fraction(*result['summary']['weighted_credit'])


def table(path,rows):
    if not rows: return
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def qualify_pair(low,high):
    a,b=low['summary'],high['summary']
    fine={tuple(s['time']):s for s in b['physical_samples']}
    missing=[s['time'] for s in a['physical_samples'] if tuple(s['time']) not in fine]
    common=[s for s in a['physical_samples'] if tuple(s['time']) in fine]
    energy=max((abs(s['energy_wh']-fine[tuple(s['time'])]['energy_wh']) for s in common),default=0.)
    temperature=max((abs(t-fine[tuple(s['time'])]['temperatures_k'][n])
        for s in common for n,t in s['temperatures_k'].items()),default=0.)
    phase_equal=a['phase_seconds']==b['phase_seconds']
    request_equal=a['requests']==b['requests']
    decisions=lambda s:[(e['phase'],e['start_seconds'],e['end_seconds'],e['request_id'],e['start_angle_hex'],e['end_angle_hex']) for e in s['events']]
    decision_equal=decisions(a)==decisions(b) and a['rejections']==b['rejections']
    energy_bound=.001*low['design']['capacity_wh']
    return {'pair':low['case']['case_id'].rsplit('__L',1)[0],
        'exact_credit':a['weighted_credit']==b['weighted_credit'],'exact_requests':request_equal,
        'exact_phases':phase_equal,'exact_decisions':decision_equal,'missing_coarse_times':len(missing),
        'common_samples':len(common),'max_energy_difference_wh':energy,'energy_bound_wh':energy_bound,
        'max_temperature_difference_k':temperature,'temperature_bound_k':.1,
        'passed':not missing and a['weighted_credit']==b['weighted_credit'] and request_equal
            and phase_equal and decision_equal and energy<=energy_bound and temperature<=.1}


def energy_checks(result):
    s=result['summary'];a=s['accounting'];d=s['diagnostic_energy_wh'];spec=s['spec']
    # Independent accumulated conservation equalities, in Wh. The predeclared
    # 1e-9 Wh accounting screen permits accumulated binary64 roundoff, at
    # one millionth of a mWh. Report actual work count and ledger magnitudes;
    # this is not a proof of forward-error or time-integration accuracy.
    residuals={
        'source_split_wh':d['solar_source_wh']-fsum((d['solar_bus_wh'],d['solar_wire_loss_wh'],d['solar_converter_loss_wh'])),
        'solar_eps_wh':d['solar_bus_wh']-a['generation_wh'],
        'load_eps_wh':fsum((d['terminal_load_wh'],d['load_wire_loss_wh']))-a['requested_load_wh'],
        'bus_balance_wh':fsum((a['generation_wh'],a['discharge_output_wh']))-fsum((a['served_load_wh'],a['charge_input_wh'],a['curtailed_generation_wh'])),
        'battery_balance_wh':s['final_energy_wh']-(result['design']['capacity_wh']*spec['initial_fraction']
            +a['charge_input_wh']*spec['assumptions']['charge_efficiency']
            -a['discharge_output_wh']/spec['assumptions']['discharge_efficiency']-a['unavailable_energy_wh']),
        'rest_to_rest_kinetic_heat_wh':d.get('actuator_heat_adjustment_wh',0.),
        # The accepted internal_dissipation ledger excludes the separately
        # exported battery_conversion_heat. Do not add that loss twice.
        'retained_internal_heat_wh':a['routed_internal_heat_wh']-fsum((a['served_load_wh'],d.get('actuator_heat_adjustment_wh',0.)))}
    return {'case_id':result['case']['case_id'],**residuals,'bound_wh':1e-9,
        'physical_substeps':a.get('numerical_substeps'),
        'largest_energy_magnitude_wh':max(abs(s['final_energy_wh']),result['design']['capacity_wh'],
            *(abs(v) for k,v in a.items() if k.endswith('_wh'))),
        'passed':all(abs(v)<=1e-9 for v in residuals.values())}


def selection(results,group,workload):
    subset=[r for r in results if r['case']['group']==group and r['case']['spec']['workload']==workload and r['case']['spec']['level']==2]
    full={r['case']['spec']['design_id']:score(r) for r in subset if r['case']['spec']['variant']=='FULL'}
    simple={r['case']['spec']['design_id']:score(r) for r in subset if r['case']['spec']['variant']=='RESOURCE_ONLY'}
    if set(full)!=set(simple) or not full: raise ValueError('incomplete paired design set')
    best_full=max(full.values());best_simple=max(simple.values())
    preferred=sorted(d for d,s in simple.items() if s==best_simple)
    gap=[best_full-max(full[d] for d in preferred),best_full-min(full[d] for d in preferred)]
    return {'group':group,'workload':workload,'full_best_designs':sorted(d for d,s in full.items() if s==best_full),
        'resource_preferred_designs':preferred,'best_full_credit':str(best_full),'best_resource_credit':str(best_simple),
        'full_credit_of_resource_preferred':{d:str(full[d]) for d in preferred},'selection_loss_range':[str(x) for x in gap]}


def figures(directory,protocol,results):
    os.environ.setdefault('MPLCONFIGDIR',str(directory/'matplotlib-config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})
    fig,axes=plt.subplots(1,2,figsize=(11,4.2),layout='constrained')
    for d in protocol['designs']:
        selected=d['design_id'] in protocol['selected_designs']
        color='#146B8C' if selected else '#aaa'
        axes[0].scatter(d['capacity_wh'],45*d['arrays'],s=90 if selected else 55,
            marker='o' if d['accepted'] else 'x',color=color)
        axes[0].annotate(d['design_id'],(d['capacity_wh'],45*d['arrays']),xytext=(0,7),textcoords='offset points',ha='center',fontsize=8)
        if selected:
            axes[1].scatter(d['total_mass_kg'],d['inertia_y_kg_m2'],s=90,color='#146B8C')
            axes[1].annotate(d['design_id'],(d['total_mass_kg'],d['inertia_y_kg_m2']),xytext=(0,8),textcoords='offset points',ha='center',fontsize=9)
    axes[0].set(xlabel='Working battery capacity (Wh)',ylabel='Nominal array interface power (W)',title='Bounded component space: circles feasible, crosses rejected',ylim=(65,305))
    axes[1].axvline(78,color='#A44828',linestyle='--',label='78 kg ceiling')
    axes[1].set(xlabel='Actual total mass (kg)',ylabel='Deployed inertia about y (kg m²)',title='Selected feasible designs',ylim=(10.3,12.5))
    axes[1].legend(loc='lower right');axes[0].grid(alpha=.15);axes[1].grid(alpha=.15)
    fig.savefig(directory/'figure-design-trade.png');fig.savefig(directory/'figure-design-trade.pdf');plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    names=protocol['selected_designs'];x=list(range(len(names)))
    for col,work in enumerate(('relaxed','close')):
        for variant,offset,color,label in (('FULL',-.18,'#146B8C','FULL'),('RESOURCE_ONLY',.18,'#C48524','Resource-only')):
            rr=[next(r for r in results if r['case']['group']=='nominal' and r['case']['spec']['design_id']==d
                and r['case']['spec']['workload']==work and r['case']['spec']['variant']==variant and r['case']['spec']['level']==2) for d in names]
            axes[0,col].bar([i+offset for i in x],[100*float(score(r)) for r in rr],.35,color=color,label=label)
            axes[1,col].bar([i+offset for i in x],[r['summary']['phase_seconds'].get('motion',0)+r['summary']['phase_seconds'].get('settle',0) for r in rr],.35,color=color)
        axes[0,col].set(title=work.capitalize()+' workload',ylabel='Delivered priority by deadline (%)',ylim=(0,110),xticks=x,xticklabels=names)
        axes[1,col].set(ylabel='Executed motion + settling (s)',xticks=x,xticklabels=names)
        axes[0,col].legend();axes[0,col].grid(axis='y',alpha=.15);axes[1,col].grid(axis='y',alpha=.15)
    fig.savefig(directory/'figure-full-ablation.png');fig.savefig(directory/'figure-full-ablation.pdf');plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--prepare-mass-screen',action='store_true')
    args=parser.parse_args();directory=output_directory(args.output)
    if args.prepare_mass_screen: return prepare_mass_screen(directory)
    protocol_path=directory/'protocol.json'
    if hashlib.sha256(protocol_path.read_bytes()).hexdigest()!=(directory/'protocol.sha256').read_text().strip():
        raise ValueError('frozen protocol hash mismatch')
    protocol=json.loads(protocol_path.read_text(encoding='utf-8'))
    mass_path=directory/'mass-screen.json'
    if hashlib.sha256(mass_path.read_bytes()).hexdigest()!=protocol['mass_screen_sha256']:
        raise ValueError('predeclared mass sensitivity differs')
    mass_screen=json.loads(mass_path.read_text(encoding='utf-8'))
    results=[];inventory=[]
    for case in protocol['cases']:
        r=read_matching(directory,case,protocol['source'])
        inventory.append({'case_id':case['case_id'],'status':'missing' if r is None else 'success'})
        if r is not None: results.append(r)
    (directory/'verified-run-inventory.json').write_text(encode(inventory),encoding='utf-8')
    if len(results)!=len(protocol['cases']): raise ValueError('study incomplete; see verified run inventory')
    by_id={r['case']['case_id']:r for r in results}
    pairs=[qualify_pair(r,by_id[r['case']['case_id'][:-1]+'2']) for r in results
        if r['case']['group']=='nominal' and r['case']['spec']['level']==1]
    energy=[energy_checks(r) for r in results]
    selections=[selection(results,'nominal',w) for w in ('relaxed','close')]
    selections += [selection(results,g,'close') for g in sorted({r['case']['group'] for r in results}-{'nominal'})]
    table(directory/'numerical-pairs.csv',pairs);table(directory/'energy-checks.csv',energy)
    compact=[]
    for r in results:
        s=r['summary'];d=r['design'];p=s['phase_seconds'];e=s['diagnostic_energy_wh']
        contacts=[decode_content(event['outcome']) for event in s['events'] if event['phase']=='contact']
        tx_seconds=sum((c.tx_on_seconds.fraction for c in contacts),Fraction(0))
        contact_idle=sum((c.idle_seconds.fraction for c in contacts),Fraction(0))
        compact.append({'case_id':r['case']['case_id'],'group':r['case']['group'],
            'design':s['spec']['design_id'],'workload':s['spec']['workload'],'variant':s['spec']['variant'],
            'level':s['spec']['level'],'priority_credit':str(score(r)),
            'completed_products':sum(x['credited_products'] for x in s['requests']),
            'motion_seconds':p.get('motion',0),'settle_seconds':p.get('settle',0),'hold_seconds':p.get('hold',0),
            'imaging_seconds':p.get('imaging',0),'contact_seconds':p.get('contact',0),
            'tx_on_seconds_exact':str(tx_seconds),'contact_idle_seconds_exact':str(contact_idle),
            'total_idle_seconds_exact':str(contact_idle+p.get('hold',0)),
            'final_energy_wh':s['final_energy_wh'],'minimum_energy_wh':s['minimum_energy_wh'],
            'generation_wh':s['accounting']['generation_wh'],'actuator_wh':e['actuator_electrical_wh'],
            'solar_wire_heat_wh':e['solar_wire_loss_wh'],'load_wire_heat_wh':e['load_wire_loss_wh'],
            'regulator_heat_wh':e['solar_converter_loss_wh'],'mass_kg':d['total_mass_kg'],
            'spare_mass_kg':d['spare_mass_kg'],'inertia_y_kg_m2':d['inertia_y_kg_m2'],
            'min_temperature_k':min(v for a in s['physical_samples'] for v in a['temperatures_k'].values()),
            'max_temperature_k':max(v for a in s['physical_samples'] for v in a['temperatures_k'].values()),
            'rejected_requests':len(s['rejections']),
            'active_rejection_reasons':';'.join(sorted({reason for _,reason in s['rejections']})),
            'unmet_wh':s['accounting']['unmet_load_wh']})
    table(directory/'case-summary.csv',compact)
    products=[{'case_id':r['case']['case_id'],**p} for r in results for p in r['summary']['requests']]
    table(directory/'products.csv',products)
    designs=[{'design':d['design_id'],'accepted':d['accepted'],'selected':d['design_id'] in protocol['selected_designs'],
        'constraints':','.join(d['rejection_reasons']),'mass_kg':d['total_mass_kg'],'spare_mass_kg':d['spare_mass_kg'],
        'capacity_wh':d['capacity_wh'],'solar_w':45*d['arrays'],'inertia_y_kg_m2':d['inertia_y_kg_m2'],
        'battery_occupied_volume_m3':d['battery_occupied_volume_m3'],'deployed_span_m':d['deployed_span_m']} for d in protocol['designs']]
    table(directory/'designs.csv',designs)
    table(directory/'core-mass-sensitivity.csv',[{'core_mass_kg':mass,'design':d['design_id'],
        'accepted':d['accepted'],'mass_kg':d['total_mass_kg'],'constraints':','.join(d['rejection_reasons'])}
        for mass,ds in mass_screen['designs'].items() for d in ds])
    chosen=[d for d in protocol['designs'] if d['design_id'] in protocol['selected_designs']]
    costs=[]
    for i,a in enumerate(chosen):
        for b in chosen[i+1:]:
            delta={k:a['cost_expression'][k]-b['cost_expression'][k] for k in a['cost_expression'] if k!='meaning'}
            db,da=delta['BP8_pack'],delta['TSP_complete']
            ratio=(None if db==0 else {'lhs':'c_B / c_A',
                'constant':-da/db,'harness_ratio_coefficient':-delta['external_harness_kg']/db,
                'rhs':'constant + harness_ratio_coefficient * (c_h / c_A)',
                'definitions':{'c_B':'BP8 pack + pack mount cost',
                    'c_A':'complete TSP + adapter + one-half regulator bank cost',
                    'c_h':'external harness cost per kg'},
                'scope':'formal break-even ratio with positive unknown costs; no claimed market prices'})
            costs.append({'A':a['design_id'],'B':b['design_id'],'A_minus_B_coefficients':delta,
                'break_even':'sum(delta_i * unknown_unit_cost_i) = 0; costs unverified',
                'battery_to_array_cost_ratio':ratio})
    evidence={'cases_completed':len(results),'cases_failed':0,'cases_missing':0,'refinement_pairs':pairs,
        'energy_checks':energy,'selection':selections,'cost_break_even':costs,
        'qualification_passed':all(p['passed'] for p in pairs) and all(e['passed'] for e in energy),
        'source_sha256':protocol['source']['sha256'],'protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest()}
    (directory/'comparison-evidence.json').write_text(encode(evidence),encoding='utf-8')
    figures(directory,protocol,results)
    lines=['# Task05E bounded coupled design trade — Methods / Results / Limitations','',
        '## Methods','',
        'The frozen protocol compares the same physically screened component allocations under FULL and a resource-only analytical counterfactual. Both use the same received requests, earliest-window controller, reference MS product definition, forcing and protected physical executors. FULL uses derived inertia and sized external wiring; the counterfactual uses common core inertia and ideal wiring. Both pay actual maneuver, settling, holding, acquisition and contact time and electricity. Bodies and locked wing normals rotate together. No free solar tracking is used.',
        '',f"The predeclared study completed {len(results)} cases: {sum(r['case']['group']=='nominal' for r in results)} nominal and {sum(r['case']['group']!='nominal' for r in results)} sensitivity. The two successful source/input-matched timing pilots are reused. Fallback used: {protocol['fallback_used']}. Protocol SHA-256: `{evidence['protocol_sha256']}`.",'',
        '## Results','', '|Workload|Design|Variant|Priority credit|Products|Motion + settle (s)|Minimum battery (Wh)|',
        '|---|---|---|---:|---:|---:|---:|']
    for r in compact:
        if r['group']=='nominal' and r['level']==2:
            lines.append(f"|{r['workload']}|{r['design']}|{r['variant']}|{r['priority_credit']}|{r['completed_products']}|{r['motion_seconds']+r['settle_seconds']}|{r['minimum_energy_wh']:.6f}|")
    lines+=['','Primary preference is maximum delivered priority by deadline; all ties are retained. Secondary metrics do not silently break these ties.']
    for s in selections:
        lines.append(f"- {s['group']}/{s['workload']}: FULL best tested {', '.join(s['full_best_designs'])} ({s['best_full_credit']}); resource-preferred {', '.join(s['resource_preferred_designs'])} ({s['best_resource_credit']}); applying those choices to FULL gives selection-loss range {s['selection_loss_range']}.")
    lines+=['',f"All {len(pairs)} nominal refinement pairs passed: {all(p['passed'] for p in pairs)}. Maximum common-time battery difference {max(p['max_energy_difference_wh'] for p in pairs):.9g} Wh; temperature difference {max(p['max_temperature_difference_k'] for p in pairs):.9g} K. Exact request, phase and decision equality is checked separately in numerical-pairs.csv. All {len(energy)} accumulated energy checks passed: {all(e['passed'] for e in energy)}.",
        '', '## Limitations','',
        'These are synthetic, short-horizon comparisons of tested designs, not a global optimum or a flight/hardware campaign. The core mass distribution, thermal material/boundary parameters, actuator electrical draw and mode-power map remain assumptions. Regulator-equivalent interfaces are not catalog integration certification. Structural screening does not qualify deployment, stiffness or flexible dynamics. Panel temperatures are not evolved; external PV-wire/regulator heat is separately exported. The first moving eclipse crossing uses midpoint quadrature; the refinement screen is not a rigorous continuous error bound. Protection is sampled. The same reference optical sampling/product approximation is retained at different pointings. Sensitivity cases use L2 only and are not independently refinement-qualified across the entire uncertainty domain.',
        '', 'No monetary prices are claimed. cost_break_even contains named unknown coefficients and pairwise zero-difference equations, rather than an economic winner. Failed development invocations and their corrections are retained separately from the completed frozen study. Accepted 05C/05D studies remain separate. Full V5, J2 temporal visibility, propulsion, OBC processing and long-horizon qualification remain open.']
    (directory/'METHODS_RESULTS_LIMITATIONS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(encode({'cases':len(results),'refinement_pairs':len(pairs),'qualification_passed':evidence['qualification_passed'],
        'selection':selections[:2]}))
    return 0 if evidence['qualification_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
