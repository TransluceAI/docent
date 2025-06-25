import { redirect } from 'next/navigation';
import { getUser } from '../services/dal';

export default async function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getUser();

  // Redirect if the user is already logged in (non-anonymous)
  if (user && !user.is_anonymous) {
    return redirect('/dashboard');
  } else {
    return children;
  }
}
