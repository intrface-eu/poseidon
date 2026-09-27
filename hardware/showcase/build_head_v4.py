"""Build the v4 listening-head scene: head.blend and build/head.raw.glb.

Run: Blender -b --python hardware/showcase/build_head_v4.py
Geometry: hardware/candidates/passive-v3/cad/generated/passive-v3/INTRFACE_PASSIVE_V3.glb only.
The three EMPTY_* reserve envelopes are left out: they are allocations, not parts.
"""

import bpy
import math
import os
import sys
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import v4_lib as L
importlib.reload(L)

FPS = 30
EXPLODE_FRAMES = 45  # 1.5 s

# CAD (mm, Z = tube axis) -> head frame (m): X = tube axis toward the dome,
# Z = CAD +Y (the side the cables leave, up when deployed), Y = CAD +X (hydrophone side).
CAD_TO_HEAD = Matrix((
    (0, 0, 1, -0.150),
    (1, 0, 0, 0.0),
    (0, 1, 0, 0.0),
    (0, 0, 0, 1),
))

# node name, label, CAD parts, material key
PARTS = [
    ("enclosureTube", "Enclosure tube", ["V3_TUBE_AL6061_BR106279_300"], "tube"),
    ("frontFlange", "Front flange", ["V3_FLANGE_FORWARD_SOURCE_ID_CONFLICT"], "black_al"),
    ("rearFlange", "Rear flange", ["V3_FLANGE_AFT_SOURCE_ID_CONFLICT"], "black_al"),
    ("endCap", "End cap", ["V3_AFT_CAP_5_M10_AL6061"], "black_al"),
    ("cableConnector", "Cable connector", ["V3_WETLINK_M10_7P5_SOURCE_REVISION_CONFLICT"], "connector"),
    ("domeRing", "Dome retaining ring", ["V3_DOME_RETAINING_RING_ALUMINIUM"], "black_al"),
    ("dome", "Camera dome", ["V3_DOME_POLYCARBONATE_BR107201"], "dome"),
]
GROUPS = [
    ("camera", "Camera", [
        ("cameraBoard", "Camera board and lens", ["V3_CAMERA_BR_LOW_LIGHT_USB_VENDOR_INTERNALS"], "pcb"),
        ("cameraTray", "Camera tray", ["V3_CAMERA_TRAY_PEEK_ALLOCATION"], "peek"),
        ("cameraStandoffs", "Camera standoffs", ["V3_CAMERA_STANDOFF_00_PEEK", "V3_CAMERA_STANDOFF_01_PEEK",
                                                  "V3_CAMERA_STANDOFF_10_PEEK", "V3_CAMERA_STANDOFF_11_PEEK"], "peek"),
    ]),
    ("hydrophone", "Hydrophone", [
        ("hydrophoneElement", "Hydrophone element", ["V3_AS1_RECEIVE_ONLY_SOURCE_ENVELOPE"], "rubber"),
        ("hydrophoneBracket", "Hydrophone bracket", ["V3_AS1_NONMETAL_STANDOFF_BRACKET"], "peek"),
        ("hydrophoneCable", "Hydrophone cable", ["V3_AS1_ANALOG_CABLE_DRY_HUB_ROUTE_CONCEPT"], "cable_black"),
    ]),
    ("longlineClamp", "Longline clamp", [
        ("clampSaddle", "Clamp saddle", ["V3_LONGLINE_FIXED_JAW_SADDLE_LANYARD_LUG"], "peek"),
        ("clampJaw", "Release jaw", ["V3_DIVER_RELEASE_MOVING_JAW"], "peek"),
        ("clampPins", "Pull pins", ["V3_DIVER_PULL_PIN_1_ISOLATED_316", "V3_DIVER_PULL_PIN_2_ISOLATED_316"], "steel"),
        ("clampPinSleeves", "Pin sleeves", ["V3_PIN_1_PEEK_ISOLATION_SLEEVE", "V3_PIN_2_PEEK_ISOLATION_SLEEVE"], "peek_dark"),
        ("clampLanyard", "Safety lanyard", ["V3_LANYARD_ROUTE_CONCEPT_UNTERMINATED"], "lanyard"),
    ]),
    ("tetherStrainRelief", "Tether and strain relief", [
        ("strainRelief", "Strain relief", ["V3_TETHER_NONMETAL_STRAIN_RELIEF_CONCEPT"], "peek"),
        ("tetherCable", "Tether", ["V3_FATHOM_TETHER_SURFACE_ROUTE_CONCEPT"], "tether"),
    ]),
]

# Explode endpoints (metres, head frame). The enclosure tube is the datum and never moves.
EXPLODE = {
    "frontFlange": (0.07, 0, 0),
    "camera": (0.17, 0, 0),
    "domeRing": (0.27, 0, 0),
    "dome": (0.36, 0, 0),
    "rearFlange": (-0.07, 0, 0),
    "endCap": (-0.14, 0, 0),
    "cableConnector": (-0.21, 0, 0),
    "tetherStrainRelief": (-0.30, 0, 0),
    "hydrophone": (0, 0, 0.20),
    "longlineClamp": (0, 0, -0.20),
}


