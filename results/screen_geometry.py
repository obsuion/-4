"""Read-only independent geometry screening, not a mission replay. Python >=3.9 + NumPy.
Example: python geometry_screen.py --d1 D1-90D-EVENTS.zip --d2 D2-90D-EVENTS.zip --out screening.csv
Supply --core KAZEOSAT-CORE-DIRECT90D-CREATE-R2-review.zip to verify frozen orbit/target inputs.
Default is portable. An independently built compatible integration library is optional.
"""
import argparse,csv,ctypes as C,gzip,io,json,math,pathlib,zipfile
from collections import Counter,defaultdict
import numpy as np
pa=argparse.ArgumentParser(description=__doc__)
for k in ['d1','d2','core','fast-library','out']:pa.add_argument('--'+k)
a=pa.parse_args()
gm,j2,rg=4.0e14,0.0009765625,6400000.
s0=np.array([6326533.269375081,126547.53884264459,2932645.420002207,0.,7500.,0.])
dt=10.;ep=128.;omega=7.292115e-5;lat=math.radians(25);aearth,flatten=6378137.,0.0033528106647474805
if a.core:
 def clean(d):
  if isinstance(d,list):return [clean(x) for x in d]
  if not isinstance(d,dict):return d
  if d.get('kind')=='float':return float.fromhex(d['value'])
  if d.get('kind')=='int':return int(d['value'])
  for k in ['rolling_tuple','immutable_input','typed','fields','items','value','member']:
   if k in d:return clean(d[k])
  return {k:clean(v) for k,v in d.items() if k not in ('provenance','type','kind')}
 with zipfile.ZipFile(a.core) as z:
  for case in ['D1_BALANCED','D2_LIGHT']:
   f=f'gates/INITIAL02/results/prepared/{case}/P64/root-input.json'
   m=json.loads(z.read(f))['inputs']['base']['inputs']['reference']['inputs']['fields']['model']['fields']
   tr=clean(m['environment']['immutable_input']['fields']['trajectory']);cat=clean(m['catalog']);p=tr['initial_state']['position'];e=p['frame']['ellipsoid'];rot=p['frame']['rotation']
   assert tr['gravity_model']==dict(gravitational_parameter_m3_s2=gm,j2=j2,reference_radius_m=rg)
   assert ep==p['instant']['elapsed_seconds'] and dt==clean(m['nominal_policy'])['step_seconds']
   assert (e['equatorial_radius_m'],e['flattening'],rot['angular_velocity_rad_per_s'],rot['initial_phase_rad'])==(aearth,flatten,omega,0)
   assert np.array_equal(s0,p['components_m']+tr['initial_state']['velocity']['components_m_per_s'])
   for item,name,h in [(cat[0],'target',1000.),(cat[2],'station',120.)]:
    q=item['point']; assert (q['latitude_rad'],q['longitude_rad'],q['point_id'],q['ellipsoidal_height_m'],item['visibility_policy']['minimum_elevation_rad'])==(lat,0.,name,h,0.)
   assert cat[2]['nominal_rate_bps']==1000
 if a.core: print('Matched source input parameters for both designs.')
if a.fast_library:
 lib=C.CDLL(str(pathlib.Path(a.fast_library).resolve()));A=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
 lib.init.argtypes=[C.c_int,*[C.c_double]*4,A];lib.eval.argtypes=[C.c_int,A,A];lib.init(777600,dt,gm,j2,rg,s0)
 def state(t):
  t=np.array(t,dtype=float)-ep; out=np.empty((t.size,6));lib.eval(t.size,t.ravel(),out);return out.reshape(t.shape+(6,))
