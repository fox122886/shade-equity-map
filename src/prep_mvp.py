"""
樹蔭公平提案單 MVP：前處理
輸入：行道樹、樹穴、人行道範圍、公園基本資料、里界
輸出：mvp_data.json（嵌入網頁用）
所有模擬值都以固定種子產生，每次執行結果相同。
"""
import json, hashlib, math, sys
import numpy as np, pandas as pd
from pyproj import Transformer
from shapely.geometry import shape, Point, mapping
from shapely.strtree import STRtree
from shapely.ops import unary_union
import shapely

import os
HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.join(HERE, '..', 'data')
OUT = os.path.join(HERE, 'mvp_data.json')

to3857 = Transformer.from_crs(3826, 3857, always_xy=True)
wgs_to3826 = Transformer.from_crs(4326, 3826, always_xy=True)

def h01(*parts):
    """依字串產生 0–1 的固定亂數（模擬資料用）"""
    s = '|'.join(str(p) for p in parts).encode('utf-8')
    return int(hashlib.md5(s).hexdigest()[:8], 16) / 0xFFFFFFFF

TOWN = {'63000010': '松山區', '63000020': '信義區', '63000030': '大安區', '63000040': '中山區', '63000050': '中正區',
        '63000060': '大同區', '63000070': '萬華區', '63000080': '文山區', '63000090': '南港區', '63000100': '內湖區',
        '63000110': '士林區', '63000120': '北投區'}

# ---------------- 人行道 ----------------
g = json.load(open(SP + '/TP_SIDEWORK.json', encoding='utf-8'))
segs = []
for f in g['features']:
    if not f['geometry']:
        continue
    p = f['properties']
    geom = shape(f['geometry'])
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty or geom.area < 1:
        continue
    segs.append(dict(geom=geom, id=p['ID'], road=p.get('NAME_Road') or '', side=p.get('SW_DIRECT') or '',
                     pstart=p.get('PSTART') or '', pend=p.get('PEND') or '',
                     width=float(p.get('SW_WTH_ItemValue') or 0), length=float(p.get('SW_LENG_ItemValue') or 0),
                     code=p.get('code') or '', dist=TOWN.get(str(p.get('Town_N')), '')))
N = len(segs)
G = [s['geom'] for s in segs]
seg_tree = STRtree(G)
area = np.array([x.area for x in G])
print('segments', N)

# ---------------- 行道樹：分類與樹冠推估 ----------------
t = pd.read_csv(SP + '/TaipeiTree.csv', dtype={'TreeID': str})
t['TreeType'] = t.TreeType.fillna('未填樹種')
tx, ty = t.TWD97X.values.astype(float), t.TWD97Y.values.astype(float)
pts = shapely.points(tx, ty)
near = seg_tree.query(pts, predicate='dwithin', distance=1.5)
on_sw = np.zeros(len(t), bool); on_sw[np.unique(near[0])] = True
rr = t.RegionRemark.fillna('')
island_kw = rr.str.contains(r'分隔島|中島|安全島|分隔帶|槽化').values
# 類別：0 人行道、1 分隔島、2 其他綠帶
tcls = np.where(on_sw, 0, np.where(island_kw, 1, 2)).astype(np.uint8)
# 樹冠半徑推估（公尺）：0.8 + 0.055 × 胸徑（cm），限制在 1–8 公尺
dbh = t.Diameter.fillna(0).values.astype(float)
crown_r = np.clip(0.8 + 0.055 * dbh, 1.0, 8.0)
print('trees on sidewalk', on_sw.sum(), 'island', (tcls == 1).sum(), 'other', (tcls == 2).sum())

circles = shapely.buffer(pts, crown_r, quad_segs=6)
circ_tree = STRtree(circles)

# 每段人行道：樹冠與人行道面的重疊面積（有效樹蔭）
pairs = circ_tree.query(G, predicate='intersects')
by_seg = {}
for si, ci in zip(pairs[0], pairs[1]):
    by_seg.setdefault(si, []).append(ci)
