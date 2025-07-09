// store.ts

import { configureStore } from '@reduxjs/toolkit';

import searchReducer from './searchSlice';
import experimentViewerReducer from './experimentViewerSlice';
import collectionReducer from './collectionSlice';
import toastReducer from './toastSlice';
import transcriptReducer from './transcriptSlice';
import { diffReducer } from './diffSlice';
import embedReducer from './embedSlice';
import createWebSocketMiddleware from './webSocketMiddleware';
import { collabApi } from '@/lib/permissions/collabSlice';
import { experimentViewerApi } from '../api/experimentViewerApi';
import { diffApi } from '../api/diffApi';

// Create a custom error logger middleware
const errorLogger = () => (next: any) => (action: any) => {
  // Apparently RTK async thunks can cancel themselves in normal behavior. These are not errors. See https://stackoverflow.com/questions/69789058/what-does-this-error-mean-in-redux-toolkit
  const isRtkQueryInternalAction =
    action.type?.startsWith('collab/executeQuery') ||
    action.type?.startsWith('collab/executeMutation');
  // Log rejected thunk actions
  if (action.type?.endsWith('/rejected') && !isRtkQueryInternalAction) {
    console.error('Redux Thunk Error:', action.type);
    console.error('Error details:', action.error || action.payload);
  }

  return next(action);
};

const store = configureStore({
  reducer: {
    experimentViewer: experimentViewerReducer,
    search: searchReducer,
    embed: embedReducer,
    diff: diffReducer,
    collection: collectionReducer,
    transcript: transcriptReducer,
    toast: toastReducer,
    [collabApi.reducerPath]: collabApi.reducer,
    [experimentViewerApi.reducerPath]: experimentViewerApi.reducer,
    [diffApi.reducerPath]: diffApi.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware()
      .concat(createWebSocketMiddleware())
      .concat(errorLogger)
      .concat(collabApi.middleware)
      .concat(experimentViewerApi.middleware)
      .concat(diffApi.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export default store;
