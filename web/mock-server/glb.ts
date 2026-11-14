/**
 * Tiny glTF 2.0 (.glb) box writer so the mock server can serve placeholder furniture
 * without any binary files in git. Box is centered on x/z, sits on y = 0 (floor), and
 * is `w` wide (x), `h` tall (y) and `d` deep (z). Real models come from Yared's assets/glb.
 */

type Vec3 = [number, number, number];

export function buildBoxGlb(w: number, h: number, d: number, rgb: Vec3): Buffer {
  const x = w / 2;
  const z = d / 2;
  // [normal, 4 corners counter-clockwise seen from outside]
  const faces: [Vec3, Vec3[]][] = [
    [[0, 0, 1], [[-x, 0, z], [x, 0, z], [x, h, z], [-x, h, z]]],
    [[0, 0, -1], [[x, 0, -z], [-x, 0, -z], [-x, h, -z], [x, h, -z]]],
    [[1, 0, 0], [[x, 0, z], [x, 0, -z], [x, h, -z], [x, h, z]]],
    [[-1, 0, 0], [[-x, 0, -z], [-x, 0, z], [-x, h, z], [-x, h, -z]]],
    [[0, 1, 0], [[-x, h, z], [x, h, z], [x, h, -z], [-x, h, -z]]],
    [[0, -1, 0], [[-x, 0, -z], [x, 0, -z], [x, 0, z], [-x, 0, z]]],
  ];

  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  faces.forEach(([n, corners], f) => {
    corners.forEach((c) => {
      positions.push(...c);
      normals.push(...n);
    });
    const o = f * 4;
    indices.push(o, o + 1, o + 2, o, o + 2, o + 3);
  });

  const posBuf = Buffer.from(new Float32Array(positions).buffer);
  const normBuf = Buffer.from(new Float32Array(normals).buffer);
  const idxBuf = Buffer.from(new Uint16Array(indices).buffer);
  const bin = Buffer.concat([posBuf, normBuf, idxBuf]);

  const json = {
    asset: { version: "2.0", generator: "hestia-mock" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1 }, indices: 2, material: 0 }] }],
    materials: [
      { pbrMetallicRoughness: { baseColorFactor: [...rgb, 1], metallicFactor: 0, roughnessFactor: 0.8 } },
    ],
    accessors: [
      { bufferView: 0, componentType: 5126, count: 24, type: "VEC3", min: [-x, 0, -z], max: [x, h, z] },
      { bufferView: 1, componentType: 5126, count: 24, type: "VEC3" },
      { bufferView: 2, componentType: 5123, count: 36, type: "SCALAR" },
    ],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: posBuf.length, target: 34962 },
      { buffer: 0, byteOffset: posBuf.length, byteLength: normBuf.length, target: 34962 },
      { buffer: 0, byteOffset: posBuf.length + normBuf.length, byteLength: idxBuf.length, target: 34963 },
    ],
    buffers: [{ byteLength: bin.length }],
  };

  let jsonStr = JSON.stringify(json);
  while (Buffer.byteLength(jsonStr) % 4 !== 0) jsonStr += " ";
  const jsonBuf = Buffer.from(jsonStr);
  const binPad = (4 - (bin.length % 4)) % 4;
  const binBuf = Buffer.concat([bin, Buffer.alloc(binPad)]);

  const total = 12 + 8 + jsonBuf.length + 8 + binBuf.length;
  const header = Buffer.alloc(12);
  header.write("glTF", 0, "ascii");
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(total, 8);
  const jsonHead = Buffer.alloc(8);
  jsonHead.writeUInt32LE(jsonBuf.length, 0);
  jsonHead.write("JSON", 4, "ascii");
  const binHead = Buffer.alloc(8);
  binHead.writeUInt32LE(binBuf.length, 0);
  binHead.write("BIN\0", 4, "latin1");

  return Buffer.concat([header, jsonHead, jsonBuf, binHead, binBuf]);
}
