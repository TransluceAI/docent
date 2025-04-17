import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useFrameGrid } from '../contexts/FrameGridContext';
import { toast } from '@/hooks/use-toast';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { KeyRound } from 'lucide-react';

export function ApiKeyModal() {
  const { sendMessage, apiKeys, isApiKeyModalOpen, setIsApiKeyModalOpen } =
    useFrameGrid();
  const [anthropicKey, setAnthropicKey] = useState(apiKeys.anthropic_key || '');
  const [openaiKey, setOpenaiKey] = useState(apiKeys.openai_key || '');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    // Update local state when API keys change
    setAnthropicKey(apiKeys.anthropic_key || '');
    setOpenaiKey(apiKeys.openai_key || '');
  }, [apiKeys]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      sendMessage('set_api_keys', {
        anthropic_key: anthropicKey || undefined,
        openai_key: openaiKey || undefined,
      });
      setIsApiKeyModalOpen(false);
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to update API keys',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={isApiKeyModalOpen} onOpenChange={setIsApiKeyModalOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-1.5">
            <KeyRound className="h-4 w-4 text-blue-500" />
            <DialogTitle className="text-sm font-semibold text-gray-800">
              API Key Management
            </DialogTitle>
          </div>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="flex flex-col space-y-2">
            <p className="text-xs text-gray-600">
              Enter your API keys below to use your own accounts for API calls.
              This can help bypass rate limits and ensure uninterrupted service.
            </p>
            <div className="space-y-1">
              <Label htmlFor="anthropic-key" className="text-xs">
                Anthropic API Key
              </Label>
              <Input
                id="anthropic-key"
                type="password"
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
                placeholder="Enter your Anthropic API key"
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="openai-key" className="text-xs">
                OpenAI API Key
              </Label>
              <Input
                id="openai-key"
                type="password"
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder="Enter your OpenAI API key"
                className="h-8 text-xs"
              />
            </div>
          </div>
          <DialogFooter className="flex sm:justify-end gap-1.5 mt-2">
            <Button
              type="button"
              variant="outline"
              className="text-xs h-8 px-3"
              onClick={() => setIsApiKeyModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isLoading}
              className="text-xs h-8 px-3"
            >
              {isLoading ? 'Saving...' : 'Save API Keys'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// Keep the original component for backward compatibility
export function ApiKeyManager() {
  const { sendMessage, apiKeys } = useFrameGrid();
  const [anthropicKey, setAnthropicKey] = useState(apiKeys.anthropic_key || '');
  const [openaiKey, setOpenaiKey] = useState(apiKeys.openai_key || '');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    // Update local state when API keys change
    setAnthropicKey(apiKeys.anthropic_key || '');
    setOpenaiKey(apiKeys.openai_key || '');
  }, [apiKeys]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      sendMessage('set_api_keys', {
        anthropic_key: anthropicKey || undefined,
        openai_key: openaiKey || undefined,
      });
      toast({
        title: 'Success',
        description: 'API keys updated successfully',
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to update API keys',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4 border rounded-lg">
      <div className="space-y-2">
        <Label htmlFor="anthropic-key">Anthropic API Key</Label>
        <Input
          id="anthropic-key"
          type="password"
          value={anthropicKey}
          onChange={(e) => setAnthropicKey(e.target.value)}
          placeholder="Enter your Anthropic API key"
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="openai-key">OpenAI API Key</Label>
        <Input
          id="openai-key"
          type="password"
          value={openaiKey}
          onChange={(e) => setOpenaiKey(e.target.value)}
          placeholder="Enter your OpenAI API key"
        />
      </div>
      <Button type="submit" disabled={isLoading}>
        {isLoading ? 'Saving...' : 'Save API Keys'}
      </Button>
    </form>
  );
}
