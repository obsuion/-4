"""Compare accepted simulation exports. Python 3.10+, standard library. No simulation."""
import argparse, bisect, csv, gzip, hashlib, io, json, zipfile
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

def require(ok, why):
    if not ok:
        raise ValueError(why)

def digest(fileobj):
    h=hashlib.sha256()
    for b in iter(lambda:fileobj.read(1<<20), b''):
        h.update(b)
    return h.hexdigest()

def inspect(path, label):
    with path.open('rb') as fp: arcsha=digest(fp)
    with zipfile.ZipFile(path) as z:
        def readj(name): return json.loads(z.read(name))
        cov=readj('COVERAGE.json')
        require(cov['case']==label,'case mismatch')
        for name,v in readj('FILES-SHA256.json').items():
            with z.open(name) as fp: require(digest(fp).lower()==v['sha256'].lower(),name)
        reqs=list(csv.DictReader(io.TextIOWrapper(z.open('requests.csv'),encoding='utf-8-sig')))
        ids=[r['request_id'] for r in reqs]
        times=[int(r['release_seconds']) for r in reqs]
        require(len(ids)==len(set(ids))==8640 and all(b-a==900 for a,b in zip(times,times[1:])),'population or cadence')
        solar=[0]*len(ids)
        direct=defaultdict(list); adds={}; credits={}; exp=0; reasons=Counter(); kinds=Counter(); solwall=Counter(); modes=Counter()
        focus=[]; last=cov['source_start']; ni=0
        with gzip.GzipFile(fileobj=z.open('events.jsonl.gz')) as fp:
            for line in fp:
                d=json.loads(line); r=d['record']; a,b=r['start_seconds'],r['end_seconds']
                require(d['event_index']==ni and r['index']==ni and a==last and b>=a,'continuity at '+str(ni))
                last=b; ni+=1; kind=r['kind']; rid=r['request_id']; kinds[kind]+=1
                exp+=r['expired_count']; modes[r['power_service']['mode']]+=b-a
                for offer in r['new_offers']:
                    k=offer['request_id']; require(k not in adds,'duplicate offer'); adds[k]=offer['release_seconds']
                for cr in r['credits']:
                    k=cr['request_id']; require(k not in credits,'duplicate credit'); credits[k]=cr
                if r['status']=='refused': reasons[r['reason']]+=1
                if rid: direct[rid].append((kind,r['status'],r['reason'],ni-1,a,b))
                if kind in ('SOLAR_POINT','SOLAR_HOLD') and b>a:
                    solwall[kind]+=b-a
                    # Exposure eligibility is [release, release + 180], as in both scenario roots.
                    for i in range(max(0,bisect.bisect_right(times,a-180)),bisect.bisect_left(times,b)):
                        solar[i]+=max(0,min(b,times[i]+180)-max(a,times[i]))
                if b>=5754728-2 and a<=5754728+610:
                    focus.append(dict(event_index=d['event_index'],start_offset=a-5754728,end_offset=b-5754728,kind=kind,status=r['status'],id=rid,reason=r['reason'],mode=r['power_service']['mode'],solar_phase=r['solar_attitude'].get('phase'),credits=[v['request_id'] for v in r['credits']],expired_count=r['expired_count']))
        require(last==7776128 and len(credits)+exp==len(ids) and dict(zip(ids,times))==adds,'closure')
        require(ni==cov['event_records'] and reasons==cov['reason_original_counts'],'export disagree')
        require({c['request_id'] for c in readj('credits.json')}==set(credits),'credit index disagree')
        rows={}
        for i,r in enumerate(reqs):
            k=ids[i]; seq=direct[k]; cr=credits.get(k)
            require((cr is not None)==(r['outcome']=='CREDITED') and int(r['actions'])==len(seq),'request index mismatch: '+k)
            code='CREDIT' if cr else ('NO_ACTION' if not seq else seq[-1][2])
            rows[k]=dict(category=code,actions=len(seq),first_event=seq[0][3] if seq else None,last_event=seq[-1][3] if seq else None,solar_s_in_window=solar[i],credit_time=str(Fraction(*map(int,cr['completion_time']))) if cr else None,credit_bits=cr['useful_bits'] if cr else 0,release=times[i],ordinal=i)
        return rows,dict(sha256=arcsha,events=ni,unique_requests=len(adds),expiry_counter=exp,credits=len(credits),accepted_jobs=cov['accepted_causal_jobs'],curve_sample_info=readj('STATE-COVERAGE.json')['progress_boundary_samples'],reason_event_counts=reasons,request_groups=Counter(v['category'] for v in rows.values()),solar_duration_s=solwall,power_mode_seconds=modes,no_action_solar_seconds=dict(Counter(v['solar_s_in_window'] for v in rows.values() if v['category']=='NO_ACTION')),requests_per_30d=[sum(1 for k,v in rows.items() if v['category']=='CREDIT' and i*2880<=v['ordinal']<(i+1)*2880) for i in range(3)]),focus

def main():
    p=argparse.ArgumentParser();p.add_argument('d1',type=Path);p.add_argument('d2',type=Path);p.add_argument('dest',type=Path);a=p.parse_args()
    a.dest.mkdir(parents=True,exist_ok=True)
    d1,m1,f1=inspect(a.d1,'D1');d2,m2,f2=inspect(a.d2,'D2')
    require(set(d1)==set(d2) and all(v['release']==d2[k]['release'] for k,v in d1.items()),'unmatched requests')
    pairs=Counter()
    with (a.dest/'requests_paired.csv').open('w',encoding='utf-8',newline='') as fp:
        out=csv.writer(fp); fields=['category','actions','first_event','last_event','solar_s_in_window','credit_time','credit_bits']
        out.writerow(['ordinal','request_id','release_clock','model_day']+[g+'_'+f for g in ('D1','D2') for f in fields])
        for k,v in d1.items():
            w=d2[k]; pairs[v['category'],w['category']]+=1
            out.writerow([v['ordinal'],k,v['release'],1+(v['release']-128)//86400]+[r[f] for r in (v,w) for f in fields])
    def save(n,obj): (a.dest/n).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save('evidence.json',dict(D1=m1,D2=m2,transitions=[dict(D1=k[0],D2=k[1],count=v) for k,v in pairs.most_common()],case_6394=dict(D1=f1,D2=f2)))
if __name__=='__main__': main()
