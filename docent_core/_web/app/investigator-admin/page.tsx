/**
 * Admin page for managing investigator authorized users.
 * Only accessible to hardcoded admin emails.
 *
 * http://localhost:3001/investigator-admin
 */

'use client';

import { ModeToggle } from '@/components/ui/theme-toggle';
import { PlusIcon, TrashIcon, UsersIcon } from 'lucide-react';
import React, { useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { toast } from '@/hooks/use-toast';

import { UserProfile } from '../components/auth/UserProfile';
import { useRequireUserContext } from '../contexts/UserContext';
import {
  useGetAuthorizedUsersQuery,
  useAddAuthorizedUserMutation,
  useRemoveAuthorizedUserMutation,
  AuthorizedUser,
} from '../api/investigatorApi';

export default function InvestigatorAdminPage() {
  const { user } = useRequireUserContext();

  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);

  const [isAddUserDialogOpen, setIsAddUserDialogOpen] = useState(false);
  const [newUserEmail, setNewUserEmail] = useState('');

  // RTK Query hooks - try to fetch authorized users to determine admin access
  const {
    data: authorizedUsers,
    isLoading: isLoadingUsers,
    error: usersError,
  } = useGetAuthorizedUsersQuery(undefined, {
    skip: isAdmin === false,
  });
  const [addAuthorizedUser, { isLoading: isAddingUser }] =
    useAddAuthorizedUserMutation();
  const [removeAuthorizedUser, { isLoading: isRemovingUser }] =
    useRemoveAuthorizedUserMutation();

  React.useEffect(() => {
    if (usersError) {
      const error = usersError as any;
      if (error?.status === 403) {
        setIsAdmin(false);
        setAccessError('You are not authorized to access this admin page.');
      } else {
        setIsAdmin(false);
        setAccessError('An error occurred while checking admin access.');
      }
    } else if (authorizedUsers !== undefined) {
      setIsAdmin(true);
      setAccessError(null);
    }
  }, [authorizedUsers, usersError]);

  const handleAddUser = async () => {
    if (!newUserEmail.trim()) {
      toast({
        title: 'Email Required',
        description: 'Please provide an email address',
        variant: 'destructive',
      });
      return;
    }

    try {
      await addAuthorizedUser({ email: newUserEmail }).unwrap();

      setIsAddUserDialogOpen(false);
      setNewUserEmail('');

      toast({
        title: 'User Added',
        description: 'User has been added to the authorized list',
      });
    } catch (error: any) {
      console.error('Failed to add user:', error);
      toast({
        title: 'Error',
        description: error?.data?.detail || 'Failed to add user',
        variant: 'destructive',
      });
    }
  };

  const handleRemoveUser = async (userId: string, email: string) => {
    try {
      await removeAuthorizedUser(userId).unwrap();

      toast({
        title: 'User Removed',
        description: `${email} has been removed from the authorized list`,
      });
    } catch (error: any) {
      console.error('Failed to remove user:', error);
      toast({
        title: 'Error',
        description: error?.data?.detail || 'Failed to remove user',
        variant: 'destructive',
      });
    }
  };

  if (isAdmin === null) {
    return (
      <ScrollArea className="h-screen">
        <div className="container mx-auto py-4 px-3 max-w-screen-xl space-y-3">
          <div className="text-center py-8 text-muted-foreground">
            Checking admin access...
          </div>
        </div>
      </ScrollArea>
    );
  }

  if (isAdmin === false) {
    return (
      <ScrollArea className="h-screen">
        <div className="container mx-auto py-4 px-3 max-w-screen-xl space-y-3">
          <div className="space-y-1 mb-4">
            <div className="flex justify-between items-center">
              <div>
                <div className="text-lg font-semibold tracking-tight">
                  Access Denied
                </div>
                <div className="text-xs text-muted-foreground">
                  {accessError ||
                    'You are not authorized to access this admin page.'}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <ModeToggle />
                <UserProfile />
              </div>
            </div>
          </div>
          <Separator className="my-4" />
          <div className="bg-red-bg border-red-border rounded-sm p-3">
            <div className="flex items-start gap-3">
              <UsersIcon className="h-5 w-5 text-red-text mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <h3 className="font-medium text-sm mb-1 text-red-text">
                  Admin Access Required
                </h3>
                <p className="text-xs text-muted-foreground">
                  This page is only accessible to investigator administrators.
                  Contact an admin if you need access to investigator features.
                </p>
              </div>
            </div>
          </div>
        </div>
      </ScrollArea>
    );
  }

  return (
    <ScrollArea className="h-screen">
      <div className="container mx-auto py-4 px-3 max-w-screen-xl space-y-3">
        {/* Header Section */}
        <div className="space-y-1 mb-4">
          <div className="flex justify-between items-center">
            <div>
              <div className="text-lg font-semibold tracking-tight">
                Investigator Admin
              </div>
              <div className="text-xs text-muted-foreground">
                Manage authorized users for investigator features
              </div>
            </div>
            <div className="flex items-center gap-2">
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      className="flex items-center gap-1 h-7"
                      size="sm"
                      onClick={() => setIsAddUserDialogOpen(true)}
                    >
                      <PlusIcon className="h-3.5 w-3.5" />
                      Add User
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Add a user to the authorized list</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              <ModeToggle />
              <UserProfile />
            </div>
          </div>
        </div>

        <Separator className="my-4" />

        {/* Info banner */}
        <div className="bg-secondary border-border rounded-sm p-3">
          <div className="flex items-start gap-3">
            <UsersIcon className="h-5 w-5 text-muted-foreground mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <h3 className="font-medium text-sm mb-1 text-primary">
                Authorized Users Management
              </h3>
              <p className="text-xs text-muted-foreground mb-3">
                Users in this list are authorized to access investigator
                features. Only users with valid accounts can be added to the
                list.
              </p>
              <div className="text-xs text-muted-foreground">
                <strong>Note:</strong> Users must have an existing account in
                the system before they can be added to the authorized list.
              </div>
            </div>
          </div>
        </div>

        {/* Authorized Users Table */}
        <div className="bg-background border border-border rounded-sm">
          <div className="p-3 border-b border-border">
            <h3 className="font-medium text-sm text-primary">
              Authorized Users ({authorizedUsers?.length || 0})
            </h3>
          </div>
          <div className="p-3">
            {isLoadingUsers ? (
              <div className="text-center py-8 text-muted-foreground">
                Loading authorized users...
              </div>
            ) : !authorizedUsers || authorizedUsers.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No authorized users found. Add users to get started.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Added Date</TableHead>
                    <TableHead className="w-[100px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {authorizedUsers.map((user: AuthorizedUser) => (
                    <TableRow key={user.user_id}>
                      <TableCell className="font-medium">
                        {user.email}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(user.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-7 w-7 p-0"
                                onClick={() =>
                                  handleRemoveUser(user.user_id, user.email)
                                }
                                disabled={isRemovingUser}
                              >
                                <TrashIcon className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>Remove user from authorized list</p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>
      </div>

      {/* Add User Dialog */}
      <Dialog open={isAddUserDialogOpen} onOpenChange={setIsAddUserDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Authorized User</DialogTitle>
            <DialogDescription>
              Add a user to the investigator authorized list by their email
              address. The user must have an existing account.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="user-email">
                Email Address <span className="text-red-text">*</span>
              </Label>
              <Input
                id="user-email"
                type="email"
                value={newUserEmail}
                onChange={(e) => setNewUserEmail(e.target.value)}
                placeholder="user@example.com"
                required
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setIsAddUserDialogOpen(false);
                setNewUserEmail('');
              }}
              disabled={isAddingUser}
            >
              Cancel
            </Button>
            <Button
              onClick={handleAddUser}
              disabled={isAddingUser || !newUserEmail.trim()}
            >
              {isAddingUser ? 'Adding...' : 'Add User'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ScrollArea>
  );
}
