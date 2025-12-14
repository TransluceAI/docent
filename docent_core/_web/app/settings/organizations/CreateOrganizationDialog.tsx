'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { toast } from '@/hooks/use-toast';
import { useCreateOrganizationMutation } from '@/app/api/orgApi';
import { getRtkQueryErrorMessage } from '@/lib/rtkQueryError';

export default function CreateOrganizationDialog() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [createOrg, { isLoading }] = useCreateOrganizationMutation();

  const handleCreate = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) return;
    try {
      const org = await createOrg({
        name: trimmedName,
        description: description.trim() || undefined,
      }).unwrap();
      toast({ title: 'Organization created', description: org.name });
      setIsOpen(false);
      setName('');
      setDescription('');
      router.push(`/settings/organizations/${org.id}`);
      router.refresh();
    } catch (err: unknown) {
      const parsed = getRtkQueryErrorMessage(
        err,
        'Failed to create organization.'
      );
      toast({
        title: 'Error',
        description: parsed.message,
        variant: 'destructive',
      });
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button>Create Organization</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create New Organization</DialogTitle>
          <DialogDescription>
            Create a new organization and become its first admin.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="orgName">Organization Name</Label>
            <Input
              id="orgName"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Acme Corp, Engineering Team"
            />
          </div>
          <div>
            <Label htmlFor="orgDescription">Description (optional)</Label>
            <Input
              id="orgDescription"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A brief description of your organization"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setIsOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={isLoading || !name.trim()}>
            {isLoading ? 'Creating...' : 'Create Organization'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
