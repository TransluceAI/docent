import type { Middleware } from '@reduxjs/toolkit';

import socketService from '../services/socketService';

import { setAgentRunIds } from './experimentViewerSlice';
import { updateAgentRunMetadata } from './collectionSlice';
import { AppDispatch } from './store';
import { chartApi } from '../api/chartApi';
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
import { setEmbeddingProgress, setIsListening } from './embedSlice';

export const createWebSocketMiddleware = (): Middleware => {
  return (store) => {
    // Set up a listener for WebSocket messages
    const handleMessage = async (event: MessageEvent) => {
      const data = JSON.parse(event.data);

      // Handle different types of messages from the server
      const dispatch = store.dispatch as AppDispatch;
      switch (data.action) {
        case 'datapoint_metadata':
          dispatch(updateAgentRunMetadata(data.payload.metadata));
          break;
        case 'specific_bins':
          if (data.payload.request_type === 'comb_stats') {
            dispatch(setAgentRunIds(data.payload.result?.agentRunIds || []));
            // Invalidate the chart data cache
            dispatch(chartApi.util.invalidateTags(['ChartData']));
          }
          break;
        case 'datapoint':
          dispatch(setCurAgentRun(data.payload.datapoint));
          break;
        case 'datapoints_updated':
          dispatch(handleAgentRunsUpdated());
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

        case 'embedding_progress':
          dispatch(setEmbeddingProgress(data.payload));
          dispatch(setIsListening(true));
          break;
        case 'embedding_complete':
          dispatch(setEmbeddingProgress(undefined));
          dispatch(setIsListening(false));
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
