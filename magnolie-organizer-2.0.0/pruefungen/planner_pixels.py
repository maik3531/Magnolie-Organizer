"""Compare native synthetic Planner screenshots without modifying either image."""
import json
from pathlib import Path
import sys

from PIL import Image, ImageChops

paths = [Path(value).resolve() for value in sys.argv[1:]]
assert len(paths) == 2 and all(path.is_relative_to("/tmp/opencode") for path in paths)
images = [Image.open(path).convert("RGBA") for path in paths]
assert images[0].size == images[1].size, "Screenshot dimensions changed"
difference = ImageChops.difference(*images)
pixels = list(difference.getdata())
result = {"before": str(paths[0]), "after": str(paths[1]), "size": images[0].size,
          "changed_pixels": sum(any(pixel) for pixel in pixels),
          "max_channel_difference": max(max(pixel) for pixel in pixels)}
print(json.dumps(result))
sys.exit(0 if result["changed_pixels"] == 0 else 1)
