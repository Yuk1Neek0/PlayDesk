/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a standalone server bundle so the Docker image can run `node server.js`.
  output: "standalone",
};

export default nextConfig;
