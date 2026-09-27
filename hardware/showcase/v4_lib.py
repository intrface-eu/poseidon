"""Shared helpers for the v4 showcase builds (head and hero).

Blender authors in Z-up metres. The glTF exporter writes +Y up, so a Blender
point (x, y, z) lands in glTF at (x, z, -y). The water surface is z = 0.

Run inside Blender 5.x. Nothing here downloads anything; every mesh is either
read from the repo's CadQuery exports or built procedurally below.
"""

import bpy
import bmesh
import math
import os
import random
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SURFACE_GLB = os.path.join(REPO, "hardware/candidates/surface-v3/cad/generated/surface-v3/SURFACE_V3.glb")
PASSIVE_GLB = os.path.join(REPO, "hardware/candidates/passive-v3/cad/generated/passive-v3/INTRFACE_PASSIVE_V3.glb")
TEX_DIR = os.path.join(HERE, "textures")
BUILD_DIR = os.path.join(HERE, "build")


# ---------------------------------------------------------------- scene basics

def clear_scene():
    bpy.ops.wm.read_homefile(use_empty=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions):
        for item in list(block):
            if item.users == 0:
                block.remove(item)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    sc.render.fps = 30
    return sc


def link(obj, parent=None, coll=None):
    (coll or bpy.context.scene.collection).objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def empty(name, parent=None, loc=(0, 0, 0), coll=None, **extras):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.1
    e.location = loc
    link(e, parent, coll)
    for k, v in extras.items():
        e[k] = v
    return e


def mesh_object(name, bm_or_mesh, mat=None, parent=None, coll=None, smooth=None):
    if isinstance(bm_or_mesh, bmesh.types.BMesh):
        me = bpy.data.meshes.new(name)
        bm_or_mesh.to_mesh(me)
        bm_or_mesh.free()
    else:
        me = bm_or_mesh
    if mat is not None and not me.materials:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    link(ob, parent, coll)
    if smooth is not None:
        set_smooth(ob, smooth)
    return ob


def set_smooth(ob, angle_deg=35.0):
    """Smooth shading with sharp edges above angle_deg, baked into the mesh."""
    me = ob.data
    if angle_deg is False:
        for p in me.polygons:
            p.use_smooth = False
        return
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(angle_deg))
    except AttributeError:
        pass


def parent_keep(child, parent):
    """Parent child to parent, baking child's world placement into its mesh so the
    node ends up with an identity local transform."""
    bpy.context.view_layer.update()
    mw = child.matrix_world.copy()
    pw = parent.matrix_world.copy()
    if child.type == "MESH":
        child.data.transform(pw.inverted() @ mw)
        child.data.update()
        child.parent = parent
        child.matrix_parent_inverse = Matrix.Identity(4)
        child.matrix_basis = Matrix.Identity(4)
    else:
        child.parent = parent
        child.matrix_world = mw


def action_fcurves(act):
    """All F-curves of an action (legacy or layered/slotted actions)."""
    if hasattr(act, "fcurves") and not hasattr(act, "layers"):
        return list(act.fcurves)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for cb in getattr(strip, "channelbags", []):
                out += list(cb.fcurves)
    if not out and hasattr(act, "fcurves"):
        out = list(act.fcurves)
    return out


def bake_world(ob):
    """Apply the object's world matrix to its mesh and clear parent/transform."""
    mw = ob.matrix_world.copy()
    ob.parent = None
    if ob.type == "MESH":
        ob.data.transform(mw)
        ob.data.update()
    ob.matrix_world = Matrix.Identity(4)


def set_origin(ob, point):
    """Move ob's origin to world point without moving its geometry (unparented ob)."""
    p = Vector(point)
    ob.data.transform(Matrix.Translation(-p))
    ob.location = ob.location + p


