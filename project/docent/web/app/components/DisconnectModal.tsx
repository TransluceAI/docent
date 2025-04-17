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
import { WifiOff, RefreshCw, Unplug } from 'lucide-react';

export function DisconnectModal() {
  const { showDisconnectModal, setShowDisconnectModal } = useFrameGrid();

  const handleRefresh = () => {
    window.location.reload();
  };

  return (
    <Dialog open={showDisconnectModal} onOpenChange={setShowDisconnectModal}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-1.5">
            <Unplug className="h-4 w-4 text-red-500" />
            <DialogTitle className="text-sm font-semibold text-gray-800">
              Session disconnected
            </DialogTitle>
          </div>
        </DialogHeader>
        <div className="flex flex-col space-y-2">
          <p className="text-xs text-gray-600">
            Docent has disconnected from the server due to inactivity, so your
            last request didn&apos;t go through.
          </p>
          <p className="text-xs text-gray-600">
            Please refresh the page to reconnect!
          </p>
        </div>

        <DialogFooter className="flex sm:justify-end gap-1.5 mt-2">
          <Button
            variant="outline"
            className="text-xs h-8 px-3"
            onClick={() => setShowDisconnectModal(false)}
          >
            Dismiss
          </Button>
          <Button
            variant="default"
            onClick={handleRefresh}
            className="flex items-center gap-1.5 text-xs h-8 px-3"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh Page
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
