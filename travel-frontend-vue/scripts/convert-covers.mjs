// 封面图 WebP 转换管线（M4 §5.6）：src/assets/covers/*.jpg → *.webp
// 用法：node scripts/convert-covers.mjs
// 质量 78：单张目标 ≤200KB（§5.6 上限），肉眼无损级；源 JPG 保留作回退
import { readdir, stat } from 'node:fs/promises'
import path from 'node:path'
import sharp from 'sharp'

const dir = path.resolve('src/assets/img')
const files = (await readdir(dir)).filter((f) => /\.jpe?g$/i.test(f))
let totalBefore = 0
let totalAfter = 0
for (const file of files) {
  const src = path.join(dir, file)
  const dst = path.join(dir, file.replace(/\.jpe?g$/i, '.webp'))
  // 卡片最大显示宽约 800px（2x 屏 1600 内）：超宽源图先缩到 1280 再压，
  // 否则 WebP 只省编码效率、省不掉多余像素
  await sharp(src).resize({ width: 1280, withoutEnlargement: true }).webp({ quality: 68 }).toFile(dst)
  const before = (await stat(src)).size
  const after = (await stat(dst)).size
  totalBefore += before
  totalAfter += after
  console.log(`${file}: ${(before / 1024).toFixed(0)}KB -> ${(after / 1024).toFixed(0)}KB`)
}
console.log(`total: ${(totalBefore / 1024).toFixed(0)}KB -> ${(totalAfter / 1024).toFixed(0)}KB (-${(100 - (totalAfter / totalBefore) * 100).toFixed(0)}%)`)
