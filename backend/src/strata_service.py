from sqlalchemy import select,delete
from fastapi import HTTPException
from .models import Reading,Interpretation,Stratum,SampleInterval
from .common import hole,get,pack,audit

def effective(s,h):
    return s.scalar(select(Interpretation).where(Interpretation.borehole_id==h.id,Interpretation.state=='confirmed').order_by(Interpretation.id.desc()))
def pending(s,h):
    return s.scalar(select(Interpretation).where(Interpretation.borehole_id==h.id,Interpretation.state.in_(['queued','ready'])).order_by(Interpretation.id.desc()))
def queue(s,p,u):
    h=hole(s,p.borehole_id)
    if pending(s,h):raise HTTPException(409,'本孔已有排队或待批的层段解释，须先撤销或等待批准')
    n=len(s.scalars(select(Reading).where(Reading.borehole_id==h.id)).all())
    if n<12:raise HTTPException(409,'至少12个真实物性测点才可选层数')
    old=effective(s,h)
    x=Interpretation(borehole_id=h.id,state='queued');s.add(x);s.flush();audit(s,u,'申请GMM层段解释' if not old else '申请修订层段（替代 #'+str(old.id)+' 版），待批期间现行层段继续生效');return pack(x)
def layers(s,id,p,u):
    ref=get(s,Interpretation,id);h=hole(s,ref.borehole_id);x=get(s,Interpretation,id,True)
    if x.state!='ready':raise HTTPException(409,'须算法已就绪且未主管批准确认才能修订接触面')
    rows=sorted(p.layers,key=lambda z:z.start_m);edge=0
    for z in rows:
        if abs(z.start_m-edge)>1e-6 or z.end_m<=z.start_m:raise HTTPException(409,'人工层段须从0连续衔接，不得缺段或重叠')
        edge=z.end_m
    if abs(edge-h.total_depth)>1e-6:raise HTTPException(409,'人工层段必须完整覆盖孔深')
    s.execute(delete(Stratum).where(Stratum.interpretation_id==id))
    for z in rows:s.add(Stratum(interpretation_id=id,**z.model_dump()))
    s.flush();audit(s,u,'人工接触面已编录');return pack(x)
def crossing(s,h,rows):
    """新界面切开的已有有效样段；样段也必须完整落在单一新层内。"""
    from .calibration import crossing_samples
    samples=s.scalars(select(SampleInterval).where(SampleInterval.borehole_id==h.id,SampleInterval.state!='cancelled')).all()
    return crossing_samples(samples,rows)
def confirm(s,id,u):
    ref=get(s,Interpretation,id);h=hole(s,ref.borehole_id);x=get(s,Interpretation,id,True)
    old=s.scalar(select(Interpretation).where(Interpretation.borehole_id==x.borehole_id,Interpretation.state=='confirmed',Interpretation.id!=id))
    if x.state!='ready' or not s.scalar(select(Stratum.id).where(Stratum.interpretation_id==id)):raise HTTPException(409,'须算法就绪且人工完整编录层段，不能重复确认')
    rows=s.scalars(select(Stratum).where(Stratum.interpretation_id==id).order_by(Stratum.start_m)).all();edge=0
    for z in rows:
        if abs(z.start_m-edge)>1e-6:raise HTTPException(409,'人工层段须从0连续衔接，不得缺段或重叠')
        edge=z.end_m
    if abs(edge-h.total_depth)>1e-6:raise HTTPException(409,'人工层段必须完整覆盖孔深')
    crossed=crossing(s,h,rows)
    if crossed:
        detail='、'.join(o['sample'].code+(('（界面 '+', '.join(str(c)for c in o['hit'])+'m 落在样段内）')if o['hit']else'（不再完整落在单一层段）')for o in crossed)
        raise HTTPException(409,'新界面切开已有有效样段：'+detail+'。批准未生效，'+(('保留原已确认层段')if old else'未生成已确认层段'))
    if old:
        # Sealed/broken/transferred bags keep their own stratum_id as provenance: manual contacts
        # never rewrite historical source layers, and each seal snapshot also carries the stratum
        # in force when it was sealed. Only unsealed plans are re-attached to the new equivalent
        # layer, so revising them after approval validates against the version actually in force.
        for v in s.scalars(select(SampleInterval).where(SampleInterval.borehole_id==h.id,SampleInterval.state=='planned')):
            v.stratum_id=next(z.id for z in rows if v.start_m>=z.start_m-1e-8 and v.end_m<=z.end_m+1e-8)
        old.state='superseded';audit(s,u,'旧层段版本 #'+str(old.id)+' 被新批版本替代，已封签取样来源层与封签快照保留')
    x.state='confirmed';audit(s,u,'主管确认地层接触面' if not old else '主管批准修订层段，现行取样改按新界面校验');return pack(x)
def withdraw(s,id,u):
    ref=get(s,Interpretation,id);hole(s,ref.borehole_id);x=get(s,Interpretation,id,True)
    if x.state not in ['ready','failed','confirmed']:raise HTTPException(409,'仅已完成/失败解释可撤销重编')
    ids=s.scalars(select(Stratum.id).where(Stratum.interpretation_id==id)).all()
    if ids and s.scalar(select(SampleInterval.id).where(SampleInterval.stratum_id.in_(ids))):raise HTTPException(409,'已有取样引用层面，禁止撤销解释')
    x.state='withdrawn';audit(s,u,'撤销解释，允许重测重编');return pack(x)
