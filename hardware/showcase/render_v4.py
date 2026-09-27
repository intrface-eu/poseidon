"""Press renders for the v4 showcase.

Hero shots (open hero.blend):
  Blender -b hardware/showcase/hero.blend --python hardware/showcase/render_v4.py -- --shot hero|og|farm|unit
Head shot (open head.blend):
  Blender -b hardware/showcase/head.blend --python hardware/showcase/render_v4.py -- --shot head

Options: --samples N, --scale PCT (preview size), --out DIR, --hdri PATH.
Lighting uses the Poly Haven HDRI "kloofendal_48d_partly_cloudy_puresky" (CC0) when --hdri
or POSEIDON_HDRI points at it; otherwise a procedural sky. The stage (water volume, section
face, sediment block, studio set) is built here at render time and never saved into the
master .blend files or the GLBs.
"""

import bpy
import bmesh
import math
import os
import sys
from mathutils import Vector, Matrix, Euler

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "renders-v4")


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    o = {"shot": "hero", "samples": 256, "scale": 100, "out": OUT, "hdri": os.environ.get("POSEIDON_HDRI", "")}
    i = 0
    while i < len(a):
        k = a[i].lstrip("-")
        o[k] = type(o.get(k, ""))(a[i + 1]) if k in o and not isinstance(o[k], str) else a[i + 1]
        i += 2
    return o


# ------------------------------------------------------------------ engine

def setup_cycles(samples, w, h, scale):
    sc = bpy.context.scene
    try:
        sc.render.engine = "CYCLES"
    except TypeError:
        pass
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = dev
            prefs.refresh_devices()
            if any(d.type == dev for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == dev
                sc.cycles.device = "GPU"
                break
        except TypeError:
            continue
    c = sc.cycles
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.01
    c.use_denoising = True
    c.max_bounces = 10
    c.diffuse_bounces = 3
    c.glossy_bounces = 4
    c.transmission_bounces = 8
    c.volume_bounces = 1
    c.transparent_max_bounces = 16
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.blur_glossy = 1.0
    try:
        c.volume_step_rate = 4.0
        c.volume_preview_step_rate = 4.0
    except AttributeError:
        pass
    r = sc.render
    r.resolution_x, r.resolution_y = w, h
    r.resolution_percentage = scale
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.color_depth = "8"
    # no stamped metadata (it would carry the .blend path)
    for p in dir(r):
        if p.startswith("use_stamp") and isinstance(getattr(r, p), bool):
            try:
                setattr(r, p, False)
            except Exception:
                pass
    vs = sc.view_settings
    try:
        vs.view_transform = "AgX"
        vs.look = "AgX - Medium High Contrast"
    except TypeError:
        try:
            vs.look = "Medium High Contrast"
        except TypeError:
            pass
    vs.exposure = 0.0


def world_sky(hdri, strength=1.0, rot_z=0.0):
    w = bpy.data.worlds.get("showcaseWorld") or bpy.data.worlds.new("showcaseWorld")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    if hdri and os.path.exists(hdri):
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri, check_existing=True)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Rotation"].default_value = (0, 0, rot_z)
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        try:
            sky.sun_elevation = math.radians(38)
            sky.sun_rotation = rot_z
        except AttributeError:
            pass
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.25 * strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return w


def world_flat(color, strength=1.0):
    w = bpy.data.worlds.get("studioWorld") or bpy.data.worlds.new("studioWorld")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = tuple(color) + (1,)
    bg.inputs["Strength"].default_value = strength
    return w


# ------------------------------------------------------------------ water stage

def water_volume_nodes(nt, out, clarity=1.0):
    absn = nt.nodes.new("ShaderNodeVolumeAbsorption")
    absn.inputs["Color"].default_value = (0.30, 0.74, 0.84, 1)
    absn.inputs["Density"].default_value = 0.26 / clarity
    sca = nt.nodes.new("ShaderNodeVolumeScatter")
    sca.inputs["Color"].default_value = (0.36, 0.70, 0.92, 1)
    sca.inputs["Density"].default_value = 0.05 / clarity
    sca.inputs["Anisotropy"].default_value = 0.65
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(absn.outputs[0], add.inputs[0])
    nt.links.new(sca.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs["Volume"])