def import_cad(path):
    """Import a CadQuery GLB, bake every mesh to world space (Z-up metres),
    drop the importer's empties and return {node_name: object}."""
    before = set(bpy.data.objects)
    mats_before = set(bpy.data.materials)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    bpy.context.view_layer.update()
    meshes = {}
    for o in new:
        if o.type == "MESH":
            # unique mesh data per part
            if o.data.users > 1:
                o.data = o.data.copy()
            bake_world(o)
            o.data.materials.clear()
            meshes[o.name] = o
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.materials):
        if m not in mats_before and m.users == 0:
            bpy.data.materials.remove(m)
    return meshes


def bbox(obs):
    pts = []
    for o in obs if isinstance(obs, (list, tuple)) else [obs]:
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def join(obs, name):
    """Merge mesh objects into the first one (world space kept), without operators."""
    obs = [o for o in obs if o is not None]
    base = obs[0]
    if len(obs) == 1:
        base.name = name
        base.data.name = name
        return base
    inv = base.matrix_world.inverted()
    slots = [m for m in base.data.materials]
    bm = bmesh.new()
    bm.from_mesh(base.data)
    for o in obs[1:]:
        me = o.data.copy()
        me.transform(inv @ o.matrix_world)
        remap = []
        for m in me.materials:
            if m not in slots:
                slots.append(m)
            remap.append(slots.index(m) if m is not None else 0)
        if remap:
            for p in me.polygons:
                p.material_index = remap[p.material_index] if p.material_index < len(remap) else 0
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        old = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if old.users == 0:
            bpy.data.meshes.remove(old)
    base.data.materials.clear()
    for m in slots:
        base.data.materials.append(m)
    bm.to_mesh(base.data)
    bm.free()
    base.name = name
    base.data.name = name
    return base


def add_bevel(ob, width=0.002, segments=2, angle_deg=40):
    mod = ob.modifiers.new("bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(angle_deg)
    mod.harden_normals = True
    return mod


def apply_modifiers(ob):
    ctx = bpy.context
    dg = ctx.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    me.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)


# ---------------------------------------------------------------- materials

