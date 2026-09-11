"""Clean crop: drop bottom watermark strip only. No blur, no stretch."""
from PIL import Image
import os

root = r"D:\wcy\project\Travel-Assistant\travel-frontend-vue\src\assets\img"
src = os.path.join(root, "candidates")

jobs = [
    ("hero-handbook.jpg", 160),
    ("cover-hangzhou.jpg", 160),
    ("cover-chengdu.jpg", 160),
    ("cover-xian.jpg", 160),
    ("cover-chongqing.jpg", 160),
    ("cover-beijing.jpg", 160),
    ("cover-shanghai.jpg", 160),
    ("bento-notebook.jpg", 170),
]

for name, bottom in jobs:
    path = os.path.join(src, name)
    im = Image.open(path).convert("RGB")
    w, h = im.size
    # crop bottom strip + tiny right margin
    im2 = im.crop((0, 0, w - 16, h - bottom))
    out = os.path.join(root, name)
    im2.save(out, "JPEG", quality=90, optimize=True)
    print(f"{name}: {w}x{h} -> {im2.size}  {os.path.getsize(out)} bytes")

print("done")
