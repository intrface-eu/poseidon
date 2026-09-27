"""Candidate-only engineering exports and STEP import checks; no baseline writes."""
from __future__ import annotations
import html
import math
import xml.etree.ElementTree as ET
import cadquery as cq
import ezdxf
from candidate_parameters import REVISION, STATUS
from model import bbox, geometry_checks


def roundtrip(path, shape):
    text = path.read_text(errors="replace")
    units = "SI_UNIT(.MILLI.,.METRE.)" in text
    imported = cq.importers.importStep(str(path)).val()
    b1, b2 = bbox(shape), bbox(imported)
    delta = max(abs(b1[key][i] - b2[key][i]) for key in ("min_mm", "max_mm") for i in range(3))
    vd = abs(shape.Volume() - imported.Volume())
    vt = max(1e-3, shape.Volume()*1e-8)
    count = len(shape.Solids())
    return {"id": path.stem + "_step_roundtrip", "passed": bool(units and imported.isValid() and delta <= 1e-4 and vd <= vt and len(imported.Solids()) == count),
            "units_mm": units, "bbox_max_delta_mm": delta, "volume_delta_mm3": vd, "volume_tolerance_mm3": vt,
            "expected_solids": count, "imported_solids": len(imported.Solids()), "evidence": "Fresh STEP import and OCP BRep validity, bbox, volume and solid-count comparison"}


def projection_edges(shape, axes):
    for edge in shape.Edges():
        n = 2 if edge.geomType() == "LINE" else max(16, min(80, int(edge.Length()/4)+2))
        points = [edge.positionAt(i/(n-1)).toTuple() for i in range(n)]
        xy = [(p[axes[0]], p[axes[1]]) for p in points]
        if any(math.dist(xy[0], p) > 1e-5 for p in xy[1:]):
            yield xy


def drawing(a, out):
    shape = a.compound()
    bounds = bbox(shape)
    sizes = bounds["size_mm"]
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="1120" viewBox="0 0 1500 1120">', '<rect width="1500" height="1120" fill="white"/>',
           '<g fill="#172d39" font-family="Arial,sans-serif">', f'<text x="40" y="40" font-size="26">{a.id} / {REVISION} / mm / {html.escape(STATUS)}</text>',
           f'<text x="40" y="70" font-size="18">{html.escape(a.description)}</text>', '<text x="40" y="98" font-size="17">ENGINEERING REFERENCE: no build, procurement, pressure, thermal, electrical or load qualification.</text>']
    dxf = ezdxf.new("R2018")
    dxf.units = ezdxf.units.MM
    dxf.header["$MEASUREMENT"] = 1
    space = dxf.modelspace()
    for name in ("TOP", "FRONT", "RIGHT", "NOTES", "DIMENSIONS"):
        dxf.layers.new(name)
    for view, ox, oy, w, h, axes, offset in [("TOP", 40, 135, 680, 355, (0,1), (0,0)), ("FRONT", 40, 550, 680, 355, (0,2), (0,-sizes[2]-150)), ("RIGHT", 790, 135, 650, 770, (1,2), (sizes[0]+150,0))]:
        u,v=axes
        scale=min((w-100)/sizes[u],(h-80)/sizes[v])
        sx,sy=ox+40,oy+h-45
        xmin,ymin=bounds["min_mm"][u],bounds["min_mm"][v]
        svg.append(f'<text x="{ox}" y="{oy+18}" font-size="17">{view}, {scale:.3f} px/mm; do not scale print</text>')
        for points in projection_edges(shape, axes):
            xy=" ".join(f"{sx+(x-xmin)*scale:.3f},{sy-(y-ymin)*scale:.3f}" for x,y in points)
            svg.append(f'<polyline points="{xy}" fill="none" stroke="#243e4c" stroke-width="1"/>')
            space.add_lwpolyline([(x-xmin+offset[0],y-ymin+offset[1]) for x,y in points],dxfattribs={"layer":view})
        x2,y2=sx+sizes[u]*scale,sy-sizes[v]*scale
        svg.extend([f'<path d="M{sx},{sy+8}V{sy+25}M{x2},{sy+8}V{sy+25}M{sx},{sy+18}H{x2}" stroke="#52616b" fill="none"/>',
                    f'<text x="{(sx+x2)/2}" y="{sy+39}" font-size="14" text-anchor="middle">{sizes[u]:.2f} mm</text>',
                    f'<path d="M{sx-8},{sy}H{sx-25}M{sx-8},{y2}H{sx-25}M{sx-18},{sy}V{y2}" stroke="#52616b" fill="none"/>',
                    f'<text x="{sx-23}" y="{(sy+y2)/2}" transform="rotate(-90 {sx-23} {(sy+y2)/2})" font-size="14" text-anchor="middle">{sizes[v]:.2f} mm</text>'])
        dx,dy=offset
        style={"dimtxt":max(2.5,max(sizes)/150),"dimasz":max(2.5,max(sizes)/200),"dimdec":2}
        space.add_linear_dim(base=(dx,dy-35),p1=(dx,dy),p2=(dx+sizes[u],dy),override=style,dxfattribs={"layer":"DIMENSIONS"}).render()
        space.add_linear_dim(base=(dx-35,dy),p1=(dx,dy),p2=(dx,dy+sizes[v]),angle=90,override=style,dxfattribs={"layer":"DIMENSIONS"}).render()
    notes=["Orthographic wireframe, XY/XZ/YZ; curved edges sampled. STEP holds exact solids; all dimension entities use mm.",
           "Part/source/feature schedule distinguishes verified overall envelopes from custom assumed details. No pressure parts or STL exports.",
           "Two physical40W panels,2S1P,668x425x25mm each,50mm edge gap. Face area0.5678m2; no wind-load or energy-yield acceptance.",
           "Cable R56mm at8mm diameter is a provisional6D allowance; terminal positions and cable/connector specifications remain open.",
           "Metal finish, galvanic isolation, mounting zones, torque, preload, thermal contact/air capture and shade heat require independent review.",
           "Tolerances assumed: linear +/-0.3mm, cable diameter +/-0.3mm, bend radius +/-0.5mm. Not fabrication specifications.",
           "Existing HW-REF-1.1 is frozen. This is NON-ADOPTED HW-CAND-2.0, not a replacement field configuration."]
    for i,note in enumerate(notes):
        svg.append(f'<text x="40" y="{955+i*23}" font-size="14">{html.escape(note)}</text>')
        space.add_text(note,dxfattribs={"height":4,"layer":"NOTES","insert":(0,-sizes[2]-250-i*9)})
    svg.extend(["</g>","</svg>"])
    (out/f"{a.id}.svg").write_text("\n".join(svg))
    dxf.saveas(out/f"{a.id}.dxf")


