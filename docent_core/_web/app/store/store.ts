// store.ts

import { configureStore } from '@reduxjs/toolkit';

import collectionReducer from './collectionSlice';
import toastReducer from './toastSlice';
import transcriptReducer from './transcriptSlice';
import embedReducer from './embedSlice';
import { collabApi } from '@/lib/permissions/collabSlice';
import { chartApi } from '../api/chartApi';
import { rubricApi } from '../api/rubricApi';
import rubricReducer from './rubricSlice';
import { collectionApi } from '../api/collectionApi';
import { refinementApi } from '../api/refinementApi';
import { chatApi } from '../api/chatApi';
import { settingsApi } from '../api/settingsApi';
import { labelApi } from '../api/labelApi';
import { orgApi } from '../api/orgApi';
import { statusApi } from '@/components/MaintenanceBanner';
import { resultSetApi } from '../api/resultSetApi';
import refinementReducer from './refinementSlice';

const store = configureStore({
  reducer: {
    rubric: rubricReducer,
    embed: embedReducer,
    collection: collectionReducer,
    transcript: transcriptReducer,
    toast: toastReducer,
    refinement: refinementReducer,
    [collabApi.reducerPath]: collabApi.reducer,
    [chartApi.reducerPath]: chartApi.reducer,
    [rubricApi.reducerPath]: rubricApi.reducer,
    [collectionApi.reducerPath]: collectionApi.reducer,
    [refinementApi.reducerPath]: refinementApi.reducer,
    [chatApi.reducerPath]: chatApi.reducer,
    [settingsApi.reducerPath]: settingsApi.reducer,
    [labelApi.reducerPath]: labelApi.reducer,
    [orgApi.reducerPath]: orgApi.reducer,
    [statusApi.reducerPath]: statusApi.reducer,
    [resultSetApi.reducerPath]: resultSetApi.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        ignoredActionPaths: ['meta.arg', 'meta.baseQueryMeta'],
        ignoredActions: ['persist/PERSIST', 'persist/REHYDRATE'],
        ignoredPaths: [
          'collectionApi.queries.importRunsFromFileStream(undefined).originalArgs',
        ],
      },
    })
      .concat(collabApi.middleware)
      .concat(chartApi.middleware)
      .concat(rubricApi.middleware)
      .concat(collectionApi.middleware)
      .concat(refinementApi.middleware)
      .concat(chatApi.middleware)
      .concat(settingsApi.middleware)
      .concat(labelApi.middleware)
      .concat(orgApi.middleware)
      .concat(statusApi.middleware)
      .concat(resultSetApi.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export default store;