def head_materials():
    return {
        "tube": L.material("anodisedAluminium", (0.70, 0.72, 0.74), 1.0, 0.30),
        "black_al": L.material("blackAnodisedAluminium", (0.035, 0.037, 0.042), 0.9, 0.34),
        "connector": L.material("connectorBody", (0.06, 0.06, 0.065), 0.6, 0.4),
        "dome": L.material("polycarbonateDome", (0.92, 0.96, 1.0), 0.0, 0.04, transmission=1.0, ior=1.58),
        "pcb": L.material("cameraBoard", (0.03, 0.10, 0.06), 0.1, 0.45),
        "peek": L.material("peek", (0.50, 0.38, 0.22), 0.0, 0.5),
        "peek_dark": L.material("peekDark", (0.30, 0.22, 0.13), 0.0, 0.55),
        "rubber": L.material("hydrophoneUrethane", (0.05, 0.06, 0.07), 0.0, 0.6),
        "cable_black": L.material("cableBlack", (0.03, 0.03, 0.035), 0.0, 0.45),
        "steel": L.material("stainless316", (0.80, 0.80, 0.80), 1.0, 0.22),
        "lanyard": L.material("lanyardRope", (0.85, 0.24, 0.05), 0.0, 0.7),
        "tether": L.material("tetherJacket", (0.92, 0.68, 0.05), 0.0, 0.42),
    }


def build_head(parent=None, coll=None, mats=None, name="head"):
    """Import the passive-v3 CAD and return the assembled head root (head frame at origin)."""
    mats = mats or head_materials()
    parts = L.import_cad(L.PASSIVE_GLB)
    for n, o in list(parts.items()):
        if n.startswith("EMPTY_"):
            bpy.data.objects.remove(o, do_unlink=True)
            del parts[n]
        else:
            o.data.transform(CAD_TO_HEAD)
            o.data.update()
    root = L.empty(name, parent, coll=coll)
    root["label"] = "Listening head"

    def make(node, label, src, mkey, par):
        obs = [parts.pop(s) for s in src]
        ob = L.join(obs, node)
        ob.data.materials.clear()
        ob.data.materials.append(mats[mkey])
        L.set_smooth(ob, 32)
        ob.parent = par
        ob["label"] = label
        ob["cadParts"] = ", ".join(src)
        return ob

    nodes = {}
    for node, label, src, mkey in PARTS:
        nodes[node] = make(node, label, src, mkey, root)
    for gname, glabel, members in GROUPS:
        g = L.empty(gname, root, coll=coll)
        g["label"] = glabel
        nodes[gname] = g
        for node, label, src, mkey in members:
            nodes[node] = make(node, label, src, mkey, g)
    assert not parts, parts.keys()
    return root, nodes


def ease(t):
    return t * t * (3 - 2 * t)


def add_explode_clips(nodes, frames=EXPLODE_FRAMES):
    """NLA tracks 'explode' and 'assemble' on every moving part; exported as two clips."""
    for node, off in EXPLODE.items():
        ob = nodes[node]
        rest = ob.location.copy()
        end = rest + Vector(off)
        ob.animation_data_create()
        for clip, a, b in (("explode", rest, end), ("assemble", end, rest)):
            act = bpy.data.actions.new(f"{clip}_{node}")
            ob.animation_data.action = act
            for f in range(0, frames + 1, 3):
                ob.location = a.lerp(b, ease(f / frames))
                ob.keyframe_insert("location", frame=f)
            track = ob.animation_data.nla_tracks.new()
            track.name = clip
            strip = track.strips.new(clip, 0, act)
            strip.name = clip
            track.mute = True
            ob.animation_data.action = None
        ob.location = rest
        ob["explodeOffsetGltf"] = [off[0], off[2], -off[1]]


def export_glb(path, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    args = dict(filepath=path, export_format="GLB", export_yup=True, export_extras=True,
                export_apply=True, export_animations=True, export_animation_mode="NLA_TRACKS",
                export_cameras=False, export_lights=False, use_visible=False, use_renderable=False,
                export_texcoords=True, export_normals=True, export_materials="EXPORT",
                export_image_format="AUTO", export_optimize_animation_size=True)
    args.update(kw)
    bpy.ops.export_scene.gltf(**args)


def main():
    L.clear_scene()
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 0, EXPLODE_FRAMES
    root, nodes = build_head(name="head")
    root["contract"] = "poseidon.showcase.head.v4"
    root["units"] = "metres"
    root["explodeAxis"] = "Enclosure tube axis, glTF +X toward the dome. Hydrophone lifts +Y, clamp drops -Y."
    root["datum"] = "enclosureTube and head never move in any clip."
    root["status"] = "Design render of a non-adopted candidate. Not built, not tested."
    add_explode_clips(nodes)
    sc.frame_set(0)
    return root, nodes


if __name__ == "__main__":
    main()
    L.save_blend(os.path.join(L.HERE, "head.blend"))
    export_glb(os.path.join(L.BUILD_DIR, "head.raw.glb"))
