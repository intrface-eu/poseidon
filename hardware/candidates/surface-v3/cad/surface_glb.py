"""Strict embedded GLB parser and binary geometry measurements; no third-party imports."""
from __future__ import annotations
import json
import math
import struct
from surface_contract import require


def identity():
    return [[float(r == c) for c in range(4)] for r in range(4)]


def multiply(a, b):
    return [[sum(a[r][k]*b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def point(m, v):
    return [sum(m[r][k]*v[k] for k in range(3))+m[r][3] for r in range(3)]


def matrix(n):
    if "matrix" in n:
        require(not any(k in n for k in ("translation", "rotation", "scale")), "Mixed matrix/TRS")
        a = n["matrix"]
        require(len(a) == 16 and all(math.isfinite(x) for x in a), "Matrix data")
        return [[a[c*4+r] for c in range(4)] for r in range(4)]
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    require(abs(x*x+y*y+z*z+w*w-1) < 1e-5, "Quaternion norm")
    s, t = n.get("scale", [1, 1, 1]), n.get("translation", [0, 0, 0])
    require(len(s) == len(t) == 3 and all(math.isfinite(v) for v in [*s, *t]), "TRS data")
    return [[(1-2*y*y-2*z*z)*s[0], (2*x*y-2*z*w)*s[1], (2*x*z+2*y*w)*s[2], t[0]],
            [(2*x*y+2*z*w)*s[0], (1-2*x*x-2*z*z)*s[1], (2*y*z-2*x*w)*s[2], t[1]],
            [(2*x*z-2*y*w)*s[0], (2*y*z+2*x*w)*s[1], (1-2*x*x-2*y*y)*s[2], t[2]], [0, 0, 0, 1]]


def unpack(path):
    data = path.read_bytes()
    require(len(data) >= 28 and struct.unpack_from("<4sII", data) == (b"glTF", 2, len(data)), "GLB header")
    chunks, offset = [], 12
    while offset < len(data):
        require(offset+8 <= len(data), "Truncated GLB header")
        size, kind = struct.unpack_from("<I4s", data, offset)
        require(size % 4 == 0 and offset+8+size <= len(data), "GLB chunk bounds")
        chunks.append((kind, data[offset+8:offset+8+size]))
        offset += size+8
    require([c[0] for c in chunks] == [b"JSON", b"BIN\0"], "Embedded JSON/BIN only")
    return json.loads(chunks[0][1]), chunks


def encode(doc, chunks):
    raw = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode()
    raw += b" "*((-len(raw)) % 4)
    chunks = [(b"JSON", raw), *chunks[1:]]
    body = b"".join(struct.pack("<I4s", len(blob), kind)+blob for kind, blob in chunks)
    return struct.pack("<4sII", b"glTF", 2, len(body)+12)+body


class Parsed:
    def __init__(self, path):
        self.doc, chunks = unpack(path)
        d = self.doc
        self.bin = chunks[1][1]
        require(d["asset"]["version"] == "2.0" and not d.get("images") and not d.get("textures") and not d.get("animations"), "Static local geometry only")
        require(len(d["buffers"]) == 1 and "uri" not in d["buffers"][0], "External buffer forbidden")
        length = d["buffers"][0]["byteLength"]
        require(0 <= len(self.bin)-length <= 3, "Buffer length mismatch")
        for view in d["bufferViews"]:
            start, size = view.get("byteOffset", 0), view["byteLength"]
            require(view["buffer"] == 0 and start >= 0 and size > 0 and start+size <= length, "Buffer view range")
        self.cache = {}
        for i in range(len(d["accessors"])):
            self.accessor(i)
        self.names, self.parents, self.worlds = {}, {}, {}
        for i, node in enumerate(d["nodes"]):
            name = node.get("name")
            require(name and name not in self.names, "Missing/duplicate node name")
            self.names[name] = i
            for c in node.get("children", []):
                require(type(c) is int and 0 <= c < len(d["nodes"]) and c not in self.parents, "Child reference/multiple parents")
                self.parents[c] = i
        roots = d["scenes"][d.get("scene", 0)]["nodes"]
        require(roots and all(r not in self.parents for r in roots), "Scene root invalid")
        visited = set()
        def visit(i, active):
            require(i not in active and i not in visited, "Cycle or duplicate root traversal")
            visited.add(i)
            parent = self.parents.get(i)
            local = matrix(d["nodes"][i])
            self.worlds[i] = multiply(self.worlds[parent], local) if parent is not None else local
            for c in d["nodes"][i].get("children", []):
                visit(c, active | {i})
        for root in roots:
            visit(root, set())
        require(len(visited) == len(d["nodes"]), "Unreachable nodes")
        for name, i in self.names.items():
            if "mesh" in d["nodes"][i]:
                self.triangles(name)

    def accessor(self, index):
        if index in self.cache:
            return self.cache[index]
        require(type(index) is int and 0 <= index < len(self.doc["accessors"]), "Accessor index")
        a = self.doc["accessors"][index]
        require(not a.get("sparse") and not a.get("normalized"), "Unsupported sparse/normalized accessor")
        formats = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
        counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
        require(a["componentType"] in formats and a["type"] in counts, "Accessor type")
        code, width = formats[a["componentType"]]
        n = counts[a["type"]]
        view = self.doc["bufferViews"][a["bufferView"]]
        stride = view.get("byteStride", width*n)
        start = view.get("byteOffset", 0)+a.get("byteOffset", 0)
        count = a["count"]
        require(type(count) is int and count > 0 and stride >= width*n and start % width == 0 and a.get("byteOffset", 0) >= 0, "Accessor stride/count")
        require(a.get("byteOffset", 0)+(count-1)*stride+width*n <= view["byteLength"], "Accessor out of range")
        rows = [list(struct.unpack_from("<"+code*n, self.bin, start+j*stride)) for j in range(count)]
        require(all(math.isfinite(x) for row in rows for x in row), "Non-finite binary data")
        for key, func in (("min", min), ("max", max)):
            if key in a:
                require(len(a[key]) == n, "Accessor extrema length")
                require(all(abs(func(r[k] for r in rows)-a[key][k]) <= max(1e-6, abs(a[key][k])*2e-6) for k in range(n)), "Accessor extrema differ from binary")
        self.cache[index] = rows
        return rows

    def triangles(self, name):
        node = self.doc["nodes"][self.names[name]]
        require("mesh" in node and 0 <= node["mesh"] < len(self.doc["meshes"]), "Missing mesh: "+name)
        result = []
        transform = self.worlds[self.names[name]]
        for prim in self.doc["meshes"][node["mesh"]]["primitives"]:
            require(prim.get("mode", 4) == 4 and not prim.get("extensions"), "Uncompressed triangles only")
            ai = prim["attributes"]["POSITION"]
            require(self.doc["accessors"][ai]["type"] == "VEC3" and self.doc["accessors"][ai]["componentType"] == 5126, "Float XYZ positions")
            vertices = [point(transform, v) for v in self.accessor(ai)]
            for attr in prim["attributes"].values():
                require(len(self.accessor(attr)) == len(vertices), "Mesh attribute count")
            if "indices" in prim:
                index = prim["indices"]
                a = self.doc["accessors"][index]
                require(a["type"] == "SCALAR" and a["componentType"] in (5121, 5123, 5125), "Triangle index type")
                ids = [r[0] for r in self.accessor(index)]
            else:
                ids = list(range(len(vertices)))
            require(len(ids) % 3 == 0 and all(type(i) is int and 0 <= i < len(vertices) for i in ids), "Triangle indices")
            result.extend([[vertices[ids[j+k]] for k in range(3)] for j in range(0, len(ids), 3)])
        require(result, "Empty triangle mesh")
        return result

    def geometry(self, name):
        triangles = self.triangles(name)
        vertices = [v for tri in triangles for v in tri]
        lo = [min(v[k] for v in vertices) for k in range(3)]
        hi = [max(v[k] for v in vertices) for k in range(3)]
        # Shift origin to reduce cancellation on a 6.9 m pole with a 3 mm wall.
        origin = [(a+b)/2 for a, b in zip(lo, hi)]
        volume = 0
        for tri in triangles:
            a, b, c = [[v[k]-origin[k] for k in range(3)] for v in tri]
            cross = [b[1]*c[2]-b[2]*c[1], b[2]*c[0]-b[0]*c[2], b[0]*c[1]-b[1]*c[0]]
            volume += sum(a[k]*cross[k] for k in range(3))/6
        return {"min_m": lo, "max_m": hi, "triangle_count": len(triangles), "enclosed_mesh_volume_m3": abs(volume)}


def expected_bounds(b):
    return {"min_m": [b["min_mm"][0]/1000, b["min_mm"][2]/1000, -b["max_mm"][1]/1000],
            "max_m": [b["max_mm"][0]/1000, b["max_mm"][2]/1000, -b["min_mm"][1]/1000]}
