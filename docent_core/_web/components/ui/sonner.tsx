'use client';

import { useTheme } from 'next-themes';
import { Toaster as Sonner } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

const toastClassNames = {
  toast:
    'group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg',
  description: 'group-[.toast]:text-muted-foreground',
  actionButton:
    'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground',
  cancelButton: 'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground',
};

/** Transient toasts (top-right) - for temporary notifications */
const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = 'system' } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps['theme']}
      className="toaster group"
      position="top-right"
      duration={2000}
      closeButton
      toastOptions={{ classNames: toastClassNames }}
      {...props}
    />
  );
};

/** Persistent toasts (bottom-right) - for banners that require user action */
export const PERSISTENT_TOASTER_ID = 'persistent';

const PersistentToaster = ({ ...props }: ToasterProps) => {
  const { theme = 'system' } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps['theme']}
      className="toaster group"
      position="bottom-right"
      expand
      id={PERSISTENT_TOASTER_ID}
      toastOptions={{ classNames: toastClassNames }}
      {...props}
    />
  );
};

export { Toaster, PersistentToaster };
