"""Read and explicitly update LibreOffice user-profile fields (#115)."""
import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET

FIELDS = {"givenname", "sn", "o", "street", "postalcode", "l", "c", "st", "mail", "telephonenumber", "homephone"}
OOR = "http://openoffice.org/2001/registry"
PROFILE = "/org.openoffice.UserProfile/Data"
LIMIT = 8 * 1024 * 1024


def exchange(path, changes=None, stamp=None):
    if not path or not os.path.isfile(path):
        raise ValueError("No LibreOffice user profile is available.")
    with open(path, "rb") as source:
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Invalid LibreOffice settings file.")
    current = hashlib.sha256(raw).hexdigest()
    root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    items = [node for node in root.iter() if isinstance(node.tag, str) and node.tag.split("}")[-1] == "item" and
             node.get("{%s}path" % OOR, "").endswith(PROFILE)]
    if changes is not None:
        if (not isinstance(changes, dict) or not set(changes) <= FIELDS or
                any(not isinstance(value, str) or len(value) > 2000 or "\0" in value for value in changes.values())):
            raise ValueError("Invalid LibreOffice profile fields.")
        if current != stamp:
            raise ValueError("LibreOffice user data changed. Compare the fields again.")
        if os.path.exists(os.path.join(os.path.dirname(path), "..", ".lock")):
            raise ValueError("Close LibreOffice before updating its user data.")
        if not items:
            items = [ET.SubElement(root, "item", {"{%s}path" % OOR: PROFILE})]
        for item in items:
            for prop in list(item):
                if isinstance(prop.tag, str) and prop.tag.split("}")[-1] == "prop" and prop.get("{%s}name" % OOR) in changes:
                    item.remove(prop)
        for key, value in changes.items():
            prop = ET.SubElement(items[0], "prop", {"{%s}name" % OOR: key, "{%s}op" % OOR: "fuse"})
            ET.SubElement(prop, "value").text = value
        ET.register_namespace("oor", OOR)
        updated = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        fd, temporary = tempfile.mkstemp(prefix=".magnolie-profile-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(updated); target.flush(); os.fsync(target.fileno())
            with open(path, "rb") as source:
                if source.read(LIMIT + 1) != raw:
                    raise ValueError("LibreOffice user data changed. Compare the fields again.")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        current = hashlib.sha256(updated).hexdigest()
    fields = {}
    for item in items:
        for prop in item:
            key = prop.get("{%s}name" % OOR)
            if key in FIELDS:
                fields[key] = next((node.text or "" for node in prop if isinstance(node.tag, str) and node.tag.split("}")[-1] == "value"), "")
    return {"ok": True, "felder": fields, "stamp": current}
