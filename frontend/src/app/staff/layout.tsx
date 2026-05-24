// /staff/* layout — minimal shell that intentionally does NOT mount
// <StaffSessionProvider>. The login page lives under /staff and must
// be reachable when the user has no session; wrapping it in the session
// provider would fire the 401 redirect-loop the moment /api/staff/me/
// returned 401 (which is exactly when the user needs the login form).

export default function StaffLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <>{children}</>;
}
