'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  useAddOrganizationMemberMutation,
  useGetMyOrganizationsQuery,
  useGetOrganizationMembersQuery,
  useRemoveOrganizationMemberMutation,
  useUpdateOrganizationMemberRoleMutation,
  type OrganizationRole,
} from '@/app/api/orgApi';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ArrowLeft } from 'lucide-react';
import { toast } from '@/hooks/use-toast';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';

const ROLE_LABELS: Record<OrganizationRole, string> = {
  member: 'Member',
  admin: 'Admin',
};

export default function OrganizationDetailPage() {
  const params = useParams<{ org_id: string }>();
  const orgId = params.org_id;

  const { data: organizations } = useGetMyOrganizationsQuery();
  const org = organizations?.find((o) => o.id === orgId);
  const isAdmin = org?.my_role === 'admin';

  const { data: members, isLoading } = useGetOrganizationMembersQuery(orgId);
  const [addMember] = useAddOrganizationMemberMutation();
  const [removeMember] = useRemoveOrganizationMemberMutation();
  const [updateRole] = useUpdateOrganizationMemberRoleMutation();

  const [email, setEmail] = useState('');
  const [newRole, setNewRole] = useState<OrganizationRole>('member');

  const sortedMembers = useMemo(() => {
    if (!members) return [];
    return [...members].sort((a, b) =>
      a.user.email.localeCompare(b.user.email)
    );
  }, [members]);

  const onAdd = async () => {
    const trimmed = email.trim();
    if (!trimmed) return;
    try {
      await addMember({ orgId, email: trimmed, role: newRole }).unwrap();
      toast({ title: 'Member added', description: trimmed });
      setEmail('');
      setNewRole('member');
    } catch (err: unknown) {
      const parsed = getRtkQueryErrorMessage(err, 'Failed to add member.');
      toast({
        title: 'Error',
        description: parsed.message,
        variant: 'destructive',
      });
    }
  };

  const onChangeRole = async (memberUserId: string, role: OrganizationRole) => {
    try {
      await updateRole({ orgId, memberUserId, role }).unwrap();
    } catch (err: unknown) {
      const parsed = getRtkQueryErrorMessage(err, 'Failed to update role.');
      toast({
        title: 'Error',
        description: parsed.message,
        variant: 'destructive',
      });
    }
  };

  const onRemove = async (memberUserId: string, memberEmail: string) => {
    try {
      await removeMember({ orgId, memberUserId }).unwrap();
      toast({ title: 'Member removed', description: memberEmail });
    } catch (err: unknown) {
      const parsed = getRtkQueryErrorMessage(err, 'Failed to remove member.');
      toast({
        title: 'Error',
        description: parsed.message,
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="p-3 space-y-3">
      <div className="space-y-1">
        <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
          <Link href="/settings/organizations">
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back to Organizations
          </Link>
        </Button>
        <h2 className="text-xl font-semibold">{org?.name || 'Organization'}</h2>
        <div className="text-sm text-muted-foreground">
          {org?.description ||
            'Manage members and roles for this organization.'}
        </div>
      </div>

      <Card className="p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="font-medium">Members</div>
          <div className="text-xs text-muted-foreground">
            Your role:{' '}
            <span className="capitalize">{org?.my_role || 'member'}</span>
          </div>
        </div>

        {isAdmin ? (
          <div className="flex items-center gap-2">
            <Input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email address"
            />
            <Select
              value={newRole}
              onValueChange={(v) => setNewRole(v as OrganizationRole)}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">{ROLE_LABELS.member}</SelectItem>
                <SelectItem value="admin">{ROLE_LABELS.admin}</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={onAdd} disabled={!email.trim()}>
              Add
            </Button>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            You don’t have permission to add or edit members.
          </div>
        )}

        <div className="border-t" />

        {isLoading ? (
          <div className="text-sm text-muted-foreground">Loading members…</div>
        ) : sortedMembers.length ? (
          <div className="space-y-2">
            {sortedMembers.map((m) => (
              <div
                key={m.user.id}
                className="flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {m.user.email}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Select
                    value={m.role}
                    onValueChange={(v) =>
                      onChangeRole(m.user.id, v as OrganizationRole)
                    }
                    disabled={!isAdmin}
                  >
                    <SelectTrigger className="w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="member">
                        {ROLE_LABELS.member}
                      </SelectItem>
                      <SelectItem value="admin">{ROLE_LABELS.admin}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!isAdmin}
                    onClick={() => onRemove(m.user.id, m.user.email)}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">No members found.</div>
        )}
      </Card>
    </div>
  );
}
