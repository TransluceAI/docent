'use client';

import { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { toast } from 'sonner';

import { RootState } from '@/app/store/store';

export default function ReduxToastHandler() {
  const toastNotification = useSelector(
    (state: RootState) => state.toast.toastNotification
  );

  useEffect(() => {
    if (toastNotification) {
      const message = toastNotification.description || toastNotification.title;
      if (toastNotification.variant === 'destructive') {
        toast.error(message);
      } else {
        toast.success(message);
      }
    }
  }, [toastNotification]);

  return null;
}
