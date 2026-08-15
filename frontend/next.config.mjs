
// Three build shapes, one config:
//
//   (default)        Vercel / `next start` — Next picks the output itself
//   DOCKER_BUILD=1   standalone server bundle, for the Dockerfile
//   STATIC_EXPORT=1  plain HTML/JS in out/, for S3 + CloudFront
//
// The static export is possible because every page here is a shell that fetches
// from the API in the browser: no route handlers, no middleware, no server-side
// rendering of customer data. `trailingSlash` makes each route a directory with
// its own index.html, which is what S3 needs to serve /dashboard without a
// Lambda@Edge rewrite.
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,

  // "standalone" is needed for Docker, but Vercel handles output natively.
  ...(process.env.DOCKER_BUILD === "1" ? { output: "standalone" } : {}),
  ...(staticExport ? { output: "export", trailingSlash: true, images: { unoptimized: true } } : {}),
  eslint: {
    dirs: ["app", "components", "hooks", "lib", "stores", "types"],
  },
};

export default nextConfig;
