/** Minimal RGB raster + PNG writer (no dependencies) for the mock guide and hero images. */
import { deflateSync } from "node:zlib";

export type RGB = [number, number, number];
type Pt = [number, number];

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function inside(p: Pt, poly: Pt[]): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

export class Raster {
  readonly data: Uint8Array;
  constructor(readonly width: number, readonly height: number, bg: RGB = [255, 255, 255]) {
    this.data = new Uint8Array(width * height * 3);
    this.fillRect(0, 0, width, height, bg);
  }

  set(x: number, y: number, c: RGB, alpha = 1) {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return;
    const i = (y * this.width + x) * 3;
    for (let k = 0; k < 3; k++) this.data[i + k] = Math.round(this.data[i + k] * (1 - alpha) + c[k] * alpha);
  }

  fillRect(x0: number, y0: number, w: number, h: number, c: RGB, alpha = 1) {
    for (let y = Math.max(0, Math.floor(y0)); y < Math.min(this.height, y0 + h); y++)
      for (let x = Math.max(0, Math.floor(x0)); x < Math.min(this.width, x0 + w); x++) this.set(x, y, c, alpha);
  }

  /** Vertical gradient from `top` to `bottom`. */
  gradient(top: RGB, bottom: RGB) {
    for (let y = 0; y < this.height; y++) {
      const t = y / (this.height - 1);
      const c: RGB = [0, 1, 2].map((k) => top[k] + (bottom[k] - top[k]) * t) as RGB;
      for (let x = 0; x < this.width; x++) this.set(x, y, c);
    }
  }

  fillPolygon(poly: Pt[], c: RGB, alpha = 1) {
    const xs = poly.map((p) => p[0]);
    const ys = poly.map((p) => p[1]);
    for (let y = Math.max(0, Math.floor(Math.min(...ys))); y <= Math.min(this.height - 1, Math.ceil(Math.max(...ys))); y++)
      for (let x = Math.max(0, Math.floor(Math.min(...xs))); x <= Math.min(this.width - 1, Math.ceil(Math.max(...xs))); x++)
        if (inside([x + 0.5, y + 0.5], poly)) this.set(x, y, c, alpha);
  }

  toPng(): Buffer {
    const stride = this.width * 3;
    const raw = Buffer.alloc((stride + 1) * this.height);
    for (let y = 0; y < this.height; y++) {
      raw[y * (stride + 1)] = 0; // filter: none
      Buffer.from(this.data.buffer, y * stride, stride).copy(raw, y * (stride + 1) + 1);
    }
    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(this.width, 0);
    ihdr.writeUInt32BE(this.height, 4);
    ihdr[8] = 8; // bit depth
    ihdr[9] = 2; // color type: RGB
    return Buffer.concat([
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
      chunk("IHDR", ihdr),
      chunk("IDAT", deflateSync(raw)),
      chunk("IEND", Buffer.alloc(0)),
    ]);
  }
}