s_tree = np.zeros(N); n_sw_trees = np.zeros(N, int); n_island_near = np.zeros(N, int)
for si, cis in by_seg.items():
    u = unary_union([circles[c] for c in cis])
    s_tree[si] = min(1.0, G[si].intersection(u).area / area[si])
    n_sw_trees[si] = int(sum(1 for c in cis if tcls[c] == 0))
# 附近 10 公尺內的分隔島樹（用來展示「數樹」與「有效樹蔭」的落差）
isl_idx = np.where(tcls == 1)[0]
if len(isl_idx):
    q = STRtree(pts[isl_idx]).query(G, predicate='dwithin', distance=10)
    np.add.at(n_island_near, q[0], 1)

# 「數樹」的天真遮蔭率：把附近 10 公尺內所有樹（含分隔島）的樹冠面積加總除以人行道面積
allq = STRtree(pts).query(G, predicate='dwithin', distance=10)
naive = np.zeros(N)
np.add.at(naive, allq[0], math.pi * crown_r[allq[1]] ** 2)
naive = np.minimum(1.0, naive / area)

# ---------------- 樹穴：空樹穴 ----------------
h = pd.read_csv(SP + '/TaipeiTreeHole.csv').drop_duplicates()
h = (h.assign(_n=h.Region.isna().astype(int) + h.Remark.isna().astype(int))
       .sort_values(['TreeHoleID', '_n']).drop_duplicates(['TreeHoleID', 'TWD97X', 'TWD97Y']))
hp = shapely.points(h.TWD97X.values.astype(float), h.TWD97Y.values.astype(float))
tree_pts_tree = STRtree(pts)
has_tree = np.zeros(len(h), bool)
hq = tree_pts_tree.query(hp, predicate='dwithin', distance=2.0)
has_tree[np.unique(hq[0])] = True
empty_h = hp[~has_tree]
empty_holes = np.zeros(N, int)
if len(empty_h):
    eq = STRtree(empty_h).query(G, predicate='dwithin', distance=1.0)
    np.add.at(empty_holes, eq[0], 1)
print('holes', len(h), 'empty holes (no tree within 2 m)', (~has_tree).sum())

# ---------------- 路寬推估：同路名、對側人行道之間的距離 ----------------
opp = {'東側': '西側', '西側': '東側', '南側': '北側', '北側': '南側'}
by_road = {}
for i, s in enumerate(segs):
    by_road.setdefault((s['road'], s['side']), []).append(i)
road_w = np.full(N, np.nan)
for i, s in enumerate(segs):
    o = opp.get(s['side'])
    if not o or not s['road']:
        continue
    cand = by_road.get((s['road'], o), [])
    best = None
    for j in cand:
        d = G[i].distance(G[j])
        if d < 80 and (best is None or d < best[0]):
            best = (d, j)
    if best:
        road_w[i] = best[0] + s['width'] + segs[best[1]]['width']
print('road width estimated for', np.isfinite(road_w).sum(), 'segments; median', np.nanmedian(road_w))

# ---------------- 公園（真實）----------------
parks = json.load(open(SP + '/TaipeiPark.json', encoding='utf-8'))
park_rows = []
for p in parks:
    try:
        lo, la = float(p['pm_Longitude']), float(p['pm_Latitude'])
    except Exception:
        continue
    if abs(la) > 90:
        lo, la = la, lo
    x, y = wgs_to3826.transform(lo, la)
    try:
        ar = float(p.get('pm_LandPublicArea') or 0)
    except ValueError:
        ar = 0
    park_rows.append(dict(name=p['pm_name'], dist=p.get('pm_regions', ''), x=x, y=y, area=ar, type=p.get('pm_type', '')))
park_pts = shapely.points([r['x'] for r in park_rows], [r['y'] for r in park_rows])
park_area = np.array([r['area'] for r in park_rows])

