import type { NextConfig } from "next";

const tileBackend =
  process.env.TILE_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/tiles/base/:z/:x/:y.pbf",
        destination: `${tileBackend}/tiles/base/:z/:x/:y.pbf`,
      },
      {
        source: "/tiles/traffic/:z/:x/:y.pbf",
        destination: `${tileBackend}/tiles/traffic/:z/:x/:y.pbf`,
      },
    ];
  },
};

export default nextConfig;
