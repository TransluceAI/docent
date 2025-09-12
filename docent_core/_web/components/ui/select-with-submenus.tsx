'use client';

import { CaretSortIcon, CheckIcon } from '@radix-ui/react-icons';
import * as React from 'react';

import { cn } from '@/lib/utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';

export interface SelectWithSubmenusProps {
  selectedKey: string | null;
  onChange: (key: string | null) => void;
  selectedLabel?: string;
  allowNone?: boolean;
  noneLabel?: string;
  disabled?: boolean;
  className?: string;
  children?: React.ReactNode;
}

type SelectWithSubmenusContextValue = {
  selectedKey: string | null;
  onChange: (key: string | null) => void;
};

const SelectWithSubmenusContext =
  React.createContext<SelectWithSubmenusContextValue | null>(null);

export function useSelectWithSubmenus() {
  const ctx = React.useContext(SelectWithSubmenusContext);
  if (!ctx) {
    throw new Error(
      'useSelectWithSubmenus must be used within <SelectWithSubmenus>'
    );
  }
  return ctx;
}

export function SelectWithSubmenus({
  selectedKey,
  onChange,
  selectedLabel,
  allowNone = true,
  noneLabel = 'None',
  disabled = false,
  className,
  children,
}: SelectWithSubmenusProps) {
  const triggerLabel = React.useMemo(() => {
    if (selectedLabel) return selectedLabel;
    if (selectedKey === null) return noneLabel;
    return selectedKey;
  }, [selectedLabel, selectedKey, noneLabel]);

  const contextValue = React.useMemo(
    () => ({ selectedKey, onChange }),
    [selectedKey, onChange]
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          className={cn(
            'flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1',
            'truncate text-left',
            className
          )}
          title={triggerLabel}
        >
          <span className="truncate w-full">{triggerLabel}</span>
          <CaretSortIcon className="h-4 w-4 opacity-50" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" enableScrolling={true}>
        <SelectWithSubmenusContext.Provider value={contextValue}>
          {allowNone && (
            <DropdownMenuItem
              className="text-xs cursor-default relative"
              onClick={() => onChange(null)}
              aria-checked={selectedKey === null}
            >
              {noneLabel}
              {selectedKey === null && (
                <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
                  <CheckIcon className="h-4 w-4" />
                </span>
              )}
            </DropdownMenuItem>
          )}
          {children}
        </SelectWithSubmenusContext.Provider>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default SelectWithSubmenus;

// Composable helpers
type DropdownMenuItemProps = React.ComponentPropsWithoutRef<
  typeof DropdownMenuItem
> & {
  value: string;
};

export const SelectWithSubmenusItem = React.forwardRef<
  React.ElementRef<typeof DropdownMenuItem>,
  DropdownMenuItemProps
>(({ className, value, onClick, children, ...props }, ref) => {
  const { selectedKey, onChange } = useSelectWithSubmenus();
  const isSelected = selectedKey === value;

  return (
    <DropdownMenuItem
      ref={ref}
      className={cn('text-xs cursor-default relative', className)}
      onClick={(e) => {
        onChange(value);
        onClick?.(e);
      }}
      aria-checked={isSelected}
      {...props}
    >
      {children}
      {isSelected && (
        <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
          <CheckIcon className="h-4 w-4" />
        </span>
      )}
    </DropdownMenuItem>
  );
});
SelectWithSubmenusItem.displayName = 'SelectWithSubmenusItem';

// Re-export submenu primitives for convenience
export const SelectWithSubmenusSub = DropdownMenuSub;
export const SelectWithSubmenusSubTrigger = DropdownMenuSubTrigger;
export const SelectWithSubmenusLabel = DropdownMenuLabel;
export const SelectWithSubmenusSeparator = DropdownMenuSeparator;

// Re-export submenu content with scrolling enabled by default
export const SelectWithSubmenusSubContent = React.forwardRef<
  React.ElementRef<typeof DropdownMenuSubContent>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuSubContent>
>(({ ...props }, ref) => (
  <DropdownMenuSubContent ref={ref} enableScrolling={true} {...props} />
));
SelectWithSubmenusSubContent.displayName = 'SelectWithSubmenusSubContent';
