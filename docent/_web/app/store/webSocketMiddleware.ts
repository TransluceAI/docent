import { Middleware } from '@reduxjs/toolkit';
import socketService from '../services/socketService';
import {
  setExperimentStatMarginals,
  setInterventionDescriptionMarginals,
  setIdMarginals,
  setSampleStatMarginals,
  setStatMarginals,
  setStatMarginalsAndFilters,
} from './experimentViewerSlice';
import { AppDispatch } from './store';
import {
  setBaseFilter,
  setMarginals,
  setTranscriptMetadataFields,
  updateTranscriptMetadata,
} from './frameSlice';
import { setDimensions } from './frameSlice';
import { getTranscriptMetadataFields } from './frameSlice';
import { getState } from './frameSlice';
import { setExperimentDimId, setSampleDimId } from './frameSlice';
import { setFrameGridId } from './frameSlice';
import {
  handleAttributesUpdate,
  setAttributeSearches,
  setLoadingAttributesForId,
} from './attributeFinderSlice';
import {
  handleDatapointsUpdated,
  onFinishLoadingActionsSummary,
  onFinishLoadingSolutionSummary,
  setActionsSummary,
  setCurDatapoint,
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
        case 'session_joined':
          dispatch(setFrameGridId(data.payload.id));
          dispatch(setSampleDimId(data.payload.sample_dim_id));
          dispatch(setExperimentDimId(data.payload.experiment_dim_id));

          dispatch(getState(data.payload.id));
          dispatch(getTranscriptMetadataFields());

          break;
        case 'dimensions':
          dispatch(setDimensions(data.payload));
          break;
        case 'base_filter':
          dispatch(setBaseFilter(data.payload));
          break;
        case 'transcript_metadata_fields':
          dispatch(setTranscriptMetadataFields(data.payload.fields));
          break;
        case 'datapoint_metadata':
          dispatch(updateTranscriptMetadata(data.payload.metadata));
          break;
        case 'marginals':
          dispatch(setMarginals(data.payload));
          break;

        case 'compute_attributes_update':
          dispatch(handleAttributesUpdate(data.payload));
          break;
        case 'compute_attributes_complete':
          dispatch(setLoadingAttributesForId(undefined));
          break;
        case 'specific_marginals':
          if (data.payload.request_type === 'exp_stats') {
            dispatch(setStatMarginalsAndFilters(data.payload.result));
          } else if (data.payload.request_type === 'exp_ids') {
            dispatch(setIdMarginals(data.payload.result));
          } else if (data.payload.request_type === 'per_sample_stats') {
            dispatch(setSampleStatMarginals(data.payload.result));
          } else if (data.payload.request_type === 'per_experiment_stats') {
            dispatch(setExperimentStatMarginals(data.payload.result));
          } else if (
            data.payload.request_type === 'intervention_descriptions'
          ) {
            dispatch(setInterventionDescriptionMarginals(data.payload.result));
          }
          break;
        case 'datapoint':
          dispatch(setCurDatapoint(data.payload.datapoint));
          break;
        case 'datapoints_updated':
          dispatch(handleDatapointsUpdated());
          break;
        case 'attribute_searches':
          dispatch(setAttributeSearches(data.payload));
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