cent = shapely.centroid(np.array(G))
cx, cy = shapely.get_x(cent), shapely.get_y(cent)

# ---------------- 熱暴露（推估，非實測）----------------
# 周邊 150 公尺的樹冠比例越低越熱；離 1 公頃以上公園越遠越熱（依「樹冠每多一成，地表約低 0.95°C」的方向性設計）
q150 = tree_pts_tree.query(cent, predicate='dwithin', distance=150)
can150 = np.zeros(N)
np.add.at(can150, q150[0], math.pi * crown_r[q150[1]] ** 2)
can150 = np.minimum(1.0, can150 / (math.pi * 150 ** 2))
big = park_area >= 10000
bp = park_pts[big]
d_park = np.array([shapely.distance(c, bp).min() for c in cent]) if len(bp) else np.full(N, 1000.0)
heat_raw = 0.7 * (1 - can150 / max(can150.max(), 1e-6)) + 0.3 * np.minimum(d_park, 800) / 800
def pct(a):
    return pd.Series(a).rank(pct=True).values
H = pct(heat_raw)
# 換算成「示意地表溫度」，只供畫面說明，非實測：以 150 公尺樹冠比例與 0.95°C/10% 的斜率推算
lst_demo = 36.0 - 9.5 * can150 + 1.5 * np.minimum(d_park, 800) / 800

# ---------------- 騎樓（模擬）----------------
# 舊市區、計畫道路、人行道較窄的路段比較可能有騎樓；同一條路同一側共用同一個抽樣
p_dist = {'大同區': .65, '萬華區': .6, '中正區': .5, '中山區': .5, '松山區': .45, '大安區': .4, '信義區': .3,
          '士林區': .35, '北投區': .3, '南港區': .25, '內湖區': .2, '文山區': .25}
arcade = np.zeros(N)
for i, s in enumerate(segs):
    if s['code'] not in ('計畫道路', '退縮地'):
        continue
    p = p_dist.get(s['dist'], .3) * (1.2 if s['width'] < 3 else 0.8)
    if h01('arc', s['road'], s['side'], s['dist']) < p:
        arcade[i] = 0.45 + 0.5 * h01('arcv', s['id'])   # 騎樓遮蓋率 45–95%

