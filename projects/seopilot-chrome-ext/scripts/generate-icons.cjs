/**
 * Generate simple PNG icons for the Chrome Extension.
 * Run: node scripts/generate-icons.js
 */

const { writeFileSync, mkdirSync, existsSync } = require("fs");
const { resolve } = require("path");
const { deflateSync } = require("zlib");

const iconsDir = resolve(__dirname, "../src/icons");

if (!existsSync(iconsDir)) {
  mkdirSync(iconsDir, { recursive: true });
}

function isInS(x, y) {
  const thickness = 0.15;
  if (y >= -0.6 && y <= -0.25) {
    const dist = Math.sqrt(x ** 2 + (y + 0.425) ** 2);
    if (Math.abs(dist - 0.25) < thickness && x > -0.15) return true;
  }
  if (y >= -0.15 && y <= 0.15 && x >= -0.25 && x <= 0.25) {
    if (Math.abs(y) < thickness / 2) return true;
  }
  if (y >= 0.25 && y <= 0.6) {
    const dist = Math.sqrt(x ** 2 + (y - 0.425) ** 2);
    if (Math.abs(dist - 0.25) < thickness && x < 0.15) return true;
  }
  if (y >= -0.65 && y <= -0.5 && x >= -0.25 && x <= 0.25) return true;
  if (y >= 0.5 && y <= 0.65 && x >= -0.25 && x <= 0.25) return true;
  return false;
}

function crc32(data) {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function createChunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeBuffer = Buffer.from(type, "ascii");
  const crcData = Buffer.concat([typeBuffer, data]);
  const crcBuffer = Buffer.alloc(4);
  crcBuffer.writeUInt32BE(crc32(crcData), 0);
  return Buffer.concat([length, typeBuffer, data, crcBuffer]);
}

function createPng(size) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(size, 0);
  ihdrData.writeUInt32BE(size, 4);
  ihdrData.writeUInt8(8, 8);
  ihdrData.writeUInt8(2, 9);
  ihdrData.writeUInt8(0, 10);
  ihdrData.writeUInt8(0, 11);
  ihdrData.writeUInt8(0, 12);
  const ihdr = createChunk("IHDR", ihdrData);

  const rowSize = 1 + size * 3;
  const rawData = Buffer.alloc(rowSize * size);
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 1;

  for (let y = 0; y < size; y++) {
    const ro = y * rowSize;
    rawData[ro] = 0;
    for (let x = 0; x < size; x++) {
      const po = ro + 1 + x * 3;
      const dist = Math.sqrt((x - cx) ** 2 + (y - cy) ** 2);
      if (dist <= r) {
        const t = dist / r;
        rawData[po] = Math.round(59 - t * 30);
        rawData[po + 1] = Math.round(130 - t * 52);
        rawData[po + 2] = Math.round(246 - t * 30);
        const relX = (x - cx) / r;
        const relY = (y - cy) / r;
        if (isInS(relX, relY)) {
          rawData[po] = 255;
          rawData[po + 1] = 255;
          rawData[po + 2] = 255;
        }
      } else {
        rawData[po] = 255;
        rawData[po + 1] = 255;
        rawData[po + 2] = 255;
      }
    }
  }

  const compressed = deflateSync(rawData);
  const idat = createChunk("IDAT", compressed);
  const iend = createChunk("IEND", Buffer.alloc(0));
  return Buffer.concat([signature, ihdr, idat, iend]);
}

for (const size of [16, 32, 48, 128]) {
  const png = createPng(size);
  const path = resolve(iconsDir, `icon${size}.png`);
  writeFileSync(path, png);
  console.log(`Generated ${path} (${png.length} bytes)`);
}

console.log("Done!");