def shadow_pass(nt, shader_socket, out_socket):
    """Let shadow and diffuse rays through the water surface (no caustics needed)."""
    lp = nt.nodes.new("ShaderNodeLightPath")
    mx = nt.nodes.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    nt.links.new(lp.outputs["Is Shadow Ray"], mx.inputs[0])
    nt.links.new(lp.outputs["Is Diffuse Ray"], mx.inputs[1])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(mx.outputs[0], mix.inputs[0])
    nt.links.new(shader_socket, mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out_socket)


def mat_water_top(clarity=1.0, rough=0.015):
    m = bpy.data.materials.new("renderWaterTop")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    glass = nt.nodes.new("ShaderNodeBsdfPrincipled")
    glass.inputs["Base Color"].default_value = (0.85, 0.97, 1.0, 1)
    glass.inputs["Roughness"].default_value = rough
    glass.inputs["IOR"].default_value = 1.333
    glass.inputs["Transmission Weight"].default_value = 1.0
    # ripples: two scales of noise into a bump
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 3.5
    n1.inputs["Detail"].default_value = 6
    n2 = nt.nodes.new("ShaderNodeTexWave")
    n2.inputs["Scale"].default_value = 0.35
    n2.inputs["Distortion"].default_value = 6
    nt.links.new(tc.outputs["Object"], n1.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], n2.inputs["Vector"])
    ad = nt.nodes.new("ShaderNodeMath")
    ad.operation = "ADD"
    nt.links.new(n1.outputs["Fac"], ad.inputs[0])
    nt.links.new(n2.outputs["Fac"], ad.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.02
    nt.links.new(ad.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], glass.inputs["Normal"])
    shadow_pass(nt, glass.outputs[0], out.inputs["Surface"])
    water_volume_nodes(nt, out, clarity)
    return m


def mat_water_section(clarity=1.0):
    m = bpy.data.materials.new("renderWaterSection")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(tr.outputs[0], out.inputs["Surface"])
    water_volume_nodes(nt, out, clarity)
    return m


