from pathlib import Path
import struct
import zlib

width = height = 1024
colors = {
    "bg": (30, 15, 31),
    "outer": (229, 229, 229),
    "purple": (103, 33, 104),
    "dark": (66, 1, 67),
    "inner": (221, 219, 221),
    "play": (105, 31, 105),
}

def inside_circle(px, py, cx, cy, radius):
    return (px - cx) ** 2 + (py - cy) ** 2 <= radius * radius

def inside_triangle(px, py, a, b, c):
    def sign(p1, p2, p3):
        return ((p1[0] - p3[0]) * (p2[1] - p3[1])
                - (p2[0] - p3[0]) * (p1[1] - p3[1]))
    point = (px, py)
    d1, d2, d3 = sign(point, a, b), sign(point, b, c), sign(point, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0)
               and (d1 > 0 or d2 > 0 or d3 > 0))

rows = []
for y in range(height):
    row = bytearray()
    for x in range(width):
        samples = []
        for sample_y in (0.25, 0.75):
            for sample_x in (0.25, 0.75):
                px, py = x + sample_x, y + sample_y
                color = colors["bg"]
                if inside_circle(px, py, 512, 512, 408): color = colors["outer"]
                if inside_circle(px, py, 523, 500, 379): color = colors["purple"]
                if inside_circle(px, py, 545, 475, 292): color = colors["dark"]
                if inside_circle(px, py, 505, 514, 188): color = colors["inner"]
                if inside_triangle(px, py, (457, 425), (457, 603), (606, 512)):
                    color = colors["play"]
                samples.append(color)
        rgb = tuple(sum(color[index] for color in samples) // len(samples)
                    for index in range(3))
        row.extend((*rgb, 255))
    rows.append(b"\x00" + bytes(row))

raw = b"".join(rows)

def chunk(kind, data):
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(raw, 9))
       + chunk(b"IEND", b""))

output = Path("MPVTorBox/Assets.xcassets/AppIcon.appiconset")
output.mkdir(parents=True, exist_ok=True)
(output / "AppIcon-1024.png").write_bytes(png)
(output / "Contents.json").write_text('''{
  "images" : [
    {
      "filename" : "AppIcon-1024.png",
      "idiom" : "universal",
      "platform" : "ios",
      "size" : "1024x1024"
    }
  ],
  "info" : { "author" : "xcode", "version" : 1 }
}
''')
