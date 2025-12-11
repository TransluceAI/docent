'use client';

import { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { Download, Loader2 } from 'lucide-react';

export type DownloadMenuOption = {
  key: string;
  label: string;
  onSelect: () => void | Promise<void>;
  disabled?: boolean;
  icon?: ReactNode;
};

interface DownloadMenuProps {
  options: DownloadMenuOption[];
  isLoading?: boolean;
  triggerDisabled?: boolean;
  align?: 'start' | 'center' | 'end';
  buttonLabel?: string;
  className?: string;
  contentClassName?: string;
  size?: 'default' | 'sm' | 'lg';
  variant?:
    | 'default'
    | 'destructive'
    | 'outline'
    | 'secondary'
    | 'ghost'
    | 'link';
}

const DownloadMenu = ({
  options,
  isLoading = false,
  triggerDisabled = false,
  align = 'end',
  buttonLabel = 'Download',
  className,
  contentClassName,
  size = 'sm',
  variant = 'outline',
}: DownloadMenuProps) => {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={variant}
          size={size}
          className={cn('h-8 gap-1 text-xs', className)}
          disabled={triggerDisabled || isLoading}
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          <span>{buttonLabel}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={align}
        className={cn('w-40', contentClassName)}
      >
        {options.map((option) => (
          <DropdownMenuItem
            key={option.key}
            className="text-xs"
            disabled={option.disabled}
            onSelect={(event) => {
              event.preventDefault();
              option.onSelect();
            }}
          >
            <div className="flex items-center gap-2">
              {option.icon}
              <span>{option.label}</span>
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default DownloadMenu;
