"""Build the v4 hero scene: hero.blend and build/hero.raw.glb.

Run: Blender -b --python hardware/showcase/build_hero_v4.py

The surface unit and listening head come only from the repo's CadQuery exports.
Everything else (farm, seabed, fish, boat, water) is modelled here from code.
Blender is Z-up metres; the water surface is z = 0; glTF export writes +Y up.
"""

import bpy
import bmesh
import math
import os
import sys
import numpy as np
from mathutils import Vector, Matrix, Euler, Quaternion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import v4_lib as L
import build_head_v4 as H
importlib.reload(L)
importlib.reload(H)

FPS = 30
DESCEND_FRAMES = 60           # 2 s
SWIM_SECONDS = 20
SWIM_FRAMES = SWIM_SECONDS * FPS

SEABED_Z = -6.4               # CAD pole bottom / footing plate top
SURFACE_Z = 0.5               # tray underside, pole mode (CAD surface origin)
FLOAT_SURFACE_Z = 0.24220835166429532
BACKBONE_Z = -0.85            # at a buoy; sags between buoys
LINES_Y = (1.6, 6.6, -4.6)    # longline backbones run along X
LINE_X = (-12.5, 12.5)
BUOY_X = (-12, -8, -4, 0, 4, 8, 12)
SENSOR_X = 0.9                # sensor line hangs from the near backbone here
HEAD_WORK_Z = -2.6            # tube axis at working depth
HEAD_TOP_Z = -1.55            # start of the descend clip
DROPPER_LEN = 3.1

# head-frame points (see build_head_v4): line through the clamp, cable stub tops
HEAD_LINE = Vector((-0.045, -0.10, 0.0))
HEAD_TETHER_TOP = Vector((-0.2408, 0.0, 0.30))
HEAD_HYDRO_TOP = Vector((-0.120, 0.095, 0.30))
HEAD_ROT = Matrix.Rotation(math.pi, 4, "Z")   # dome looks toward world -X


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def backbone_z(x):
    """Sag between buoys (buoys hold the backbone up at BUOY_X)."""
    d = min(abs(x - b) for b in BUOY_X)
    return BACKBONE_Z - 0.16 * math.sin(math.pi * min(d, 2.0) / 4.0) ** 1.0


def head_origin(z):
    line = HEAD_ROT @ HEAD_LINE
    return Vector((SENSOR_X - line.x, LINES_Y[0] - line.y, z))


def head_point(local, z):
    return head_origin(z) + HEAD_ROT @ local


# ================================================================ textures

def texture_solar():
    W, H_ = 1024, 640
    img = np.zeros((H_, W, 3), np.float32)
    img[:] = (0.80, 0.81, 0.82)                     # backsheet between cells
    cols, rows, m, gap = 8, 5, 10, 6
    cw = (W - 2 * m - (cols - 1) * gap) / cols
    ch = (H_ - 2 * m - (rows - 1) * gap) / rows
    yy, xx = np.mgrid[0:H_, 0:W]
    r = np.random.default_rng(7)
    for i in range(cols):
        for j in range(rows):
            x0 = m + i * (cw + gap)
            y0 = m + j * (ch + gap)
            lx = xx - x0
            ly = yy - y0
            inside = (lx >= 0) & (lx < cw) & (ly >= 0) & (ly < ch)
            cham = 9
            corner = (np.minimum(lx, cw - lx) + np.minimum(ly, ch - ly)) < cham
            cell = inside & ~corner
            tone = 0.9 + 0.2 * r.random()
            base = np.array((0.055, 0.075, 0.16)) * tone
            grad = 1.0 + 0.10 * (ly / ch - 0.5)
            img[cell] = base * grad[cell][:, None]
            fingers = cell & ((ly.astype(int) % 5) == 0)
            img[fingers] = (0.12, 0.14, 0.22)
            for b in range(4):
                bx = x0 + cw * (b + 0.5) / 4
                bus = cell & (np.abs(xx - bx) < 1.2)
                img[bus] = (0.70, 0.71, 0.73)
    rgba = np.concatenate([img, np.ones((H_, W, 1), np.float32)], axis=2)
    return L.save_image("solar_cells", W, H_, rgba[::-1].reshape(-1))


# orada profile (metres, snout at x = 0, standard length 0.26, total 0.32)
SL = 0.26
TL = 0.32
PROF_T = [0.0, 0.03, 0.08, 0.16, 0.28, 0.42, 0.56, 0.70, 0.82, 0.92, 1.0]
PROF_TOP = [0.004, 0.020, 0.038, 0.054, 0.063, 0.064, 0.057, 0.042, 0.026, 0.016, 0.012]
PROF_BOT = [-0.007, -0.017, -0.029, -0.041, -0.049, -0.050, -0.044, -0.031, -0.018, -0.012, -0.010]
PROF_W = [0.004, 0.014, 0.025, 0.034, 0.040, 0.040, 0.034, 0.025, 0.015, 0.009, 0.007]


def prof(t, arr):
    return float(np.interp(t, PROF_T, arr))