def mat_sediment():
    m = bpy.data.materials.new("renderSediment")
    m.use_nodes = True
    nt = m.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    wv = nt.nodes.new("ShaderNodeTexNoise")
    wv.inputs["Scale"].default_value = 3.0
    wv.inputs["Detail"].default_value = 8
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.12, 0.10, 0.075, 1)
    ramp.color_ramp.elements[1].color = (0.24, 0.20, 0.15, 1)
    nt.links.new(tc.outputs["Object"], wv.inputs["Vector"])
    nt.links.new(wv.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 1.0
    return m


def box_mesh(name, x0, x1, y0, y1, z0, z1, mats, front_mat=None):
    bm = bmesh.new()
    res = bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((x0 if v.co.x < 0 else x1, y0 if v.co.y < 0 else y1, z0 if v.co.z < 0 else z1))
    me = bpy.data.meshes.new(name)
    for m in mats:
        me.materials.append(m)
    bm.normal_update()
    for f in bm.faces:
        f.material_index = 0 if f.normal.z > 0.5 else 1
        if front_mat is not None and f.normal.y < -0.5:
            f.material_index = front_mat
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def stage_water(cam, front=None, sediment_top=-6.75, clarity=1.0, rough=0.015):
    """A water block whose near face is a clean section plane `front` metres in front of
    the camera (split view), or far behind it (front=None: plain above-water view).
    Built in the camera's yaw frame, so the section face squarely faces the lens."""
    yaw = cam.matrix_world.to_euler().z
    R = Matrix.Rotation(yaw, 4, "Z")
    cpos = cam.matrix_world.translation
    y_front = -80.0 if front is None else front
    top, sect = mat_water_top(clarity, rough), mat_water_section(clarity)
    # in camera-yaw frame the camera looks along +Y
    wb = box_mesh("stageWater", -80, 80, y_front, 80, -9.0, 0.0, [top, sect])
    wb.matrix_world = Matrix.Translation((cpos.x, cpos.y, 0)) @ R @ Matrix.Rotation(0, 4, "Z")
    # rotate so the local +Y is the camera's view direction
    wb.matrix_world = Matrix.Translation((cpos.x, cpos.y, 0)) @ Matrix.Rotation(yaw, 4, "Z")
    sed = box_mesh("stageSediment", -80, 80, (y_front if front else -80) + 0.001, 80, -12.0, sediment_top, [mat_sediment(), mat_sediment()])
    sed.matrix_world = wb.matrix_world.copy()
    wb.visible_shadow = False
    for o in (wb, sed):
        o["renderStage"] = True
    return wb, sed


def hide_for_render():
    for n in ("waterSurface",):
        o = bpy.data.objects.get(n)
        if o:
            o.hide_render = True
    mf = bpy.data.objects.get("mountFloat")
    if mf:
        for o in [mf] + list(mf.children_recursive):
            o.hide_render = True


def camera(name, loc, look_at, lens=35, dof=None, fstop=4.0, sensor=36):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = sensor
    cd.clip_start = 0.02
    cd.clip_end = 400
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    d = Vector(look_at) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if dof:
        cd.dof.use_dof = True
        cd.dof.focus_distance = dof
        cd.dof.aperture_fstop = fstop
    bpy.context.scene.camera = cam
    bpy.context.view_layer.update()
    return cam


def sun(strength, elev_deg, azim_deg, angle_deg=1.0, color=(1.0, 0.96, 0.9)):
    ld = bpy.data.lights.new("stageSun", "SUN")
    ld.energy = strength
    ld.angle = math.radians(angle_deg)
    ld.color = color
    ob = bpy.data.objects.new("stageSun", ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler = Euler((math.radians(90 - elev_deg), 0, math.radians(azim_deg)))
    return ob


# ------------------------------------------------------------------ shots

def shot_hero(o, w=1920, h=1080, name="hero-16x9.png", cam_loc=(-1.8, -1.6, 0.55), target=(1.2, 1.0, 0.55), lens=16, shift_x=0.0, shift_y=-0.19, front=1.7):
    hide_for_render()
    cam = camera("cam", cam_loc, target, lens=lens)
    cam.data.shift_x = shift_x
    cam.data.shift_y = shift_y
    stage_water(cam, front=front)
    world_sky(o["hdri"], 1.0, math.radians(200))
    sun(3.2, 42, -35)
    setup_cycles(o["samples"], w, h, o["scale"])
    return name


def shot_og(o):
    return shot_hero(o, 1200, 630, "og-image.png", cam_loc=(-1.8, -1.6, 0.55), target=(1.2, 1.0, 0.55), lens=16, shift_x=-0.13, shift_y=-0.17, front=1.7)


def shot_farm(o):
    """Split view down the length of the longlines; clearer water so the far lines read."""
    hide_for_render()
    cam = camera("cam", (-19.0, -1.8, 0.35), (5.0, 0.6, 0.35), lens=18)
    cam.data.shift_y = -0.10
    stage_water(cam, front=3.0, clarity=2.2)
    world_sky(o["hdri"], 1.0, math.radians(200))
    sun(3.2, 42, -35)
    setup_cycles(o["samples"], 1920, 1080, o["scale"])
    return "farm-wide.png"


def shot_unit(o):
    hide_for_render()
    cam = camera("cam", (1.7, -1.7, 1.45), (0.0, 0.05, 0.40), lens=45, dof=2.6, fstop=5.6)
    stage_water(cam, front=None, rough=0.07)
    # the skirt's mirror image in the rippled surface reads as a stray white shape; drop it
    for n in ("traySkirt", "socketBody"):
        ob = bpy.data.objects.get(n)
        if ob:
            ob.visible_glossy = False
    world_sky(o["hdri"], 1.0, math.radians(110))
    sun(3.5, 40, 80)
    setup_cycles(o["samples"], 1600, 1600, o["scale"])
    return "unit-closeup.png"


def shot_head(o):
    sc = bpy.context.scene
    # show the exploded state: evaluate the explode track at its last frame
    for ob in bpy.data.objects:
        ad = ob.animation_data
        if ad:
            for tr in ad.nla_tracks:
                tr.mute = tr.name != "explode"
    sc.frame_set(45)
    world_flat((0.93, 0.93, 0.92), 0.25)
    # curved backdrop
    bm = bmesh.new()
    prof = [(-3.0, -0.35)] + [(-0.0 + 0.6 * math.sin(a), -0.35 + 0.6 - 0.6 * math.cos(a)) for a in [i * math.pi / 2 / 12 for i in range(13)]]
    prof = [(-3.0, -0.35), (0.0, -0.35)] + [(0.6 * math.sin(a), -0.35 + 0.6 - 0.6 * math.cos(a)) for a in [i * math.pi / 2 / 12 for i in range(1, 13)]] + [(0.6, 3.0)]
    rows = []
    for y, z in prof:
        rows.append([bm.verts.new((x, y, z)) for x in (-4.0, 4.0)])
    for a, b in zip(rows, rows[1:]):
        bm.faces.new((a[0], a[1], b[1], b[0]))
    me = bpy.data.meshes.new("stageBackdrop")
    bm.to_mesh(me)
    bm.free()
    m = bpy.data.materials.new("stageBackdrop")
    m.use_nodes = True
    bs = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bs.inputs["Base Color"].default_value = (0.80, 0.81, 0.80, 1)
    bs.inputs["Roughness"].default_value = 0.8
    me.materials.append(m)
    for p in me.polygons:
        p.use_smooth = True
    bd = bpy.data.objects.new("stageBackdrop", me)
    sc.collection.objects.link(bd)
    bd.location = (0, 0.45, 0.06)
    # studio lights
    def area(name, loc, energy, size, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.size = size
        ld.color = color
        ob = bpy.data.objects.new(name, ld)
        sc.collection.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (Vector((0.05, 0, 0.02)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return ob
    area("key", (-0.9, -1.1, 1.2), 140, 1.0, (1.0, 0.97, 0.93))
    area("fill", (1.3, -0.9, 0.4), 30, 1.5, (0.92, 0.96, 1.0))
    area("rim", (0.4, 1.0, 1.1), 55, 0.8)
    area("top", (0.0, 0.0, 1.6), 20, 2.0)
    cam = camera("cam", (0.30, -1.60, 0.70), (0.01, 0.0, 0.12), lens=47)
    setup_cycles(o["samples"], 1600, 1200, o["scale"])
    sc.view_settings.exposure = -0.3
    return "head-exploded.png"


def strip_png_text(path):
    """Drop PNG text and time chunks; Blender writes the .blend path and date into them."""
    import struct
    data = open(path, "rb").read()
    out, i = [data[:8]], 8
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        if kind not in (b"tEXt", b"zTXt", b"iTXt", b"tIME"):
            out.append(data[i:i + 12 + n])
        i += 12 + n
    open(path, "wb").write(b"".join(out))


SHOTS = {"hero": shot_hero, "og": shot_og, "farm": shot_farm, "unit": shot_unit, "head": shot_head}


def main():
    o = args()
    name = SHOTS[o["shot"]](o)
    os.makedirs(o["out"], exist_ok=True)
    path = os.path.join(o["out"], name)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    strip_png_text(path)
    print("wrote", path)


if __name__ == "__main__":
    main()