def feature_sheet(a,out):
    import json,textwrap
    lines=[]
    for p in a.parts:
        lines.append(p.id+" / BOM "+p.bom_id+" / "+p.source_status)
        lines.extend("  "+line for line in textwrap.wrap(p.description+"; "+p.note,130))
        for key,value in p.features.items():
            lines.extend("  "+line for line in textwrap.wrap(key+": "+json.dumps(value),130))
    h=160+21*len(lines)
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="{h}"><rect width="100%" height="100%" fill="white"/>', '<g font-family="monospace" fill="#172d39">',
         f'<text x="30" y="40" font-size="24">{a.id} / {REVISION} / FEATURE-SOURCE-FASTENER SCHEDULE</text>', f'<text x="30" y="75" font-size="19">{STATUS} / mm / No fabrication or thermal/load qualification</text>']
    for i,line in enumerate(lines):
        svg.append(f'<text x="30" y="{115+i*21}" font-size="15">{html.escape(line)}</text>')
    svg.extend(["</g>","</svg>"])
    (out/f"{a.id}_features.svg").write_text("\n".join(svg))


def view(a,out,kind):
    ns="http://www.w3.org/2000/svg"
    shapes=[p.shape.translate((0,0,i*24 if kind=="exploded" else 0)) for i,p in enumerate(a.parts)]
    if kind=="keepouts":
        shapes.extend(ko["shape"] for ko in a.keepouts.values())
    image=cq.exporters.getSVG(cq.Compound.makeCompound(shapes),{"width":1400,"height":1050,"marginLeft":70,"marginTop":100,"projectionDir":(1,-1,0.75),"showAxes":False,"showHidden":False})
    root=ET.fromstring(image)
    projection=ET.Element(f"{{{ns}}}g",{"transform":"rotate(180 700 525)"})
    for child in list(root):
        root.remove(child)
        projection.append(child)
    root.append(projection)
    root.insert(0,ET.Element(f"{{{ns}}}rect",{"width":"100%","height":"100%","fill":"white"}))
    for y,text in ((30,f"{a.id} / {REVISION} / {kind.upper()} / {STATUS}"),(58,"Z-up review view. Exploded spacing is not assembly order. Keepout allocations are not physical BOM parts.")):
        node=ET.SubElement(root,f"{{{ns}}}text",{"x":"25","y":str(y),"font-family":"Arial","font-size":"18","fill":"#172d39"})
        node.text=text
    (out/f"{a.id}_{kind}.svg").write_text(ET.tostring(root,encoding="unicode"))


def export(a,out):
    path=out/"step"/f"{a.id}.step"
    a.native().export(str(path),"STEP")
    checks=geometry_checks(a)+[roundtrip(path,a.compound())]
    keepouts=[]
    if a.keepouts:
        ka=cq.Assembly(name=a.id+"_KEEP_OUT_NOT_PARTS")
        for id,ko in a.keepouts.items():
            ka.add(ko["shape"],name=id,color=cq.Color(1,0.5,0.1,0.2))
            keepouts.append({"id":id,"bbox":bbox(ko["shape"]),"note":ko["note"],"category":ko["category"],"bom_item":False})
        kp=out/"keepouts"/f"{a.id}_keepouts.step"
        ka.export(str(kp),"STEP")
        checks.append(roundtrip(kp,cq.Compound.makeCompound([ko["shape"] for ko in a.keepouts.values()])))
    drawing(a,out/"drawings")
    feature_sheet(a,out/"drawings")
    for kind in ("assembly","exploded","keepouts"):
        view(a,out/"views",kind)
    return {"id":a.id,"description":a.description,"bbox":bbox(a.compound()),"parts":[p.metadata() for p in a.parts],"keepouts":keepouts,"checks":checks,
            "step":f"step/{a.id}.step","drawing_dxf":f"drawings/{a.id}.dxf","drawing_svg":f"drawings/{a.id}.svg"}