else:
 def deriv(x,y,z,vx,vy,vz):
  r2=x*x+y*y+z*z;r=r2**.5; f=-gm/(r*r2);cf=(1.5*j2)*(rg*rg/r2);q=5*z*z/r2
  return vx,vy,vz,f*x*(1-cf*(q-1)),f*y*(1-cf*(q-1)),f*z*(1-cf*(q-3))
 def step(s,h):
  k1=deriv(*s);k2=deriv(*(v+h*.5*k for v,k in zip(s,k1)));k3=deriv(*(v+h*.5*k for v,k in zip(s,k2)));k4=deriv(*(v+h*k for v,k in zip(s,k3)))
  return tuple(v+(h/6)*(a+2*b+2*c+d) for v,a,b,c,d in zip(s,k1,k2,k3,k4))
 grid=np.empty((777601,6));s=tuple(s0.tolist());grid[0]=s
 for i in range(1,777601):s=step(s,dt);grid[i]=s
 def state(t):
  t=np.asarray(t,dtype=float)-ep;j=(t//dt).astype(int);tail=t-j*dt;s=np.moveaxis(grid[j],-1,0)
  return np.moveaxis(step(s,tail),0,-1)
def angles(t,h):
 states=state(t);x,y,z=np.moveaxis(states[...,:3],-1,0)
 e2=1-(1-flatten)**2;phi=t*omega;co,si=np.cos(phi),np.sin(phi);sl,cl=np.sin(lat),np.cos(lat)
 N=aearth/np.sqrt(1.-e2*sl**2);R=(N+h)*cl;Z=(N*(1-e2)+h)*sl
 dx,dy,dz=x-R*co,y-R*si,z-Z;d=np.sqrt(dx*dx+dy*dy+dz*dz)
 elev=np.degrees(np.arcsin(np.clip((dx*cl*co+dy*cl*si+dz*sl)/d,-1,1)))
 off=np.degrees(np.arccos(np.clip((dx*x+dy*y+dz*z)/(d*np.sqrt(x*x+y*y+z*z)),-1,1)))
 return elev,off
T=128+900*np.arange(8640)
def lengths(v):
 res=np.zeros(v.shape[0],int);st=np.zeros_like(res)
 for row in v.T:st=np.where(row,st+1,0);res=np.maximum(res,st)
 return np.maximum(res-1,0)
def screened(t):
 e,off=angles(t[:,None]+np.arange(181),1000);se,_=angles(t[:,None]+np.arange(240,361),120)
 v=e>0;b=v&(off<=45);sv=lengths(se>0)
 # Code checks the 45 deg envelope at capture start. This screen requires visibility
 # at start/end of the four-second exposure. For this geometry these samples also
 # have uninterrupted positive elevation during every intermediate sample.
 starts=b[:,:177]&v[:,4:];continuous=starts.copy()
 for j in [1,2,3]:continuous&=v[:,j:j+177]
 assert np.array_equal(starts,continuous)
 # One 12288-bit sample at declared 1000 bit/s = 12.288s. Try all integer starts
 # leaving this interval within +240..+360; require station visible at endpoints
 # and every intermediate whole second. This is geometry, not RF/transport simulation.
 se_end,_=angles(t[:,None]+np.arange(240,348)+12.288,120)
 radio=se_end>0
 for j in range(13):radio&=se[:,j:j+108]>0
 return np.column_stack([e[:,0],e.max(1),np.where(v,off,np.inf).min(1),np.where(v.any(1),v.argmax(1),-1),np.where(starts.any(1),starts.argmax(1),-1),lengths(b),sv,radio.any(1)&starts.any(1),np.where(radio.any(1),radio.argmax(1)+240,-1)])
G=np.vstack([screened(t) for t in np.array_split(T,24)])
cols=['request_ordinal','release_clock_s','elevation_at_release_deg','max_sampled_elevation_deg','min_off_nadir_while_visible_deg','first_visible_offset_s','first_view_start_offset_s','longest_view_with_angle_throughout_s','longest_sampled_station_visibility_s','joint_geometry_candidate','first_contiguous_rf_start_offset_s']
table=[]
for i,r in enumerate(G):
 table.append([i,T[i],round(r[0],6),round(r[1],6),round(r[2],6) if np.isfinite(r[2]) else '',int(r[3]) if r[3]>=0 else '',int(r[4]) if r[4]>=0 else '',int(r[5]),int(r[6]),int(r[7]),int(r[8]) if r[8]>=0 else ''])
print('Counts (visible at release, ever visible, optical candidates, joint candidates):',*(int(x.sum()) for x in [G[:,0]>0,G[:,3]>=0,G[:,4]>=0,G[:,7]>0]))
for k,fp in [('D1',a.d1),('D2',a.d2)]:
 if not fp:continue
 with zipfile.ZipFile(fp) as zz:
  with zz.open('requests.csv') as q0:
   req={int(r['ordinal']):r for r in csv.DictReader(io.TextIOWrapper(q0,encoding='utf-8-sig'))}
  cm=defaultdict(list)
  with zz.open('commands.csv.gz') as c0,gzip.GzipFile(fileobj=c0) as raw:
   for row in csv.DictReader(io.TextIOWrapper(raw)):
    if row['request_id']:cm[int(row['request_id'].rsplit('-',1)[1])].append(row)
  cr={int(r['request_id'].rsplit('-',1)[1]) for r in json.loads(zz.read('credits.json'))}
 assert set(req)==set(range(len(T))) and all(T[i]==int(r['release_seconds']) for i,r in req.items())
 ts=[];st=[];tc=[];ang=[];counts=Counter()
 cols.append(k+'_observed_outcome')
 for i in range(len(T)):
  rows=cm.get(i,[]);outcome='CREDITED' if i in cr else (rows[-1]['reason_original'] if rows else 'NO_LINKED_ACTION')
  if G[i,7]:counts[outcome]+=1
  table[i].append(outcome);point=next((r for r in rows if r['kind']=='POINT'),None)
  if point:ts.append(int(point['start_seconds']));st.append(point['status']!='refused')
  for row in rows:
   if row['reason_original']=='ACQUISITION_VIEW_ENVELOPE_REFUSED':
    tc.append(int(row['start_seconds']));ang.append(dict(json.loads(row['refusal_detail_json'])['quantities'])['requested_view_angle_deg'])
 a0=angles(np.array(ts),1000)[0];e0=np.abs(angles(np.array(tc),1000)[1]-ang)
 print(k,'first POINT comparisons / mismatches',len(ts),sum((a0>0)!=st),'angles compared / max error deg',len(tc),float(np.max(e0)),'outcomes of joint candidates',dict(counts))
if a.out:
 with open(a.out,'w',encoding='utf-8',newline='') as f: w=csv.writer(f);w.writerow(cols);w.writerows(table)
