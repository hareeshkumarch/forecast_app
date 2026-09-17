const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,

  ...(process.env.DOCKER_BUILD === "1" ? { output: "standalone" } : {}),
  ...(staticExport ? { output: "export", trailingSlash: true, images: { unoptimized: true } } : {}),
  eslint: {
    dirs: ["app", "components", "hooks", "lib", "stores", "types"],
  },
};

export default nextConfig;
