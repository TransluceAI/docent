// store.ts

import { configureStore, isRejectedWithValue } from '@reduxjs/toolkit';
import experimentViewerReducer from './experimentViewerSlice';
import attributeFinderReducer from './attributeFinderSlice';
import frameReducer from './frameSlice';
import transcriptReducer from './transcriptSlice';
import createWebSocketMiddleware from './webSocketMiddleware';
import toastReducer from './toastSlice';

// Create a custom error logger middleware
const errorLogger = (store: any) => (next: any) => (action: any) => {
  // Log rejected thunk actions
  if (action.type?.endsWith('/rejected')) {
    console.error('Redux Thunk Error:', action.type);
    console.error('Error details:', action.error || action.payload);
  }

  return next(action);
};

const store = configureStore({
  reducer: {
    experimentViewer: experimentViewerReducer,
    attributeFinder: attributeFinderReducer,
    frame: frameReducer,
    transcript: transcriptReducer,
    toast: toastReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware()
      .concat(createWebSocketMiddleware())
      .concat(errorLogger),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export default store;