def _bsdf(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def material(name, color, metallic=0.0, roughness=0.5, alpha=1.0, transmission=0.0,
             ior=1.45, emission=None, coat=0.0, spec=0.5, double_sided=False):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = _bsdf(m)
    col = tuple(color) + ((1.0,) if len(color) == 3 else ())
    b.inputs["Base Color"].default_value = col
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = roughness
    b.inputs["IOR"].default_value = ior
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = spec
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.08
    if emission:
        b.inputs["Emission Color"].default_value = tuple(emission) + (1.0,)
        b.inputs["Emission Strength"].default_value = 1.0
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        try:
            m.surface_render_method = "BLENDED"
        except Exception:
            pass
    m.use_backface_culling = not double_sided
    m.diffuse_color = col
    return m


def material_textured(name, image, metallic=0.0, roughness=0.5, vertex_color=False,
                      normal_image=None, normal_strength=1.0, rough_image=None):
    m = material(name, (1, 1, 1), metallic, roughness)
    nt = m.node_tree
    b = _bsdf(m)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.location = (-500, 250)
    if vertex_color:
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = "Col"
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        nt.links.new(tex.outputs["Color"], mix.inputs[6])
        nt.links.new(vc.outputs["Color"], mix.inputs[7])
        nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    else:
        nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
    if normal_image is not None:
        nt_ = nt.nodes.new("ShaderNodeTexImage")
        nt_.image = normal_image
        normal_image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = normal_strength
        nt.links.new(nt_.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    return m


def material_vcol(name, metallic=0.0, roughness=0.6, layer="Col"):
    """Base colour taken from the mesh's colour attribute (exported as COLOR_0)."""
    m = material(name, (1, 1, 1), metallic, roughness)
    nt = m.node_tree
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = layer
    nt.links.new(vc.outputs["Color"], _bsdf(m).inputs["Base Color"])
    return m


# ---------------------------------------------------------------- textures

def save_image(name, w, h, rgba, alpha=False):
    """rgba: flat list/array of floats (w*h*4), row 0 at the bottom."""
    os.makedirs(TEX_DIR, exist_ok=True)
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, w, h, alpha=alpha)
    import numpy as _np
    img.pixels.foreach_set(_np.ascontiguousarray(rgba, dtype=_np.float32).reshape(-1))
    path = os.path.join(TEX_DIR, name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    img.filepath = bpy.path.relpath(path) if bpy.data.filepath else path
    return img


# ---------------------------------------------------------------- geometry

def catmull(points, n):
    """Sample a centripetal-ish Catmull-Rom through points at n arc-length-even samples."""
    P = [Vector(p) for p in points]
    P = [P[0] + (P[0] - P[1])] + P + [P[-1] + (P[-1] - P[-2])]
    dense = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(24):
            t = k / 24
            t2, t3 = t * t, t * t * t
            dense.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                                + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    dense.append(P[-2])
    L = [0.0]
    for a, b in zip(dense, dense[1:]):
        L.append(L[-1] + (b - a).length)
    total = L[-1]
    out = []
    j = 0
    for i in range(n):
        s = total * i / (n - 1)
        while j < len(L) - 2 and L[j + 1] < s:
            j += 1
        seg = max(L[j + 1] - L[j], 1e-9)
        t = (s - L[j]) / seg
        out.append(dense[j].lerp(dense[j + 1], min(max(t, 0), 1)))
    return out


def tube_bm(path, radius, sides=8, bm=None, caps=True, radius_fn=None, twist=0.0):
    """Sweep a circle along path (list of Vectors) with parallel-transport frames."""
    bm = bm or bmesh.new()
    n = len(path)
    tangents = []
    for i in range(n):
        a = path[max(i - 1, 0)]
        b = path[min(i + 1, n - 1)]
        tangents.append((b - a).normalized())
    ref = Vector((0, 0, 1)) if abs(tangents[0].z) < 0.9 else Vector((1, 0, 0))
    nrm = tangents[0].cross(ref).normalized()
    rings = []
    for i in range(n):
        t = tangents[i]
        if i > 0:
            nrm = (nrm - t * nrm.dot(t)).normalized()
        bin_ = t.cross(nrm)
        r = radius_fn(i / (n - 1)) if radius_fn else radius
        ring = []
        for k in range(sides):
            a = 2 * math.pi * k / sides + twist * i
            ring.append(bm.verts.new(path[i] + (nrm * math.cos(a) + bin_ * math.sin(a)) * r))
        rings.append(ring)
    for i in range(n - 1):
        for k in range(sides):
            k2 = (k + 1) % sides
            bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
    if caps:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    return bm


def fix_normals(bm):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def rope_object(name, path, radius, mat, parent=None, sides=8, coll=None, n=None):
    pts = catmull(path, n or max(8, int(sum((Vector(b) - Vector(a)).length for a, b in zip(path, path[1:])) / 0.08)))
    bm = fix_normals(tube_bm(pts, radius, sides))
    ob = mesh_object(name, bm, mat, parent, coll)
    set_smooth(ob, 80)
    return ob


def uv_box_project(ob, scale=1.0):
    """Cheap per-face box projection into a UV layer named UVMap."""
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uv = me.uv_layers.active.data
    for p in me.polygons:
        n = p.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if ax == 0:
                uv[li].uv = (co.y * scale, co.z * scale)
            elif ax == 1:
                uv[li].uv = (co.x * scale, co.z * scale)
            else:
                uv[li].uv = (co.x * scale, co.y * scale)


def vcol_layer(me, name="Col"):
    attr = me.color_attributes.get(name) or me.color_attributes.new(name, "BYTE_COLOR", "CORNER")
    return attr


def rng(seed):
    return random.Random(seed)


# ---------------------------------------------------------------- saving

def _blank_ui_paths(path):
    """Blank the directory and file fields that file-browser areas keep in a saved .blend.

    The default workspaces carry file-browser state holding the author's home folder. It is
    UI state only, so it is zeroed in place after saving. The .blend layout is read from the
    file's own DNA block, so field offsets follow the Blender version that wrote it.
    """
    import re
    import struct
    data = bytearray(open(path, "rb").read())
    if data[:7] != b"BLENDER":
        return 0
    large = data[7:9] == b"17"          # 5.x header: 17 bytes, 32-byte block headers
    pos = 17 if large else 12
    blocks = []
    while pos < len(data):
        code = bytes(data[pos:pos + 4])
        if large:
            sdna, _old, ln, _nr = struct.unpack("<iQqq", data[pos + 4:pos + 32])
            hl = 32
        else:
            ln, _old, sdna, _nr = struct.unpack("<iQii", data[pos + 4:pos + 24])
            hl = 24
        blocks.append((pos + hl, code, sdna, ln))
        if code == b"ENDB":
            break
        pos += hl + ln
    dna = next(b for b in blocks if b[1] == b"DNA1")
    d = bytes(data[dna[0]:dna[0] + dna[3]])
    i = 8
    n = struct.unpack("<i", d[i:i + 4])[0]
    i += 4
    names = []
    for _ in range(n):
        j = d.index(b"\0", i)
        names.append(d[i:j].decode())
        i = j + 1
    i = ((i + 3) & ~3) + 4
    n = struct.unpack("<i", d[i:i + 4])[0]
    i += 4
    types = []
    for _ in range(n):
        j = d.index(b"\0", i)
        types.append(d[i:j].decode())
        i = j + 1
    i = ((i + 3) & ~3) + 4
    tlen = struct.unpack("<%dh" % n, d[i:i + 2 * n])
    i = ((i + 2 * n + 3) & ~3) + 4
    ns = struct.unpack("<i", d[i:i + 4])[0]
    i += 4
    structs = []
    for _ in range(ns):
        t, nf = struct.unpack("<hh", d[i:i + 4])
        i += 4
        structs.append((t, [struct.unpack("<hh", d[i + 4 * k:i + 4 * k + 4]) for k in range(nf)]))
        i += 4 * nf

    def fields(idx):
        off, out = 0, {}
        for ft, fn in structs[idx][1]:
            nm = names[fn]
            count = 1
            for a in re.findall(r"\[(\d+)\]", nm):
                count *= int(a)
            size = 8 if nm.startswith("*") or nm.startswith("(*") else tlen[ft]
            base = re.sub(r"\[.*", "", nm).lstrip("*")
            out[base] = (off, size * count)
            off += size * count
        return out

    fsp = next(k for k, st in enumerate(structs) if types[st[0]] == "FileSelectParams")
    fsp_fields = fields(fsp)
    blanked = 0
    for start, code, sdna, ln in blocks:
        if code != b"DATA" or sdna >= len(structs):
            continue
        tname = types[structs[sdna][0]]
        if tname == "FileSelectParams":
            base = 0
        elif tname == "FileAssetSelectParams":
            base = fields(sdna)["base_params"][0]
        else:
            continue
        for key in ("title", "dir", "file"):
            o, sz = fsp_fields[key]
            if base + o + sz <= ln:
                data[start + base + o:start + base + o + sz] = bytes(sz)
                blanked += 1
    open(path, "wb").write(bytes(data))
    return blanked


def save_blend(path):
    """Save with relative paths, uncompressed, and without file-browser folder state."""
    for sc in bpy.data.scenes:
        sc.render.filepath = "//renders-v4/"
    bpy.ops.wm.save_as_mainfile(filepath=path, relative_remap=True, compress=False)
    _blank_ui_paths(path)
    backup = path + "1"
    if os.path.exists(backup):
        os.remove(backup)
