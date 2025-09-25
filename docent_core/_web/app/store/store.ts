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
import { investigatorApi } from '../api/investigatorApi';
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
    [investigatorApi.reducerPath]: investigatorApi.reducer,
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
      .concat(investigatorApi.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export default store;
