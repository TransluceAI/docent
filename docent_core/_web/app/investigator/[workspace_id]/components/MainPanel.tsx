'use client';

import React from 'react';

interface MainPanelProps {
  children?: React.ReactNode;
}

export default function MainPanel({ children }: MainPanelProps) {
  return (
    <div className="flex-1 custom-scrollbar overflow-y-auto">
      <div>
        {children || (
          <div className="flex items-center justify-center h-96 border-2 border-dashed rounded-lg">
            <p className="text-muted-foreground">Main content area</p>
          </div>
        )}
      </div>
    </div>
  );
}
