'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Copy, Trash2 } from 'lucide-react';
import { toast } from '@/hooks/use-toast';
import { apiRestClient } from '@/app/services/apiService';

interface ApiKey {
  id: string;
  name: string;
  created_at: string;
  disabled_at: string | null;
  last_used_at: string | null;
  is_active: boolean;
}

interface CreateApiKeyResponse {
  id: string;
  name: string;
  api_key: string;
  created_at: string;
}

export default function ApiKeysPage() {
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newlyCreatedKey, setNewlyCreatedKey] =
    useState<CreateApiKeyResponse | null>(null);

  const fetchApiKeys = async () => {
    try {
      const response = await apiRestClient.get('/api-keys');
      setApiKeys(response.data);
    } catch (error) {
      console.error('Failed to fetch API keys:', error);
      toast({
        title: 'Error',
        description: 'Failed to load API keys',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchApiKeys();
  }, []);

  const handleCreateApiKey = async () => {
    if (!newKeyName.trim()) return;

    setIsCreating(true);
    try {
      const response = await apiRestClient.post('/api-keys', {
        name: newKeyName.trim(),
      });
      const newKey: CreateApiKeyResponse = response.data;

      setNewlyCreatedKey(newKey);
      setNewKeyName('');
      setIsCreateDialogOpen(false);
      await fetchApiKeys();

      toast({
        title: 'API Key Created',
        description:
          'Your new API key has been created. Make sure to copy it now!',
      });
    } catch (error) {
      console.error('Failed to create API key:', error);
      toast({
        title: 'Error',
        description: 'Failed to create API key',
        variant: 'destructive',
      });
    } finally {
      setIsCreating(false);
    }
  };

  const handleDisableApiKey = async (keyId: string) => {
    try {
      await apiRestClient.delete(`/api-keys/${keyId}`);
      await fetchApiKeys();
      toast({
        title: 'API Key Disabled',
        description: 'The API key has been disabled successfully',
      });
    } catch (error) {
      console.error('Failed to disable API key:', error);
      toast({
        title: 'Error',
        description: 'Failed to disable API key',
        variant: 'destructive',
      });
    }
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast({
        title: 'Copied',
        description: 'API key copied to clipboard',
      });
    } catch (error) {
      console.error('Failed to copy to clipboard:', error);
      toast({
        title: 'Copy Failed',
        description:
          'Failed to copy API key to clipboard. Please copy manually.',
        variant: 'destructive',
      });
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString();
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">Docent API Keys</h1>
          <p className="text-muted-foreground">
            Manage your API keys for programmatic access to Docent
          </p>
        </div>

        <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
          <DialogTrigger asChild>
            <Button>Create API Key</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New API Key</DialogTitle>
              <DialogDescription>
                Give your API key a descriptive name to help you identify it
                later.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label htmlFor="keyName">API Key Name</Label>
                <Input
                  id="keyName"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g., Production Server, Local Development"
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setIsCreateDialogOpen(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreateApiKey}
                disabled={isCreating || !newKeyName.trim()}
              >
                {isCreating ? 'Creating...' : 'Create API Key'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {newlyCreatedKey && (
        <Card className="border-green-border bg-green-bg">
          <CardHeader>
            <CardTitle className="text-green-text">
              API Key Created Successfully!
            </CardTitle>
            <CardDescription className="text-green-text">
              Make sure to copy your API key now. You won&apos;t be able to see
              it again.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center space-x-2">
              <span className="font-mono flex items-center justify-start pl-2 text-sm border border-primary rounded w-full h-7">
                {newlyCreatedKey.api_key}
              </span>
              <div className="flex flex-row gap-2 items-center">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7"
                  onClick={() => setNewlyCreatedKey(null)}
                >
                  I&apos;ve copied the key
                </Button>
                <Button
                  size="sm"
                  className="h-7 w-7 !p-0"
                  onClick={() => copyToClipboard(newlyCreatedKey.api_key)}
                >
                  <Copy size={11} />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Your API Keys</CardTitle>
          <CardDescription>
            These API keys allow access to the Docent API. Keep them secure.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div>Loading...</div>
          ) : apiKeys.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No API keys found. Create your first API key to get started.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Last Used</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {apiKeys.map((key) => (
                  <TableRow key={key.id} className="h-12">
                    <TableCell className="font-medium">{key.name}</TableCell>
                    <TableCell>
                      <Badge variant={key.is_active ? 'default' : 'secondary'}>
                        {key.is_active ? 'Active' : 'Disabled'}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatDate(key.created_at)}</TableCell>
                    <TableCell>
                      {key.last_used_at
                        ? formatDate(key.last_used_at)
                        : 'Never'}
                    </TableCell>
                    <TableCell>
                      {key.is_active && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleDisableApiKey(key.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
