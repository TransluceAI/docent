import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface ToastNotification {
  title: string;
  description: string;
  variant?: 'default' | 'destructive';
}

export interface ToastState {
  toastNotification?: ToastNotification;
}

const initialState: ToastState = {};

export const toastSlice = createSlice({
  name: 'toast',
  initialState,
  reducers: {
    setToastNotification: (state, action: PayloadAction<ToastNotification>) => {
      state.toastNotification = action.payload;
    },
  },
});

export const { setToastNotification } = toastSlice.actions;

export default toastSlice.reducer;
