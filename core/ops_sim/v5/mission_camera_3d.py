"""Exact homogeneous Hamilton transform to B41's declared-vector proof branch."""
from .assembly_attitude_3d import BodyAttitude3D
from .mission_continuous_geometry import _Arithmetic
from .environment_forcing import _type

def exact_held_camera(attitude,body_axis,policy,*,charge):
    _type(attitude,BodyAttitude3D,'ideal held 3D pose');attitude.__post_init__()
    if type(body_axis) is not tuple or len(body_axis)!=3:raise ValueError('actual mounted camera required')
    a=_Arithmetic(policy,charge)
    w,x,y,z=(a.q(v) for v in attitude.quaternion)
    square=[a.mul(v,v) for v in (w,x,y,z)]
    n=a.add(a.add(square[0],square[1]),a.add(square[2],square[3]))
    if n<=0:raise ValueError('zero pose')
    ww,xx,yy,zz=square
    xy=a.mul(x,y);xz=a.mul(x,z);yz=a.mul(y,z)
    wx=a.mul(w,x);wy=a.mul(w,y);wz=a.mul(w,z)
    rows=((a.sub(a.add(ww,xx),a.add(yy,zz)),a.mul(2,a.sub(xy,wz)),a.mul(2,a.add(xz,wy))),
          (a.mul(2,a.add(xy,wz)),a.sub(a.add(ww,yy),a.add(xx,zz)),a.mul(2,a.sub(yz,wx))),
          (a.mul(2,a.sub(xz,wy)),a.mul(2,a.add(yz,wx)),a.sub(a.add(ww,zz),a.add(xx,yy))))
    body=tuple(a.q(v) for v in body_axis)
    result=tuple(a.div(a.add(a.add(a.mul(row[0],body[0]),a.mul(row[1],body[1])),a.mul(row[2],body[2])),n) for row in rows)
    # Exact algebra preserves norm of the declared binary body vector.
    return result
