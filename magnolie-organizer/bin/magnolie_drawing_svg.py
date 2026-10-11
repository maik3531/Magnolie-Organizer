"""Validate the geometry-only SVG emitted by the drawing renderer."""
import re
import xml.etree.ElementTree as ET


def validated_bytes(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > 64 * 1024 * 1024 or "<!" in value:
        raise ValueError("invalid drawing SVG")
    root = ET.fromstring(value)
    namespace = "{http://www.w3.org/2000/svg}"
    if root.tag != namespace + "svg":
        raise ValueError("invalid drawing SVG root")
    tags = {namespace + name for name in ("svg", "defs", "mask", "g", "path", "rect", "linearGradient", "stop")}
    for node in root.iter():
        if node.tag not in tags or (node.text or "").strip() or (node.tail or "").strip():
            raise ValueError("unsupported drawing SVG element")
        for name, raw in node.attrib.items():
            allowed = (name in {"x", "y", "width", "height", "stroke-width", "opacity", "viewBox", "x1", "y1", "x2", "y2", "offset"} and re.fullmatch(r"[0-9. +%-]+", raw) or
                       name == "d" and re.fullmatch(r"[MLACZ0-9. +,-]+", raw) or
                       name in {"fill", "stroke", "stop-color"} and re.fullmatch(r"#[0-9a-fA-F]{6}|white|none", raw) or
                       name == "fill" and re.fullmatch(r"url\(#gradient[0-9]+\)", raw) or
                       name == "id" and re.fullmatch(r"(?:erase|gradient)[0-9]+", raw) or
                       name == "mask" and re.fullmatch(r"url\(#erase[0-9]+\)", raw) or
                       name in {"maskUnits", "gradientUnits"} and raw == "userSpaceOnUse" or
                       name in {"stroke-linecap", "stroke-linejoin"} and raw == "round")
            if not allowed:
                raise ValueError("unsupported drawing SVG attribute")
    return value.encode("utf-8")
