
const nextConfig = {
  reactStrictMode: true,
  
  output: "standalone",
  eslint: {
    dirs: ["app", "components", "hooks", "lib", "stores", "types"],
  },
};

export default nextConfig;
