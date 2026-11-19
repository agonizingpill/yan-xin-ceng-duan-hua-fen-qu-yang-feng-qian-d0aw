"""纯函数：声速校正与层段界面校验，便于不依赖数据库做单元校验。

原始读数（Reading 行）永不被修改；校正只产生用于拟合的副本。
"""
def apply_corrections(rows,corrections):
    """rows: 原始读数 dict 列表（含 id/depth_m/velocity）；corrections: 修正段 dict 列表。
    返回校正副本，附 velocity_raw 与 correction_ids。原始 dict 不变。"""
    out=[]
    for r in rows:
        hit=[c for c in corrections if c['start_m']<=r['depth_m']<c['end_m']]
        v=r['velocity']+sum(c['delta_m_s'] for c in hit)
        if v<=0:raise ValueError('声速修正后出现非正值，请核对修正区间与修正量')
        out.append({**r,'velocity':round(v,3),'velocity_raw':r['velocity'],'correction_ids':[c['id']for c in hit]})
    return out
def crossing_samples(samples,strata):
    """返回 [{sample,hit}]。样段 start<contact<end 视为被界面切开；
    未完整落在单一新层段的样段也视为不合法。"""
    contacts=sorted(z.start_m for z in strata if z.start_m>1e-9)
    crossed=[]
    for v in samples:
        if getattr(v,'state','planned')=='cancelled':continue
        start=float(v.start_m);end=float(v.end_m)
        hit=[c for c in contacts if start<c<end]
        inside=[z for z in strata if start>=z.start_m-1e-8 and end<=z.end_m+1e-8]
        if hit or not inside:crossed.append({'sample':v,'hit':hit})
    return crossed
