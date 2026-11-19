from sqlalchemy import select
from fastapi import HTTPException
from .models import Stratum,Interpretation,SampleInterval,MissingInterval
from .common import hole,get,pack,audit,interval,overlaps

def effective(s,h):
    return s.scalar(select(Interpretation).where(Interpretation.borehole_id==h.id,Interpretation.state=='confirmed').order_by(Interpretation.id.desc()))
def resolve(s,h,stratum_id,start,end):
    """按实际生效的层段校验。待批修订不阻塞取样；批准后旧层段 id 映射到等价现行层；
    旧纸本留档层只用于既有来源，不能作为新切样依据。"""
    st=get(s,Stratum,stratum_id);i=get(s,Interpretation,st.interpretation_id)
    if i.borehole_id!=h.id:raise HTTPException(409,'层段不属于本孔，不能作为切样依据')
    if i.state=='confirmed' and start>=st.start_m-1e-8 and end<=st.end_m+1e-8:return st
    if i.state=='historical':raise HTTPException(409,'旧纸本留档层只保留既有取样来源，新切样须引用现行已确认层段')
    cur=effective(s,h)
    if not cur:raise HTTPException(409,'取样须位于本孔同一已确认层段内')
    rows=s.scalars(select(Stratum).where(Stratum.interpretation_id==cur.id)).all()
    hit=[z for z in rows if start>=z.start_m-1e-8 and end<=z.end_m+1e-8]
    if not hit:raise HTTPException(409,'所选层段已被新批界面替代，且区间跨过现行接触面；请按实际生效层段重选区段')
    return hit[0]
def validate(s,h,p,exclude=None):
    interval(p.start_m,p.end_m,h.total_depth);resolve(s,h,p.stratum_id,p.start_m,p.end_m)
    for m in s.scalars(select(MissingInterval).where(MissingInterval.borehole_id==h.id)):
        if overlaps(p.start_m,p.end_m,m.start_m,m.end_m):raise HTTPException(409,'缺芯区间不可取样')
    active=[x for x in s.scalars(select(SampleInterval).where(SampleInterval.borehole_id==h.id,SampleInterval.state!='cancelled'))if x.id!=exclude]
    if p.destructive:
        if any(x.destructive and overlaps(x.start_m,x.end_m,p.start_m,p.end_m)for x in active):raise HTTPException(409,'破坏性切样区间与已有取样重叠')
        if sum(x.end_m-x.start_m for x in active if x.destructive)+p.end_m-p.start_m>h.cut_quota+1e-8:raise HTTPException(409,'切样累计长度超过本孔破坏性配额')
def create(s,p,u):
    h=hole(s,p.borehole_id);st_=resolve(s,h,p.stratum_id,p.start_m,p.end_m);validate(s,h,p)
    x=SampleInterval(**{**p.model_dump(),'stratum_id':st_.id});s.add(x);s.flush();audit(s,u,'申请切样 '+x.code);return pack(x)
def revise(s,id,p,u):
    ref=get(s,SampleInterval,id);h=hole(s,ref.borehole_id);x=get(s,SampleInterval,id,True)
    if x.state!='planned' or p.borehole_id!=h.id or p.code!=x.code:raise HTTPException(409,'仅未封签计划可修订，孔号和样号固定')
    st_=resolve(s,h,p.stratum_id,p.start_m,p.end_m);validate(s,h,p,id)
    for k,v in {**p.model_dump(),'stratum_id':st_.id}.items():setattr(x,k,v)
    audit(s,u,'修订切样区间 '+x.code);return pack(x)
def cancel(s,id,u):
    ref=get(s,SampleInterval,id);hole(s,ref.borehole_id);x=get(s,SampleInterval,id,True)
    if x.state!='planned':raise HTTPException(409,'只有未封签计划可撤销释放配额')
    x.state='cancelled';audit(s,u,'撤销取样 '+x.code);return pack(x)