def texture_orada():
    W, H_ = 512, 256
    yy, xx = np.mgrid[0:H_, 0:W].astype(np.float32)
    x = (xx + 0.5) / W * TL
    z = (yy + 0.5) / H_ * 0.14 - 0.07
    t = np.clip(x / SL, 0, 1)
    top = np.interp(t, PROF_T, PROF_TOP)
    bot = np.interp(t, PROF_T, PROF_BOT)
    s = np.clip((z - bot) / np.maximum(top - bot, 1e-4), 0, 1)
    img = np.zeros((H_, W, 3), np.float32)
    belly = np.array((0.88, 0.89, 0.88))
    flank = np.array((0.74, 0.76, 0.78))
    back = np.array((0.36, 0.43, 0.49))
    a = np.clip((s - 0.15) / 0.35, 0, 1)[..., None]
    b = np.clip((s - 0.55) / 0.35, 0, 1)[..., None]
    img[:] = belly * (1 - a) + flank * a
    img = img * (1 - b) + back * b
    # faint longitudinal lines
    for sl in (0.40, 0.50, 0.60, 0.70, 0.80):
        line = np.exp(-((s - sl) / 0.012) ** 2) * (x > 0.07) * (x < SL)
        img *= (1 - 0.13 * line)[..., None]
    # scale sheen noise
    rng_ = np.random.default_rng(3)
    img *= (1 + 0.04 * (rng_.random((H_, W)) - 0.5))[..., None]
    # gill cover edge and dark opercular spot
    gx = 0.066 + 0.010 * np.sin((s - 0.5) * 2.2)
    edge = np.exp(-((x - gx) / 0.0016) ** 2) * (s > 0.18) * (s < 0.9)
    img *= (1 - 0.35 * edge)[..., None]
    spot = np.exp(-(((x - 0.064) / 0.007) ** 2 + ((s - 0.74) / 0.07) ** 2))
    img = img * (1 - 0.85 * spot[..., None]) + np.array((0.10, 0.08, 0.10)) * 0.85 * spot[..., None]
    red = np.exp(-(((x - 0.066) / 0.004) ** 2 + ((s - 0.60) / 0.05) ** 2))
    img = img * (1 - 0.5 * red[..., None]) + np.array((0.60, 0.22, 0.22)) * 0.5 * red[..., None]
    # eye
    ex, es = 0.027, 0.66
    ez = np.interp(ex / SL, PROF_T, PROF_BOT) + es * (np.interp(ex / SL, PROF_T, PROF_TOP) - np.interp(ex / SL, PROF_T, PROF_BOT))
    d = np.sqrt((x - ex) ** 2 + (z - ez) ** 2)
    img[d < 0.0085] = (0.78, 0.66, 0.35)
    img[d < 0.0055] = (0.02, 0.02, 0.03)
    # gold bar between the eyes: over the forehead, just behind the eye
    gb = np.exp(-((x - 0.040) / 0.0060) ** 4) * np.clip((s - 0.70) / 0.06, 0, 1)
    img = img * (1 - 0.95 * gb[..., None]) + np.array((0.92, 0.70, 0.18)) * 0.95 * gb[..., None]
    # snout and lips a touch darker
    sn = np.exp(-(x / 0.010) ** 2)
    img *= (1 - 0.25 * sn)[..., None]
    # fins (outside the body outline) and tail
    outside = (z > top + 0.0008) | (z < bot - 0.0008)
    fin = np.array((0.44, 0.48, 0.54))
    img[outside] = fin
    tail = x > SL * 0.985
    img[tail] = (0.42, 0.45, 0.50)
    tail_edge = tail & (x > TL - 0.018 + 0.03 * (np.abs(z) / 0.07) ** 1.5 * 0.4)
    img[tail_edge] = (0.10, 0.11, 0.14)
    img = np.clip(img, 0, 1)
    rgba = np.concatenate([img, np.ones((H_, W, 1), np.float32)], axis=2)
    return L.save_image("orada_skin", W, H_, rgba.reshape(-1))


# ================================================================ materials

def hero_materials(solar_img, fish_img):
    M = H.head_materials()
    M.update({
        "tray": L.material("trayAluminium", (0.62, 0.64, 0.66), 0.9, 0.34),
        "skirt": L.material("skirtAluminium", (0.55, 0.57, 0.59), 0.85, 0.40),
        "frame": L.material("panelFrame", (0.78, 0.79, 0.81), 1.0, 0.24),
        "backsheet": L.material("panelBacksheet", (0.80, 0.80, 0.78), 0.0, 0.6),
        "wedge": L.material("wedgeBlack", (0.03, 0.03, 0.035), 0.2, 0.55),
        "hub": L.material("hubEnclosure", (0.74, 0.75, 0.74), 0.0, 0.42),
        "carrier": L.material("hubCarrier", (0.52, 0.54, 0.56), 0.9, 0.38),
        "socket": L.material("mastSocket", (0.60, 0.62, 0.64), 1.0, 0.30),
        "pole": L.material("galvanisedPole", (0.58, 0.59, 0.58), 0.9, 0.42),
        "footing": L.material("footingSteel", (0.11, 0.11, 0.105), 0.55, 0.78),
        "collar": L.material("floatFoam", (0.93, 0.66, 0.08), 0.0, 0.62),
        "backbone": L.material("backboneRope", (0.045, 0.05, 0.06), 0.0, 0.85),
        "rope": L.material("dropperRope", (0.52, 0.45, 0.32), 0.0, 0.9),
        "sensorLine": L.material("sensorLine", (0.70, 0.64, 0.50), 0.0, 0.8),
        "buoyOrange": L.material("buoyOrange", (0.90, 0.33, 0.05), 0.0, 0.42),
        "buoyGrey": L.material("buoyGrey", (0.16, 0.17, 0.19), 0.0, 0.45),
        "concrete": L.material("concreteBlock", (0.12, 0.13, 0.11), 0.0, 0.9),
        "mussel": L.material_vcol("musselShell", 0.0, 0.45),
        "seabed": L.material_vcol("seabedMud", 0.0, 0.95),
        "hullWhite": L.material("hullWhite", (0.86, 0.87, 0.85), 0.0, 0.35),
        "hullStripe": L.material("hullStripe", (0.04, 0.16, 0.42), 0.0, 0.35),
        "antifoul": L.material("hullAntifouling", (0.42, 0.06, 0.04), 0.0, 0.7),
        "hullInside": L.material("hullInside", (0.56, 0.62, 0.64), 0.0, 0.55),
        "wood": L.material("oiledWood", (0.36, 0.21, 0.10), 0.0, 0.6),
        "motor": L.material("outboardGrey", (0.045, 0.048, 0.052), 0.0, 0.35),
        "water": L.material("waterSurface", (0.10, 0.34, 0.40), 0.0, 0.05, alpha=0.38, double_sided=True),
    })
    M["glass"] = L.material_textured("solarGlass", solar_img, 0.0, 0.12)
    M["fish"] = L.material_textured("oradaSkin", fish_img, 0.35, 0.32)
    M["fin"] = L.material_textured("oradaFin", fish_img, 0.0, 0.5)
    M["fin"].use_backface_culling = False
    return M


# ================================================================ unit (CAD)

