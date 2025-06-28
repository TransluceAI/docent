'use client';

import { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';

import { RootState } from '@/app/store/store';
import { useToast } from '@/hooks/use-toast';

export default function ReduxToastHandler() {
  const dispatch = useDispatch();
  const { toast } = useToast();
  const toastNotification = useSelector(
    (state: RootState) => state.toast.toastNotification
  );

  useEffect(() => {
    if (toastNotification) {
      toast({
        title: toastNotification.title,
        description: toastNotification.description,
        variant: toastNotification.variant,
      });

      // Clear the toast notification from Redux state after displaying it
      //   dispatch(clearToast());
    }
  }, [toastNotification, toast, dispatch]);

  return null; // This component doesn't render anything
}
