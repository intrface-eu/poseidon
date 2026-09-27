"""Original CadQuery fit envelopes for purchased components; not manufacturing models."""
from __future__ import annotations

import cadquery as cq


def cylinder(radius, length, origin=(0, 0, 0), axis=(0, 0, 1)):
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*origin), cq.Vector(*axis))


def enclosure_tube(d):
    outer = cylinder(d["tube.od"] / 2, d["tube.length"], (-d["tube.length"], 0, 0), (1, 0, 0))
    bore = cylinder(d["tube.id"] / 2, d["tube.length"], (-d["tube.length"], 0, 0), (1, 0, 0))
    # Both purchased end flanges enter a locally enlarged fit clearance.
    for start in (-d["tube.length"], -d["flange.piston_length"]):
        bore = bore.fuse(cylinder(d["flange.piston_diameter"] / 2 + 0.01,
                                 d["flange.piston_length"], (start, 0, 0), (1, 0, 0)))
    return outer.cut(bore)


def end_flange(d):
    piston = cylinder(d["flange.piston_diameter"] / 2, d["flange.piston_length"])
    rim = cylinder(d["flange.od"] / 2, d["flange.length"] - d["flange.piston_length"],
                   (0, 0, d["flange.piston_length"]))
    return piston.fuse(rim).cut(cylinder(44, d["flange.length"]))


def end_cap(d, centers):
    # Disk sits outside the flange; the smaller boss enters its clear central bore.
    cap = cylinder(d["flange.od"] / 2, 6).fuse(cylinder(44, 4, (0, 0, -4)))
    for x, y in centers:
        cap = cap.cut(cylinder(d["aft_cap.penetrator_hole_diameter"] / 2,
                               d["aft_cap.thickness"], (x, y, -4)))
    return cap


def optical_dome(d):
    # The measured radial maximum is a short retaining lip; the spherical
    # shell uses the traced 44 mm inner radius and 5.8 mm nominal wall.
    radius = d["dome.internal_radius"] + d["dome.wall"]
    outer = cq.Solid.makeSphere(radius, cq.Vector(0, 2.002, 0),
                                cq.Vector(0, 1, 0), -90, 90)
    lip = cylinder(d["dome.bbox_size_x"] / 2, 2.002, (0, 0, 0), (0, 1, 0))
    halfspace = cq.Workplane("XY").box(120, 52, 120).val().translate((0, 26, 0))
    return outer.fuse(lip).intersect(halfspace).cut(
        cq.Solid.makeSphere(d["dome.internal_radius"], cq.Vector(0, 0, 0),
                            cq.Vector(0, 1, 0), -90, 90))


def dome_retainer(d):
    return cylinder(d["flange.od"] / 2, d["dome_ring.bbox_size_y"], axis=(0, 1, 0)).cut(
        cylinder(d["dome.bbox_size_x"] / 2, d["dome_ring.bbox_size_y"], axis=(0, 1, 0)))


def camera_module(d):
    # PCB and forward optics allocation. Hole pitch and diameter are trace-bound.
    w, h = d["camera.pcb_width"], d["camera.pcb_height"]
    pcb = cq.Workplane("XY").box(w, d["camera.pcb_thickness"], h).val().translate(
        (w / 2, d["camera.pcb_thickness"] / 2, -h / 2))
    for x in ((w - d["camera.mount_pitch"]) / 2, (w + d["camera.mount_pitch"]) / 2):
        for z in (-(h - d["camera.mount_pitch"]) / 2, -(h + d["camera.mount_pitch"]) / 2):
            pcb = pcb.cut(cylinder(d["camera.mount_hole"] / 2, d["camera.pcb_thickness"],
                                   (x, 0, z), (0, 1, 0)))
    optics = cylinder(8, d["camera.front_depth"] - d["camera.pcb_thickness"], (w / 2, d["camera.pcb_thickness"], -h / 2), (0, 1, 0))
    rear = cq.Workplane("XY").box(16, d["camera.rear_depth"], 16).val().translate(
        (w / 2, -d["camera.rear_depth"] / 2, -h / 2))
    return pcb.fuse(optics, rear)


def cable_penetrator(d):
    # Source revision is 16 mm OD; current datasheet is 18 mm OD, unverified fit.
    body = cylinder(d["wetlink.thread_diameter"] / 2, 45, (0, 0, 0), (0, 1, 0))
    collar = cylinder(8, 3, (0, 21, 0), (0, 1, 0))
    return body.fuse(collar)


def build(d, register):
    centers = register["vendor_models"]["aft_cap"]["penetrator_centers_xy_mm"]
    return {"tube": enclosure_tube(d), "flange": end_flange(d),
            "aft_cap": end_cap(d, centers), "dome": optical_dome(d),
            "dome_ring": dome_retainer(d), "camera": camera_module(d),
            "wetlink": cable_penetrator(d)}
