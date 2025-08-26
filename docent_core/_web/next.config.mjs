/** @type {import('next').NextConfig} */
const nextConfig = {
  async redirects() {
    return [
      {
        source: '/sample',
        destination:
          'https://docent.transluce.org/dashboard/8831255a-249e-46cc-a600-c27c3d3cbd28?rubricId=e32d434f-168b-4708-af77-095a936ccaf0',
        permanent: false,
      },
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