# ---------------- 地下管線衝突（模擬）----------------
pipe = np.array([1 if h01('pipe', s['road'], s['dist'], int(s['length'] // 50)) < 0.28 else 0 for s in segs], np.uint8)

# ---------------- 都更與危老基地（模擬）----------------
rng = np.random.default_rng(20261024)
cand = np.where(np.isin([s['code'] for s in segs], ['計畫道路']))[0]
pick = rng.choice(cand, 160, replace=False)
stages = ['申請中', '已核定', '施工中']
ur_sites = []
for k, i in enumerate(pick):
    b = G[i].exterior if G[i].geom_type == 'Polygon' else G[i].geoms[0].exterior
    pt = b.interpolate(rng.random(), normalized=True)
    ur_sites.append(dict(x=pt.x, y=pt.y, kind='危老' if rng.random() < 0.6 else '都更', stage=stages[int(rng.integers(0, 3))],
                         area=int(rng.integers(300, 4000))))
ur_pts = shapely.points([u['x'] for u in ur_sites], [u['y'] for u in ur_sites])
uq = STRtree(ur_pts).query(G, predicate='dwithin', distance=15)
ur_near = np.full(N, -1)
for si, ui in zip(uq[0], uq[1]):
    if ur_near[si] < 0:
        ur_near[si] = ui

# ---------------- 匯出 ----------------
def merc(xs, ys):
    X, Y = to3857.transform(xs, ys)
    return np.asarray(X), np.asarray(Y)

allx, ally = [], []
ring_off, seg_ring = [0], [0]
for geom in G:
    gg = geom.simplify(0.4, preserve_topology=True)
    polys = [gg] if gg.geom_type == 'Polygon' else list(getattr(gg, 'geoms', []))
    for pg in polys:
        if pg.geom_type != 'Polygon' or pg.is_empty:
            continue
        c = np.asarray(pg.exterior.coords)
        X, Y = merc(c[:, 0], c[:, 1])
        allx.append(X); ally.append(Y)
        ring_off.append(ring_off[-1] + len(X))
    seg_ring.append(len(ring_off) - 1)
allx = np.concatenate(allx); ally = np.concatenate(ally)
MX0, MY0 = float(np.floor(allx.min())) - 1000, float(np.floor(ally.min())) - 1000

import base64
b64 = lambda a: base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()

tmx, tmy = merc(tx, ty)
cmx, cmy = merc(cx, cy)
pmx, pmy = merc(np.array([r['x'] for r in park_rows]), np.array([r['y'] for r in park_rows]))
umx, umy = merc(np.array([u['x'] for u in ur_sites]), np.array([u['y'] for u in ur_sites]))

f2 = lambda a, k=3: [round(float(v), k) for v in a]
data = dict(
    meta=dict(mx0=MX0, my0=MY0, built='2026-10-23', n_seg=N, n_tree=len(t),
              n_tree_sw=int(on_sw.sum()), n_tree_island=int((tcls == 1).sum()), n_tree_other=int((tcls == 2).sum()),
              n_hole=len(h), n_hole_empty=int((~has_tree).sum())),
    seg=dict(
        vx=b64(np.round((allx - MX0) * 10).astype('<i4')), vy=b64(np.round((ally - MY0) * 10).astype('<i4')),
        ring=b64(np.array(ring_off, '<u4')), segring=b64(np.array(seg_ring, '<u4')),
        cx=f2(cmx - MX0, 1), cy=f2(cmy - MY0, 1),
        id=[s['id'] for s in segs], road=[s['road'] for s in segs], side=[s['side'] for s in segs],
        ps=[s['pstart'] for s in segs], pe=[s['pend'] for s in segs], code=[s['code'] for s in segs],
        dist=[s['dist'] for s in segs], width=f2([s['width'] for s in segs], 2), len=f2([s['length'] for s in segs], 1),
        area=f2(area, 1), roadw=[None if not np.isfinite(v) else round(float(v), 1) for v in road_w],
        st=f2(s_tree), naive=f2(naive), nsw=n_sw_trees.tolist(), nisl=n_island_near.tolist(), eh=empty_holes.tolist(),
        H=f2(H), lst=f2(lst_demo, 1), can150=f2(can150),
        arc=f2(arcade, 2), pipe=pipe.tolist(), ur=ur_near.tolist()),
    tree=dict(x=b64(np.round((tmx - MX0) * 10).astype('<i4')), y=b64(np.round((tmy - MY0) * 10).astype('<i4')),
              cls=b64(tcls), r=b64(np.round(crown_r * 10).astype('u1'))),
    park=dict(x=f2(pmx - MX0, 1), y=f2(pmy - MY0, 1), name=[r['name'] for r in park_rows], dist=[r['dist'] for r in park_rows],
              area=[r['area'] for r in park_rows]),
    ur=dict(x=f2(umx - MX0, 1), y=f2(umy - MY0, 1), kind=[u['kind'] for u in ur_sites], stage=[u['stage'] for u in ur_sites],
            area=[u['area'] for u in ur_sites]),
)
s = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
open(OUT, 'w', encoding='utf-8').write(s)
print('wrote', OUT, round(len(s.encode()) / 1e6, 2), 'MB')
print('mean effective shade', round(float(np.average(s_tree, weights=area)), 3),
      'mean naive', round(float(np.average(naive, weights=area)), 3),
      'arcade segs', int((arcade > 0).sum()), 'pipe', int(pipe.sum()), 'ur-adjacent', int((ur_near >= 0).sum()),
      'empty-hole segs', int((empty_holes > 0).sum()))
