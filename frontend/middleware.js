import { NextResponse } from "next/server";

/**
 * Protects all routes except /login.
 * Since JWTs live in localStorage (client-only), we can't read them here,
 * so we use an HttpOnly cookie mirror named `auth_token` set on login
 * — OR fall back to a lightweight check: if the request has no cookie
 * we redirect to /login and let the client re-hydrate.
 *
 * Strategy used here: protect via cookie `auth_token`.
 * On login/register your api.js already sets localStorage; also set a
 * cookie there (see note in api.js patch below).
 */
export function middleware(request) {
  const { pathname } = request.nextUrl;

  // Public routes — never redirect
  const publicRoutes = ["/login"];
  if (publicRoutes.some((r) => pathname.startsWith(r))) {
    return NextResponse.next();
  }

  // Check for auth cookie (set by patched api.js)
  const token = request.cookies.get("auth_token")?.value;
  if (!token) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Run on all routes except Next.js internals and static files
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/).*)"],
};
