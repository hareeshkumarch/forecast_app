
const nextConfig = {
  reactStrictMode: true,
  
  // "standalone" is needed for Docker, but Vercel handles output natively.
  ...(process.env.DOCKER_BUILD === "1" ? { output: "standalone" } : {}),
  eslint: {
    dirs: ["app", "components", "hooks", "lib", "stores", "types"],
  },
};

export default nextConfig;
