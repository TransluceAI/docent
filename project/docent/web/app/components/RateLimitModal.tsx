'use client';

import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useFrameGrid } from '../contexts/FrameGridContext';
import { AlertCircle } from 'lucide-react';

export function RateLimitModal() {
  const { isRateLimited, setIsRateLimited, setIsApiKeyModalOpen } =
    useFrameGrid();

  const handleOpenApiKeyModal = () => {
    setIsRateLimited(false);
    setIsApiKeyModalOpen(true);
  };

  return (
    <Dialog open={isRateLimited} onOpenChange={setIsRateLimited}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-1.5">
            <AlertCircle className="h-4 w-4 text-red-500" />
            <DialogTitle className="text-sm font-semibold text-gray-800">
              Rate Limit Reached
            </DialogTitle>
          </div>
        </DialogHeader>
        <div className="flex flex-col space-y-2">
          <p className="text-xs text-gray-600">
            Our demo is currently experiencing high traffic, and our server has
            hit API rate limits. We appreciate the enthusiasm, and we&apos;re
            working on getting rate limits lifted!
          </p>
          <p className="text-xs text-gray-600">
            In the meantime, you can either:
          </p>
          <ul className="text-xs text-gray-600 list-disc pl-4 space-y-1">
            <li>Wait a few minutes and try again</li>
            <li>Enter your own API keys to bypass our shared limits</li>
          </ul>
        </div>
        <DialogFooter className="flex sm:justify-end gap-1.5 mt-2">
          <Button
            variant="outline"
            className="text-xs h-8 px-3"
            onClick={() => setIsRateLimited(false)}
          >
            Close
          </Button>
          <Button
            variant="default"
            className="text-xs h-8 px-3"
            onClick={handleOpenApiKeyModal}
          >
            Enter API Keys
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
