import { NextRequest, NextResponse } from 'next/server';
import { getUser } from './app/services/dal';
import { INTERNAL_BASE_URL } from './app/constants';

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // Check if cookies already have a user associated
  let user = await getUser();

  // If not, we might be able to create an anonymous session, if the path contains a fg_id
  if (!user) {
    const isFgRoute = pathname.match(
      /^\/dashboard\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\/.*)?$/i
    );
    if (isFgRoute) {
      // Create an anonymous session
      const anonResponse = await fetch(
        `${INTERNAL_BASE_URL}/rest/anonymous_session`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        }
      );
      user = await anonResponse.json();

      // Get the set-cookie header from the anonymous session response
      const setCookie = anonResponse.headers.get('set-cookie');

      // Create a new response with the cookie and user data in *request* headers
      // This is necessary for the server-side auth check in layout.tsx to work
      const response = NextResponse.next({
        request: {
          headers: new Headers({
            ...request.headers,
            'x-middleware-user': JSON.stringify(user),
            'x-middleware-cookies': setCookie || '',
          }),
        },
      });

      // Also set the *response* headers so the cookie is sent to the client
      if (setCookie) response.headers.set('set-cookie', setCookie);

      return response;
    }
  }

  // At this point, if there is no user, we need to redirect to login
  if (!user) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*'],
};
