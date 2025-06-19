import type { Middleware } from '@reduxjs/toolkit';

import socketService from '../services/socketService';

import { setSearchesWithStats } from './searchSlice';
import {
  setOuterStatMarginals,
  setIdMarginals,
  setStatMarginalsAndFilters,
} from './experimentViewerSlice';
import {
  setBaseFilter,
  setMarginals,
  setAgentRunMetadataFields,
  updateAgentRunMetadata,
  setInnerDimId,
  setOuterDimId,
  setDimensions,
  setFrameGrids,
} from './frameSlice';
import { AppDispatch } from './store';
import {
  handleAgentRunsUpdated,
  onFinishLoadingActionsSummary,
  onFinishLoadingSolutionSummary,
  setActionsSummary,
  setCurAgentRun,
  setLoadingTaResponse,
  setSolutionSummary,
  setTaMessages,
  setTaSessionId,
} from './transcriptSlice';

export const createWebSocketMiddleware = (): Middleware => {
  return (store) => {
    // Set up a listener for WebSocket messages
    const handleMessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      console.log('(ws)', data);

      // Handle different types of messages from the server
      const dispatch = store.dispatch as AppDispatch;
      switch (data.action) {
        case 'framegrids_updated':
          dispatch(setFrameGrids(data.payload));
          break;
        case 'framegrid_deleted':
          // If the current framegrid is deleted, we could potentially redirect to the home page
          // This would be handled by a different part of the app
          break;
        case 'dimensions':
          dispatch(setDimensions(data.payload));
          break;
        case 'base_filter':
          dispatch(setBaseFilter(data.payload));
          break;
        case 'transcript_metadata_fields':
          dispatch(setAgentRunMetadataFields(data.payload.fields));
          break;
        case 'datapoint_metadata':
          dispatch(updateAgentRunMetadata(data.payload.metadata));
          break;
        case 'marginals':
          dispatch(setMarginals(data.payload));
          break;

        case 'specific_marginals':
          if (data.payload.request_type === 'comb_stats') {
            dispatch(setStatMarginalsAndFilters(data.payload.result));
          } else if (data.payload.request_type === 'comb_ids') {
            dispatch(setIdMarginals(data.payload.result));
          } else if (
            data.payload.request_type === 'outer_stats' &&
            data.payload.result
          ) {
            dispatch(setOuterStatMarginals(data.payload.result));
          }
          break;
        case 'datapoint':
          dispatch(setCurAgentRun(data.payload.datapoint));
          break;
        case 'datapoints_updated':
          dispatch(handleAgentRunsUpdated());
          break;
        case 'searches':
          dispatch(setSearchesWithStats(data.payload));
          break;
        case 'io_dims_updated':
          dispatch(setInnerDimId(data.payload.inner_dim_id));
          dispatch(setOuterDimId(data.payload.outer_dim_id));
          break;
        case 'summarize_transcript_update':
          if (data.payload.type === 'solution') {
            dispatch(setSolutionSummary(data.payload.solution));
          } else if (data.payload.type === 'actions') {
            dispatch(setActionsSummary(data.payload.actions));
          }
          break;
        case 'summarize_transcript_complete':
          if (data.payload.type === 'solution') {
            dispatch(onFinishLoadingSolutionSummary());
          } else if (data.payload.type === 'actions') {
            dispatch(onFinishLoadingActionsSummary());
          }
          break;

        case 'ta_session_created':
          dispatch(setTaSessionId(data.payload.session_id));
          break;
        case 'ta_message_chunk':
          dispatch(setTaMessages(data.payload.messages));
          break;
        case 'ta_message_complete':
          dispatch(setLoadingTaResponse(false));
          break;

        default:
          console.error('(ws) unhandled message', data);
          break;
      }
    };

    // Register the message handler when the middleware is created
    socketService.addMessageListener(handleMessage);

    // Pass all actions through to the next middleware
    return (next) => (action) => {
      return next(action);
    };
  };
};

export default createWebSocketMiddleware;
