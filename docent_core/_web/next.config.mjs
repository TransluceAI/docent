/** @type {import('next').NextConfig} */
const nextConfig = {
  async redirects() {
    return [
      {
        source: '/(.*)',
        has: [
          {
            type: 'host',
            value: 'docent-alpha.transluce.org',
          },
        ],
        destination: 'https://docent.transluce.org/$1',
        permanent: true,
      },
    ];
  },
  // Enable standalone output for Docker production builds
  output: 'standalone',
};

export default nextConfig;
