import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  const url = request.nextUrl.clone();

  // Check if the URL path starts with /dashboard/docent with or without trailing slash
  if (url.pathname.startsWith('/dashboard/docent')) {
    // Remove /dashboard/docent from the path
    const newPath = url.pathname.replace('/dashboard/docent', '');

    // If the new path is empty, set it to root path
    url.pathname = newPath || '/';

    // Redirect to the new URL
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

// Configure the middleware to run only on specific paths
export const config = {
  matcher: ['/dashboard/docent', '/dashboard/docent/:path*'],
};
