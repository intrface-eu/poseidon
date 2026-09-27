import type { NextConfig } from "next";
import path from "node:path";

const monorepoRoot = path.resolve(__dirname, "../..");
const nextConfig: NextConfig = {
  turbopack: { root: monorepoRoot },
  outputFileTracingRoot: monorepoRoot,
  agentRules: false,
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
