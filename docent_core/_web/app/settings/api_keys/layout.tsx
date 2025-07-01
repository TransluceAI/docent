import { getUser } from '@/app/services/dal';
import { redirect } from 'next/navigation';
import { headers } from 'next/headers';

export default async function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getUser();

  // If user is either not authenticated or anonymous, redirect to login
  if (!user || user.is_anonymous) {
    const encodedRedirect = encodeURIComponent('/settings/api_keys');
    redirect(`/login?redirect=${encodedRedirect}`);
  }
  return <div>{children}</div>;
}
