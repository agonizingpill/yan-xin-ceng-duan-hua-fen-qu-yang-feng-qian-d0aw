import os,time,logging,hashlib,json
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from .database import Session
from .models import Interpretation,Reading,Borehole,VelocityCorrection
from .common import get,pack
from .drilling_service import corrected
from .layer_model import fit_layers
r=Redis.from_url(os.environ['REDIS_URL'],decode_responses=True)
logging.basicConfig(level=logging.INFO)
while True:
    Path('/artifacts/core-heartbeat').write_text(str(time.time()))
    item=r.blpop('core-interpret',timeout=2)
    if not item:continue
    id=int(item[1])
    try:
        with Session.begin()as s:
            preview=get(s,Interpretation,id);get(s,Borehole,preview.borehole_id,True);x=get(s,Interpretation,id,True)
            if x.state!='queued':continue
            raw=[pack(z)for z in s.scalars(select(Reading).where(Reading.borehole_id==x.borehole_id).order_by(Reading.depth_m))]
            corrections=[pack(c)for c in s.scalars(select(VelocityCorrection).where(VelocityCorrection.borehole_id==x.borehole_id).order_by(VelocityCorrection.start_m))]
            rows=corrected(raw,corrections)
            ev=fit_layers(rows)
            if corrections:
                try:
                    base=fit_layers(raw)
                    ev['raw_candidate']={'chosen_k':base['chosen_k'],'suggested_contacts_m':base['suggested_contacts_m'],'source_sha256':base['source_sha256'],'holdout_stability_ari':base['holdout_stability_ari']}
                except Exception as e:ev['raw_candidate']={'error':str(e)[:300]}
            ev['velocity_corrections']=[{'id':c['id'],'start_m':c['start_m'],'end_m':c['end_m'],'delta_m_s':c['delta_m_s'],'reason':c['reason']}for c in corrections]
            ev['raw_source_sha256']=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            ev['corrected_reading_ids']=sorted({r['id']for r in rows if r['correction_ids']})
            ev['raw_readings_archived']=True
            x.evidence=ev;x.state='ready';x.error='';logging.info('interpreted %s k=%s corrections=%s',id,ev['chosen_k'],len(corrections))
    except Exception as e:
        logging.exception('interpretation failed')
        with Session.begin()as s:
            x=get(s,Interpretation,id,True);x.state='failed';x.error=str(e)[:550]