def solar_panel(ob, M):
    """Inset the CAD panel's top face into a frame and a textured glass face."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(1.0), verts=bm.verts, edges=bm.edges)
    bm.faces.ensure_lookup_table()
    top = max(bm.faces, key=lambda f: f.normal.z * f.calc_area())
    n0 = top.normal.copy()
    bmesh.ops.inset_individual(bm, faces=[top], thickness=0.016, depth=-0.002)
    uvl = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        f.material_index = 0
    glass = max(bm.faces, key=lambda f: f.normal.dot(n0) * f.calc_area())
    glass.material_index = 1
    bottom = min(bm.faces, key=lambda f: f.normal.z)
    bottom.material_index = 2
    # UV the glass face along its long edge
    edges = [(l.vert.co, l.link_loop_next.vert.co) for l in glass.loops]
    a, b = max(edges, key=lambda e: (e[1] - e[0]).length)
    u = (b - a).normalized()
    v = glass.normal.cross(u).normalized()
    pts = [l.vert.co for l in glass.loops]
    us = [p.dot(u) for p in pts]
    vs = [p.dot(v) for p in pts]
    for l in glass.loops:
        p = l.vert.co
        l[uvl].uv = ((p.dot(u) - min(us)) / (max(us) - min(us)), (p.dot(v) - min(vs)) / (max(vs) - min(vs)))
    me.materials.clear()
    for k in ("frame", "glass", "backsheet"):
        me.materials.append(M[k])
    bm.to_mesh(me)
    bm.free()
    L.set_smooth(ob, 30)


def build_unit(root, M):
    parts = L.import_cad(L.SURFACE_GLB)
    for n in ("SV3_SINK_OCCUPANCY_NOT_FINS", "SV3_SINK_OUTLET_AIR_ALLOCATION", "SV3_CROSS_BOLT_ALLOCATION_1",
              "SV3_CROSS_BOLT_ALLOCATION_2", "SV3_CABLE_ROUTE_ALLOCATION_A", "SV3_CABLE_ROUTE_ALLOCATION_B"):
        bpy.data.objects.remove(parts.pop(n), do_unlink=True)

    surface = L.empty("surface", root, (0, 0, SURFACE_Z))
    surface["label"] = "Surface unit"
    mount_pole = L.empty("mountPole", root)
    mount_pole["label"] = "Pole mount (default)"
    mount_float = L.empty("mountFloat", root)
    mount_float["label"] = "Float collar mount (variant)"
    mount_float["defaultHidden"] = True
    mount_float["floatSurfaceY"] = FLOAT_SURFACE_Z

    def take(names, node, label, mkey, parent, bevel=0.0, smooth=30):
        ob = L.join([parts.pop(n) for n in names], node)
        if bevel:
            L.add_bevel(ob, bevel, 2, 40)
            L.apply_modifiers(ob)
        if mkey:
            ob.data.materials.clear()
            ob.data.materials.append(M[mkey])
        L.set_smooth(ob, smooth)
        L.parent_keep(ob, parent)
        ob["label"] = label
        ob["cadParts"] = ", ".join(names)
        return ob

    tray = L.empty("tray", surface)
    tray["label"] = "Tray"
    take(["SV3_TRAY_PLATE"], "trayPlate", "Tray plate", "tray", tray, 0.0015)
    take(["SV3_OPEN_BOTTOM_SKIRT"], "traySkirt", "Open-bottom skirt", "skirt", tray, 0.004)
    hub = L.empty("hub", surface)
    hub["label"] = "Electronics hub"
    take(["SV3_HUB_HAMMOND_1550WJ"], "hubEnclosure", "Hub enclosure", "hub", hub, 0.006)
    take(["SV3_HUB_CARRIER"], "hubCarrier", "Hub carrier", "carrier", hub, 0.0015)
    take(["SV3_SHADE_ROOF", "SV3_SHADE_HANGER_1", "SV3_SHADE_HANGER_2"], "hubShade", "Hub sun shade", "carrier", hub, 0.0008)
    for side in ("A", "B"):
        g = L.empty("panel" + side, surface)
        g["label"] = f"Solar panel {side} with wedges"
        p = take([f"SV3_PANEL_{side}"], f"panel{side}Module", f"Solar panel {side}", None, g, 0.0)
        solar_panel(p, M)
        take([f"SV3_WEDGE_{side}_1", f"SV3_WEDGE_{side}_2"], f"panel{side}Wedges", f"Panel {side} tilt wedges", "wedge", g, 0.002)
    ms = L.empty("mastSocket", surface)
    ms["label"] = "Mast socket"
    take(["SV3_MAST_SOCKET"], "socketBody", "Mast socket", "socket", ms, 0.0)
    take(["SV3_POLE_60MM"], "pole", "60 mm pole", "pole", mount_pole, 0.0, 40)
    take(["SV3_SEABED_FOOTING_PLATE"], "footingPlate", "Seabed footing plate", "footing", mount_pole, 0.004)
    take(["SV3_FLOAT_COLLAR"], "floatCollar", "Foam float collar", "collar", mount_float, 0.035, 50)
    assert not parts, parts.keys()
    # empties have their world placement; move the group origins sensibly
    for g in (tray, hub, bpy.data.objects["panelA"], bpy.data.objects["panelB"], ms):
        g.location = (0, 0, 0)
    return surface, mount_pole, mount_float


# ================================================================ tether (two morph states)

def tether_points(head_z, variant, which):
    """Control points from the tray cable hole to a head cable stub, world space."""
    top_local = HEAD_TETHER_TOP if which == "tether" else HEAD_HYDRO_TOP
    stub = head_point(top_local, head_z)
    line = Vector((SENSOR_X, LINES_Y[0], 0))
    off = Vector((-0.016, -0.012, 0)) if which == "tether" else Vector((0.004, -0.024, 0))
    dz = 0.0 if variant == "pole" else FLOAT_SURFACE_Z - SURFACE_Z
    hole = Vector((0.23, 0.238, 0.34 + dz)) + (Vector((0, 0, 0)) if which == "tether" else Vector((0.0, 0.012, 0)))
    to_line = (line - Vector((0, 0, 0))).normalized()
    pts = [hole, hole + Vector((0, 0, -0.08))]
    if variant == "pole":
        side = to_line * 0.038 + (Vector((0.012, -0.006, 0)) if which == "hydro" else Vector())
        pts += [Vector((0.10, 0.12, 0.16)), side + Vector((0, 0, -0.10)), side + Vector((0, 0, -0.80)),
                side + to_line * 0.12 + Vector((0, 0, -0.98))]
    else:
        pts += [hole + Vector((0.03, 0.06, -0.40)), Vector((0.36, 0.62, -0.95))]
    mid = (pts[-1] + line + off) * 0.5
    pts += [Vector((mid.x, mid.y, -1.22)), line + off + Vector((0, 0, -1.06))]
    run_bottom = stub.z + 0.14
    pts += [line + off + Vector((0, 0, run_bottom)), stub + Vector((0, 0, 0.035)), stub]
    return pts


def tether_mesh(variant, name, M, parent):
    bm = bmesh.new()
    n = 150
    work = {}
    top = {}
    for which, r in (("tether", 0.0038), ("hydro", 0.0026)):
        work[which] = L.catmull(tether_points(HEAD_WORK_Z, variant, which), n)
        top[which] = L.catmull(tether_points(HEAD_TOP_Z, variant, which), n)
    for which, r in (("tether", 0.0038), ("hydro", 0.0026)):
        L.tube_bm(work[which], r, 8, bm)
    L.fix_normals(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    # material slots: tether yellow, hydrophone cable black (second tube)
    me.materials.append(M["tether"])
    me.materials.append(M["cable_black"])
    half = len(me.polygons) // 2
    for i, p in enumerate(me.polygons):
        p.material_index = 0 if i < half else 1
    ob = L.mesh_object(name, me, None, parent)
    L.set_smooth(ob, 80)
    # shape key: head raised (start of descend)
    ob.shape_key_add(name="Basis")
    sk = ob.shape_key_add(name="headRaised")
    bmt = bmesh.new()
    for which, r in (("tether", 0.0038), ("hydro", 0.0026)):
        L.tube_bm(top[which], r, 8, bmt)
    bmt.verts.ensure_lookup_table()
    assert len(bmt.verts) == len(sk.data)
    for i, v in enumerate(bmt.verts):
        sk.data[i].co = v.co
    bmt.free()
    ob["label"] = "Tether and hydrophone cable"
    return ob


# ================================================================ farm

def mussel_bm(bm, mat4, color, col_layer, L_=0.062, H_=0.030, W_=0.022, around=6, rings=(0.12, 0.35, 0.62, 0.86)):
    """One closed mussel: pointed umbo at -X, rounded posterior at +X."""
    verts_ring = []
    tip0 = bm.verts.new(mat4 @ Vector((-L_ / 2, 0, -H_ * 0.15)))
    for u in rings:
        hh = H_ / 2 * math.sin(math.pi * u ** 0.8) ** 0.7
        hw = W_ / 2 * math.sin(math.pi * u ** 0.9) ** 0.8
        cz = H_ * (0.10 * math.sin(math.pi * u) - 0.15 * (1 - u))
        ring = []
        for k in range(around):
            a = 2 * math.pi * k / around
            ring.append(bm.verts.new(mat4 @ Vector((-L_ / 2 + u * L_, hw * math.sin(a), cz + hh * math.cos(a)))))
        verts_ring.append(ring)
    tip1 = bm.verts.new(mat4 @ Vector((L_ / 2, 0, H_ * 0.02)))
    faces = []
    for k in range(around):
        k2 = (k + 1) % around
        faces.append(bm.faces.new((tip0, verts_ring[0][k2], verts_ring[0][k])))
        faces.append(bm.faces.new((tip1, verts_ring[-1][k], verts_ring[-1][k2])))
        for i in range(len(rings) - 1):
            faces.append(bm.faces.new((verts_ring[i][k], verts_ring[i][k2], verts_ring[i + 1][k2], verts_ring[i + 1][k])))
    for f in faces:
        f.smooth = True
        for l in f.loops:
            l[col_layer] = color
    return faces


def look_matrix(pos, fwd, up_hint, scale, roll=0.0):
    x = fwd.normalized()
    z = (up_hint - x * up_hint.dot(x))
    if z.length < 1e-4:
        z = Vector((0, 0, 1)) - x * x.z
    z.normalize()
    y = z.cross(x)
    R = Matrix((x, y, z)).transposed()
    R = R @ Matrix.Rotation(roll, 3, "X")
    return Matrix.Translation(pos) @ R.to_4x4() @ Matrix.Diagonal((scale, scale, scale, 1))


MUSSEL_COLS = [(0.020, 0.024, 0.040, 1), (0.028, 0.030, 0.055, 1), (0.015, 0.016, 0.022, 1),
               (0.060, 0.045, 0.030, 1), (0.045, 0.050, 0.080, 1), (0.035, 0.030, 0.045, 1)]


def dropper_mesh(name, seed, M, n_shells=560, sides=9, length=DROPPER_LEN, around=5):
    """A mussel dropper: a short bare rope tail, then a dense clump of shells round a thin core."""
    r = L.rng(seed)
    bm = bmesh.new()
    col = bm.loops.layers.color.new("Col")
    ph = [r.random() * 6.28 for _ in range(6)]
    sway = [Vector((0.035 * math.sin(ph[3] + t * 2.2) * t, 0.035 * math.cos(ph[4] + t * 1.7) * t, -t * length))
            for t in [i / 40 for i in range(41)]]
    path = L.catmull(sway, 70)

    def radius(t):
        if t < 0.05:
            return 0.009
        base = 0.012 + 0.030 * min((t - 0.05) / 0.08, 1.0)
        base *= 1.0 - 0.40 * max(0.0, (t - 0.82) / 0.18)
        return base * (1 + 0.22 * math.sin(t * 29 + ph[0]) + 0.12 * math.sin(t * 83 + ph[1]))

    L.tube_bm(path, 0.04, sides, bm, caps=True, radius_fn=radius)
    for f in bm.faces:
        f.smooth = True
        for l in f.loops:
            t = min(max(-l.vert.co.z / length, 0), 1)
            k = r.random()
            l[col] = (0.50, 0.43, 0.30, 1) if t < 0.05 else (0.020 + 0.02 * k, 0.018 + 0.015 * k, 0.020 + 0.01 * k, 1)
    cols = MUSSEL_COLS + [(0.085, 0.075, 0.10, 1), (0.10, 0.07, 0.04, 1)]
    for i in range(n_shells):
        t = 0.06 + 0.93 * (i + r.random()) / n_shells
        a = r.random() * 2 * math.pi
        c = path[min(int(t * 69), 69)]
        rad = radius(t)
        out = Vector((math.cos(a), math.sin(a), 0))
        tang = out.cross(Vector((0, 0, 1)))
        # shingled like a pine cone: mostly down and out, some sideways, a few upturned
        fwd = out * 0.75 + Vector((0, 0, -0.55)) + tang * r.gauss(0, 0.35) + Vector((0, 0, r.gauss(0, 0.35)))
        fwd.normalize()
        s = (0.90 + 0.40 * r.random()) * (0.75 + 0.25 * min(t * 4, 1)) * (1 - 0.25 * max(0, (t - 0.85) / 0.15))
        pos = c + out * rad * 0.75 + fwd * 0.022 * s
        m4 = look_matrix(pos, fwd, out, s, r.gauss(0, 0.5) + (math.pi / 2 if r.random() < 0.5 else 0))
        mussel_bm(bm, m4, cols[r.randrange(len(cols))], col, W_=0.025, H_=0.031, around=around, rings=(0.28, 0.70))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M["mussel"])
    return me


def buoy_mesh(M, name, mat):
    """Horizontal barrel float, 0.55 m diameter x 0.85 m long, axis along X, centre at origin."""
    R_, Lh, f = 0.275, 0.425, 0.09
    prof = []
    # (x, r) from one end to the other, filleted ends with a shallow dome and two ribs
    for i in range(7):
        a = math.pi / 2 * i / 6
        prof.append((-(Lh - f) - f * math.sin(a), (R_ - f) + f * math.cos(a)))
    prof = list(reversed(prof))
    prof.insert(0, (-Lh - 0.012, 0.0))
    body = []
    for x in (-0.33, -0.31, -0.29, -0.27, 0.27, 0.29, 0.31, 0.33):
        rr = R_ + (0.012 if abs(abs(x) - 0.30) < 0.02 else 0.0)
        body.append((x, rr))
    tail = [(-x, r) for (x, r) in reversed(prof)]
    prof = prof + body + tail
    bm = bmesh.new()
    seg = 28
    rings = []
    for x, rr in prof:
        ring = []
        for k in range(seg):
            a = 2 * math.pi * k / seg
            ring.append(bm.verts.new((x, rr * math.cos(a), rr * math.sin(a))))
        rings.append(ring)
    for i in range(len(rings) - 1):
        for k in range(seg):
            k2 = (k + 1) % seg
            bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # moulded eye lug underneath
    lug = bmesh.ops.create_cube(bm, size=1.0)
    for v in lug["verts"]:
        v.co = Vector((v.co.x * 0.10, v.co.y * 0.04, v.co.z * 0.06 - R_ - 0.02))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(50))
    except AttributeError:
        pass
    return me


def build_farm(root, M, lod_far=True):
    farm = L.empty("farm", root)
    farm["label"] = "Mussel longlines"
    drop_meshes = [dropper_mesh(f"dropperMesh{i}", 100 + i, M) for i in range(3)]
    drop_lod = [dropper_mesh(f"dropperMeshFar{i}", 200 + i, M, n_shells=200, sides=7, around=4) for i in range(2)]
    buoy_o = buoy_mesh(M, "buoyOrangeMesh", M["buoyOrange"])
    buoy_g = buoy_mesh(M, "buoyGreyMesh", M["buoyGrey"])
    r = L.rng(11)
    for li, ly in enumerate(LINES_Y):
        near = li == 0
        g = L.empty(["longlineNear", "longlineBack", "longlineFront"][li], farm)
        g["label"] = ["Longline beside the unit", "Longline behind", "Longline in front"][li]
        xs = [LINE_X[0] + i * 0.25 for i in range(int((LINE_X[1] - LINE_X[0]) / 0.25) + 1)]
        pts = [Vector((x, ly, backbone_z(x))) for x in xs]
        # ends run down to seabed anchors
        a0 = Vector((LINE_X[0] - 5.5, ly, SEABED_Z + 0.25))
        a1 = Vector((LINE_X[1] + 5.5, ly, SEABED_Z + 0.25))
        L.rope_object(f"backbone{li}", pts, 0.012, M["backbone"], g, sides=8)
        L.rope_object(f"anchorLineW{li}", [pts[0], pts[0].lerp(a0, 0.5) + Vector((0, 0, -0.25)), a0], 0.012, M["backbone"], g, sides=6)
        L.rope_object(f"anchorLineE{li}", [pts[-1], pts[-1].lerp(a1, 0.5) + Vector((0, 0, -0.25)), a1], 0.012, M["backbone"], g, sides=6)
        for ai, a in enumerate((a0, a1)):
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            for v in bm.verts:
                v.co = Vector((v.co.x * 0.7, v.co.y * 0.7, v.co.z * 0.45))
            blk = L.mesh_object(f"anchorBlock{li}{'WE'[ai]}", bm, M["concrete"], g)
            L.add_bevel(blk, 0.03, 2, 40)
            L.apply_modifiers(blk)
            blk.location = a - Vector((0, 0, 0.2))
        # buoys and their short lines
        for bi, bx in enumerate(BUOY_X):
            me = buoy_o if (bi + li) % 3 else buoy_g
            b = bpy.data.objects.new(f"buoy{li}{bi}", me)
            L.link(b, g)
            b.location = (bx, ly, -0.03 + 0.02 * r.random())
            b.rotation_euler = (0.04 * (r.random() - 0.5), 0.05 * (r.random() - 0.5), 0.12 * (r.random() - 0.5))
            L.rope_object(f"buoyLine{li}{bi}", [(bx, ly, -0.33), (bx + 0.02, ly, -0.6), (bx, ly, backbone_z(bx))], 0.008, M["rope"], g, sides=6, n=10)
        # droppers
        dx = 0.9 if near else 1.2
        x = LINE_X[0] + 0.6
        k = 0
        while x < LINE_X[1] - 0.5:
            if near and abs(x - SENSOR_X) < 0.55:
                x += dx
                continue
            me = drop_meshes[k % 3] if near else drop_lod[k % 2]
            d = bpy.data.objects.new(f"dropper{li}_{k:02d}", me)
            L.link(d, g)
            d.location = (x + 0.12 * (r.random() - 0.5), ly, backbone_z(x) - 0.01)
            d.rotation_euler = (0.02 * (r.random() - 0.5), 0.02 * (r.random() - 0.5), r.random() * 6.28)
            s = 0.9 + 0.2 * r.random()
            d.scale = (1, 1, s)
            k += 1
            x += dx
        if near:
            # sensor line: plain rope from the backbone to a small weight below the droppers
            sx = SENSOR_X
            top_z = backbone_z(sx)
            sl = L.rope_object("sensorLine", [(sx, ly, top_z), (sx, ly, -2.0), (sx, ly, -4.35)], 0.008, M["sensorLine"], g, sides=8, n=60)
            sl["label"] = "Sensor line the head clamps to"
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.07, radius2=0.05, depth=0.12)
            w = L.mesh_object("sensorWeight", bm, M["footing"], g)
            w["label"] = "Sensor line weight"
            w.location = (sx, ly, -4.42)
            L.set_smooth(w, 40)
    return farm


# ================================================================ seabed

def noise2(x, y, ph):
    return (math.sin(x * 0.31 + ph[0]) * math.cos(y * 0.27 + ph[1]) * 0.6
            + math.sin(x * 0.83 + y * 0.51 + ph[2]) * 0.25
            + math.sin(x * 2.1 - y * 1.7 + ph[3]) * 0.08)


def build_seabed(root, M):
    g = L.empty("seabed", root)
    g["label"] = "Seabed"
    ph = [0.3, 1.7, 2.9, 4.1]
    x0, x1, y0, y1 = -32.0, 32.0, -26.0, 26.0
    nx, ny = 96, 78
    bm = bmesh.new()
    col = bm.loops.layers.color.new("Col")
    verts = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            x = x0 + (x1 - x0) * i / nx
            y = y0 + (y1 - y0) * j / ny
            z = SEABED_Z + 0.16 * noise2(x, y, ph) - 0.03
            # flat, settled patch around the footing plate
            d = math.hypot(x, y)
            w = min(max((d - 0.45) / 0.9, 0), 1)
            z = SEABED_Z * (1 - w) + z * w - 0.004 * (1 - w)
            row.append(bm.verts.new((x, y, z)))
        verts.append(row)
    for j in range(ny):
        for i in range(nx):
            f = bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            f.smooth = True
            for l in f.loops:
                x, y, _ = l.vert.co
                near_line = min(abs(y - ly) for ly in LINES_Y)
                shell = math.exp(-(near_line / 1.3) ** 2) * (1 if LINE_X[0] - 1 < x < LINE_X[1] + 1 else 0.3)
                n = 0.5 + 0.5 * math.sin(x * 1.3 + y * 0.7) * math.cos(y * 1.1 - x * 0.4)
                base = (0.20 + 0.04 * n, 0.175 + 0.035 * n, 0.135 + 0.02 * n)
                dark = (0.07, 0.07, 0.075)
                c = tuple(base[k] * (1 - 0.3 * shell) + dark[k] * 0.3 * shell for k in range(3))
                l[col] = c + (1.0,)
    me = bpy.data.meshes.new("seabedGround")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M["seabed"])
    ground = L.mesh_object("seabedGround", me, None, g)
    ground["label"] = "Seabed mud"

    # shell litter: dead mussels drift below the lines, plus pale broken valves and a few stones
    r = L.rng(21)
    bm = bmesh.new()
    col = bm.loops.layers.color.new("Col")
    pale = [(0.55, 0.53, 0.56, 1), (0.62, 0.60, 0.58, 1), (0.45, 0.44, 0.50, 1)]
    count = 0
    for ly in LINES_Y:
        for i in range(260):
            x = r.uniform(LINE_X[0], LINE_X[1])
            y = ly + r.gauss(0, 0.8)
            z = SEABED_Z + 0.16 * noise2(x, y, ph) - 0.03
            if math.hypot(x, y) < 0.5:
                continue
            fwd = Vector((math.cos(r.random() * 6.28), math.sin(r.random() * 6.28), r.uniform(-0.15, 0.15)))
            s = r.uniform(0.8, 1.2)
            m4 = look_matrix(Vector((x, y, z + 0.008 * s)), fwd, Vector((r.uniform(-1, 1), r.uniform(-1, 1), 0.3)), s, 0)
            c = MUSSEL_COLS[r.randrange(len(MUSSEL_COLS))] if r.random() < 0.7 else pale[r.randrange(3)]
            mussel_bm(bm, m4, c, col, around=5, rings=(0.2, 0.55, 0.85))
            count += 1
    for i in range(40):
        x, y = r.uniform(-18, 18), r.uniform(-8, 10)
        z = SEABED_Z + 0.16 * noise2(x, y, ph) - 0.03
        res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r.uniform(0.05, 0.14))
        sq = r.uniform(0.4, 0.7)
        k = r.random()
        for v in res["verts"]:
            v.co = Vector((v.co.x * r.uniform(0.8, 1.3), v.co.y, v.co.z * sq)) + Vector((x, y, z))
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.smooth = True
            for l in f.loops:
                l[col] = (0.16 + 0.05 * k, 0.15 + 0.04 * k, 0.13 + 0.03 * k, 1)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("seabedShells")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M["mussel"])
    sh = L.mesh_object("seabedShells", me, None, g)
    sh["label"] = "Shell litter and stones"
    return g


# ================================================================ orada

def orada_meshes(M):
    """Gilthead seabream, total length 0.32 m. Body and tail are separate so the tail can beat.
    Local frame: +X forward (snout at +X), +Z up, origin at mid-body."""
    HINGE_T = 0.80
    rings_t = [0.0, 0.012, 0.03, 0.06, 0.10, 0.15, 0.21, 0.28, 0.36, 0.45, 0.54, 0.63, 0.72, 0.80, 0.86, 0.92, 0.97, 1.0]
    around = 14
    ox = 0.15   # snout x in local frame

    def to_local(x_from_snout, y, z):
        return Vector((ox - x_from_snout, y, z))

    def uv_of(x_from_snout, z):
        return (x_from_snout / TL, (z + 0.07) / 0.14)

    def ring_verts(bm, t):
        x = t * SL
        top, bot, w = prof(t, PROF_TOP), prof(t, PROF_BOT), prof(t, PROF_W)
        cz, hh, hw = (top + bot) / 2, (top - bot) / 2, w / 2
        out = []
        for k in range(around):
            a = 2 * math.pi * k / around
            ca, sa = math.cos(a), math.sin(a)
            # flattened-diamond section: fuller at the belly, keeled at the back
            z = cz + hh * ca
            y = hw * (abs(sa) ** 0.85) * (1 if sa >= 0 else -1) * (1.0 - 0.25 * max(ca, 0) ** 3)
            out.append(bm.verts.new(to_local(x, y, z)))
        return out

    def build(ts, cap_front, cap_back):
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new("UVMap")
        rings = [ring_verts(bm, t) for t in ts]
        faces = []
        for i in range(len(rings) - 1):
            for k in range(around):
                k2 = (k + 1) % around
                faces.append(bm.faces.new((rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2])))
        if cap_front:
            faces.append(bm.faces.new(list(rings[0])))
        if cap_back:
            faces.append(bm.faces.new(list(reversed(rings[-1]))))
        for f in faces:
            f.smooth = True
            for l in f.loops:
                co = l.vert.co
                l[uvl].uv = uv_of(ox - co.x, co.z)
        return bm, uvl

    def fin(bm, uvl, outline, thickness=0.0015, mat_index=1):
        """Flat fin from an outline of (x_from_snout, y, z) points, as a thin two-sided slab."""
        top = [bm.verts.new(to_local(x, y + thickness / 2, z)) for x, y, z in outline]
        bot = [bm.verts.new(to_local(x, y - thickness / 2, z)) for x, y, z in outline]
        fs = [bm.faces.new(top), bm.faces.new(list(reversed(bot)))]
        for f in fs:
            f.material_index = mat_index
            for l in f.loops:
                co = l.vert.co
                l[uvl].uv = uv_of(ox - co.x, co.z)

    body_ts = [t for t in rings_t if t <= HINGE_T]
    bm, uvl = build(body_ts, True, True)
    # dorsal fin: spiny, tallest at the front
    xs = [0.085, 0.095, 0.12, 0.15, 0.18, 0.20, 0.212]
    outline = [(xs[0], 0, prof(xs[0] / SL, PROF_TOP) - 0.002)]
    for x in xs[1:]:
        h = 0.020 * (1 - (x - 0.085) / 0.14) ** 0.5 + 0.007 if x < 0.2 else 0.006
        outline.append((x, 0, prof(x / SL, PROF_TOP) + h))
    outline.append((0.214, 0, prof(0.214 / SL, PROF_TOP) - 0.002))
    outline.reverse()
    fin(bm, uvl, outline)
    # anal fin
    fin(bm, uvl, [(0.150, 0, prof(0.150 / SL, PROF_BOT) + 0.002), (0.160, 0, prof(0.16 / SL, PROF_BOT) - 0.020),
                  (0.200, 0, prof(0.2 / SL, PROF_BOT) - 0.010), (0.205, 0, prof(0.205 / SL, PROF_BOT) + 0.002)])
    # pelvic fins (pair) and pectoral fins (pair)
    for s in (1, -1):
        fin(bm, uvl, [(0.080, s * 0.010, prof(0.08 / SL, PROF_BOT) + 0.004), (0.112, s * 0.013, prof(0.08 / SL, PROF_BOT) - 0.010),
                      (0.106, s * 0.012, prof(0.08 / SL, PROF_BOT) + 0.001)])
        fin(bm, uvl, [(0.072, s * 0.0205, -0.006), (0.112, s * 0.027, -0.016), (0.114, s * 0.026, -0.010), (0.075, s * 0.0205, 0.000)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    body = bpy.data.meshes.new("oradaBody")
    bm.to_mesh(body)
    bm.free()
    body.materials.append(M["fish"])
    body.materials.append(M["fin"])

    tail_ts = [t for t in rings_t if t >= HINGE_T]
    bm, uvl = build(tail_ts, True, True)
    # forked caudal fin
    x0 = SL * 0.985
    fin(bm, uvl, [(x0 - 0.004, 0, 0.011), (TL - 0.004, 0, 0.056), (TL + 0.002, 0, 0.050), (x0 + 0.030, 0, 0.004),
                  (x0 + 0.030, 0, -0.004), (TL + 0.002, 0, -0.048), (TL - 0.004, 0, -0.054), (x0 - 0.004, 0, -0.010)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    tail = bpy.data.meshes.new("oradaTail")
    bm.to_mesh(tail)
    bm.free()
    tail.materials.append(M["fish"])
    tail.materials.append(M["fin"])
    hinge_local = ox - HINGE_T * SL
    # tail mesh relative to its hinge so it can rotate about Z there
    tail.transform(Matrix.Translation((-hinge_local, 0, 0)))
    return body, tail, hinge_local


def build_school(root, M):
    body, tail, hinge = orada_meshes(M)
    school = L.empty("school", root, (-0.5, 0.3, -2.45))
    school["label"] = "Gilthead seabream (orada), adults about 32 cm"
    r = L.rng(5)
    fish = []
    for i in range(9):
        radius = 1.25 + 0.55 * r.random()
        ang = i / 9 * 2 * math.pi + r.uniform(-0.2, 0.2)
        z = r.uniform(-0.45, 0.45)
        f = L.empty(f"orada{i + 1:02d}", school, (radius * math.cos(ang), radius * math.sin(ang), z))
        f["label"] = "Gilthead seabream"
        f.rotation_euler = (r.uniform(-0.06, 0.06), r.uniform(-0.08, 0.08), ang + math.pi / 2 + r.uniform(-0.12, 0.12))
        s = r.uniform(0.94, 1.09)
        f.scale = (s, s, s)
        b = bpy.data.objects.new(f"orada{i + 1:02d}Body", body)
        L.link(b, f)
        t = bpy.data.objects.new(f"orada{i + 1:02d}Tail", tail)
        L.link(t, f)
        t.location = (hinge, 0, 0)
        fish.append((f, t, r.random() * 2 * math.pi))
    return school, fish


# ================================================================ work boat (scale reference)

def build_boat(root, M):
    """Small open work boat, 5.2 m x 1.9 m, the kind used to tend Istrian mussel lines."""
    g = L.empty("workBoat", root, (7.5, -1.1, 0.0))
    g.rotation_euler = (0, 0.0, math.radians(-14))
    g["label"] = "5.2 m open work boat, for scale"
    n = 28
    stations = []
    for i in range(n + 1):
        u = i / n                       # 0 stern .. 1 bow
        x = -2.6 + 5.2 * u
        if u < 0.42:
            half = 0.95 - 0.28 * ((0.42 - u) / 0.42) ** 2
        else:
            half = 0.95 * max(1 - ((u - 0.42) / 0.58) ** 2, 0) ** 0.6
        sheer = 0.50 + 0.30 * max(u - 0.5, 0) ** 1.8 / 0.5 ** 1.8 + 0.05 * max(1 - u / 0.3, 0)
        keel = -0.22 + 1.02 * max(u - 0.7, 0) ** 2 / 0.09 + 0.04 * max(1 - u / 0.2, 0)
        stations.append((x, half, sheer, keel))
    bm = bmesh.new()
    prof_n = 8
    rings = []
    for x, half, sheer, keel in stations:
        pts = []
        for k in range(prof_n):
            s_ = k / (prof_n - 1)          # 0 keel .. 1 gunwale
            yy = half * math.sin(s_ * math.pi / 2) ** 0.8
            zz = keel + (sheer - keel) * (s_ ** 1.4)
            pts.append((yy, zz))
        ring = [(x, -yy, zz) for yy, zz in reversed(pts[1:])] + [(x, 0.0, pts[0][1])] + [(x, yy, zz) for yy, zz in pts[1:]]
        rings.append([bm.verts.new(p) for p in ring])
    for i in range(n):
        for k in range(len(rings[i]) - 1):
            bm.faces.new((rings[i][k], rings[i + 1][k], rings[i + 1][k + 1], rings[i][k + 1]))
    bm.faces.new(list(reversed(rings[0])))   # transom
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges)
    # the transom is one n-gon; fill it with clean triangles so it shades flat
    tf = [f for f in bm.faces if len(f.verts) > 4]
    bmesh.ops.triangulate(bm, faces=tf, quad_method="BEAUTY", ngon_method="BEAUTY")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("boatHull")
    bm.to_mesh(me)
    bm.free()
    for k in ("hullWhite", "hullInside", "hullStripe", "antifoul"):
        me.materials.append(M[k])
    hull = L.mesh_object("boatHull", me, None, g)
    sol = hull.modifiers.new("solid", "SOLIDIFY")
    sol.thickness = 0.035
    sol.offset = -1
    sol.material_offset = 1
    sol.material_offset_rim = 1
    L.apply_modifiers(hull)
    for p in hull.data.polygons:
        if p.material_index == 0 and abs(p.normal.x) < 0.9:
            c = p.center
            st = stations[min(int((c.x + 2.6) / 5.2 * n), n)]
            if c.z < 0.03:
                p.material_index = 3
            elif c.z > st[2] - 0.085:
                p.material_index = 2
    L.set_smooth(hull, 50)
    for p in hull.data.polygons:
        if abs(p.normal.x) > 0.9:     # transom, inside and out: flat
            p.use_smooth = False
    # rub rail along the sheer, thwarts, floorboards, outboard
    for side in (1, -1):
        pts = [Vector((x, (half + 0.012) * side, sheer - 0.01)) for x, half, sheer, keel in stations[:-1]] + \
              [Vector((stations[-1][0] + 0.01, 0, stations[-1][2] - 0.01))]
        L.rope_object(f"boatRubRail{'PS'[side < 0]}", pts, 0.022, M["wood"], g, sides=6)
    for i, (x, w) in enumerate(((-0.9, 0.84), (0.6, 0.80), (1.7, 0.48))):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((x + v.co.x * 0.26, v.co.y * 2 * w, 0.33 + v.co.z * 0.035))
        L.mesh_object(f"boatThwart{i}", bm, M["wood"], g)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * 2.65 - 0.175, v.co.y * 0.84, -0.08 + v.co.z * 0.02))
    L.mesh_object("boatFloor", bm, M["wood"], g)
    # outboard: cowl on a transom clamp, leg, cavitation plate, gear case and tiller
    bm = bmesh.new()
    def box(cx, cy, cz, sx, sy, sz):
        r_ = bmesh.ops.create_cube(bm, size=1.0)
        for v in r_["verts"]:
            v.co = Vector((cx + v.co.x * sx, cy + v.co.y * sy, cz + v.co.z * sz))
    box(-2.86, 0.0, 0.76, 0.46, 0.30, 0.32)    # cowl
    box(-2.70, 0.0, 0.57, 0.10, 0.20, 0.10)    # transom clamp
    box(-2.88, 0.0, 0.20, 0.13, 0.075, 0.80)   # leg
    box(-2.86, 0.0, -0.19, 0.30, 0.18, 0.02)   # cavitation plate
    box(-2.87, 0.0, -0.27, 0.24, 0.08, 0.10)   # gear case
    box(-2.52, 0.0, 0.80, 0.42, 0.045, 0.045)  # tiller
    mot = L.mesh_object("boatOutboard", bm, M["motor"], g)
    L.add_bevel(mot, 0.03, 4, 40)
    L.apply_modifiers(mot)
    L.set_smooth(mot, 40)
    return g


# ================================================================ water

def build_water(root, M):
    x0, x1, y0, y1 = -21.0, 21.0, -10.0, 12.0
    nx, ny = 84, 44
    bm = bmesh.new()
    vs = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            x = x0 + (x1 - x0) * i / nx
            y = y0 + (y1 - y0) * j / ny
            z = 0.025 * math.sin(x * 0.9 + y * 0.35) + 0.012 * math.sin(x * 2.3 - y * 1.9 + 1.3)
            row.append(bm.verts.new((x, y, z)))
        vs.append(row)
    for j in range(ny):
        for i in range(nx):
            f = bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
            f.smooth = True
    me = bpy.data.meshes.new("waterSurface")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M["water"])
    w = L.mesh_object("waterSurface", me, None, root)
    w["label"] = "Water surface (replaceable by the page's own water)"
    w["role"] = "water"
    return w


# ================================================================ animation

def nla_push(idb, clip, act):
    ad = idb.animation_data or idb.animation_data_create()
    tr = ad.nla_tracks.new()
    tr.name = clip
    st = tr.strips.new(clip, int(act.frame_range[0]), act)
    st.name = clip
    tr.mute = True
    ad.action = None


def ease(t):
    return t * t * (3 - 2 * t)


def add_descend(head, tethers):
    act = bpy.data.actions.new("descend_head")
    head.animation_data_create()
    head.animation_data.action = act
    a, b = head_origin(HEAD_TOP_Z), head_origin(HEAD_WORK_Z)
    for f in range(0, DESCEND_FRAMES + 1, 2):
        head.location = a.lerp(b, ease(f / DESCEND_FRAMES))
        head.keyframe_insert("location", frame=f)
    nla_push(head, "descend", act)
    head.location = b
    for t in tethers:
        key = t.data.shape_keys
        key.animation_data_create()
        act = bpy.data.actions.new(f"descend_{t.name}")
        key.animation_data.action = act
        kb = key.key_blocks["headRaised"]
        for f in range(0, DESCEND_FRAMES + 1, 2):
            kb.value = 1 - ease(f / DESCEND_FRAMES)
            kb.keyframe_insert("value", frame=f)
        nla_push(key, "descend", act)
        kb.value = 0.0


def add_swim(school, fish):
    act = bpy.data.actions.new("swim_school")
    school.animation_data_create()
    school.animation_data.action = act
    for f in range(0, SWIM_FRAMES + 1, 15):
        school.rotation_euler = (0, 0, 2 * math.pi * f / SWIM_FRAMES)
        school.keyframe_insert("rotation_euler", frame=f)
    for fc in L.action_fcurves(act):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    nla_push(school, "swim", act)
    school.rotation_euler = (0, 0, 0)
    beat = 24  # frames per tail cycle (0.8 s)
    for f_, tail, ph in fish:
        act = bpy.data.actions.new(f"swim_{tail.name}")
        tail.animation_data_create()
        tail.animation_data.action = act
        for f in range(0, SWIM_FRAMES + 1, 3):
            tail.rotation_euler = (0, 0, 0.30 * math.sin(2 * math.pi * f / beat + ph))
            tail.keyframe_insert("rotation_euler", frame=f)
        nla_push(tail, "swim", act)
        tail.rotation_euler = (0, 0, 0)


# ================================================================ main

def main():
    L.clear_scene()
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 0, SWIM_FRAMES
    solar = texture_solar()
    fish_img = texture_orada()
    M = hero_materials(solar, fish_img)

    root = L.empty("poseidonHero")
    root["label"] = "Poseidon Trident at a Limski kanal mussel farm"
    root["contract"] = "poseidon.showcase.hero.v4"
    root["units"] = "metres"
    root["upAxis"] = "+Y"
    root["origin"] = "Water surface at y = 0; depth is negative y; the pole axis is x = z = 0."
    root["seabedTopY"] = SEABED_Z
    root["trayTopY"] = round(SURFACE_Z + 0.004, 4)
    root["floatSurfaceY"] = FLOAT_SURFACE_Z
    root["variantRule"] = ("Pole (default): mountPole visible, mountFloat hidden, surface y = 0.5. "
                           "Float: hide mountPole, show mountFloat, set surface y = floatSurfaceY. Nothing else moves.")
    root["status"] = "Design render of a non-adopted candidate. Nothing shown has been built or tested."

    surface, mpole, mfloat = build_unit(root, M)
    tp = tether_mesh("pole", "tetherPole", M, mpole)
    tf = tether_mesh("float", "tetherFloat", M, mfloat)
    # float mooring: rope from a collar corner to a block on the seabed
    blk = Vector((-2.2, -2.4, SEABED_Z + 0.2))
    L.rope_object("floatMooring", [(-0.50, -0.60, -0.02), (-0.9, -1.0, -1.5), (-1.7, -1.9, -4.8), blk], 0.009, M["rope"], mfloat, sides=6)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * 0.55, v.co.y * 0.55, v.co.z * 0.35))
    mb = L.mesh_object("mooringBlock", bm, M["concrete"], mfloat)
    L.add_bevel(mb, 0.025, 2, 40)
    L.apply_modifiers(mb)
    mb.location = blk - Vector((0, 0, 0.18))

    head, hnodes = H.build_head(parent=root, mats=M, name="head")
    head.matrix_world = Matrix.Translation(head_origin(HEAD_WORK_Z)) @ HEAD_ROT
    head["label"] = "Listening head, clamped to its sensor line"
    head["descendTopY"] = HEAD_TOP_Z
    head["workingDepthY"] = HEAD_WORK_Z

    build_farm(root, M)
    build_seabed(root, M)
    school, fish = build_school(root, M)
    build_boat(root, M)
    build_water(root, M)

    add_descend(head, [tp, tf])
    add_swim(school, fish)
    for o in (mfloat,):
        o.hide_viewport = False
        o.hide_render = True
        for c in o.children_recursive:
            c.hide_render = True
    sc.frame_set(0)
    return root


if __name__ == "__main__":
    main()
    L.save_blend(os.path.join(L.HERE, "hero.blend"))
    H.export_glb(os.path.join(L.BUILD_DIR, "hero.raw.glb"), export_image_format="WEBP", export_image_quality=88)
