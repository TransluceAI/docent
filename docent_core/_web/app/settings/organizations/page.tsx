import Link from 'next/link';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { getUser } from '@/app/services/dal';
import { INTERNAL_BASE_URL, COOKIE_KEY } from '@/app/constants';
import type { OrganizationWithRole } from '@/app/api/orgApi';
import { Card } from '@/components/ui/card';
import CreateOrganizationDialog from './CreateOrganizationDialog';

async function fetchMyOrganizations(
  cookieValue: string
): Promise<OrganizationWithRole[]> {
  const response = await fetch(`${INTERNAL_BASE_URL}/rest/organizations`, {
    headers: {
      Cookie: `${COOKIE_KEY}=${cookieValue}`,
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
  });

  if (!response.ok) return [];
  return response.json();
}

export default async function OrganizationsIndexPage() {
  const user = await getUser();
  if (!user || user.is_anonymous) {
    redirect(
      '/login?redirect=' + encodeURIComponent('/settings/organizations')
    );
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(COOKIE_KEY);
  if (!sessionCookie?.value) {
    redirect(
      '/login?redirect=' + encodeURIComponent('/settings/organizations')
    );
  }

  const organizations = await fetchMyOrganizations(sessionCookie.value);

  return (
    <div className="p-3 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-semibold">Organizations</h2>
          <p className="text-sm text-muted-foreground">
            Select an organization to manage members.
          </p>
        </div>
        <CreateOrganizationDialog />
      </div>

      {organizations.length ? (
        <div className="grid grid-cols-1 gap-3">
          {organizations.map((org) => (
            <Link
              key={org.id}
              href={`/settings/organizations/${org.id}`}
              className="block"
            >
              <Card className="p-3 space-y-1 hover:bg-secondary">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{org.name}</div>
                    {org.description ? (
                      <div className="text-sm text-muted-foreground truncate">
                        {org.description}
                      </div>
                    ) : null}
                  </div>
                  <div className="text-xs text-muted-foreground capitalize">
                    {org.my_role}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Card className="p-3">
          <div className="text-sm text-muted-foreground">
            You don’t belong to any organizations yet.
          </div>
        </Card>
      )}
    </div>
  );
}
