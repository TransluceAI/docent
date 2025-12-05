import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { SchemaDefinition } from '@/app/types/schema';
import { InlineCitation } from '@/app/types/citationTypes';

// Types based on the backend models
export interface Label {
  id?: string; // Optional - backend will generate if not provided
  label_set_id: string;
  label_value: Record<string, any>;
  agent_run_id: string;
}

export interface LabelSet {
  id: string;
  name: string;
  description?: string | null;
  label_schema: SchemaDefinition;
}

export interface LabelSetWithCount {
  id: string;
  name: string;
  description: string | null;
  label_schema: Record<string, any>;
  label_count: number;
}

export interface CreateLabelRequest {
  label: Label;
}

export interface UpdateLabelRequest {
  label_value: Record<string, any>;
}

export interface CreateLabelSetRequest {
  name: string;
  description?: string | null;
  label_schema: Record<string, any>;
}

export interface UpdateLabelSetRequest {
  name: string;
  description?: string | null;
  label_schema: Record<string, any>;
}

export interface LabelSetName {
  id: string;
  name: string;
}

export interface Annotation {
  id: string;
  user_email: string;
  collection_id: string;
  agent_run_id: string;
  citations: InlineCitation[];
  created_at: string;
  content: string;
}

export interface NewAnnotation {
  agent_run_id: string;
  citations: InlineCitation[];
  content: string;
}

export interface UpdateAnnotationRequest {
  content: string;
}

export const labelApi = createApi({
  reducerPath: 'labelApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/label`,
    credentials: 'include',
  }),
  tagTypes: ['Label', 'LabelSet', 'LabelSetAssociation', 'Annotation'],
  endpoints: (build) => ({
    // Label CRUD
    createLabel: build.mutation<
      { label_id: string },
      { collectionId: string; label: Label }
    >({
      query: ({ collectionId, label }) => ({
        url: `/${collectionId}/label`,
        method: 'POST',
        body: { label },
      }),
      invalidatesTags: (result, error, { label }) => [
        'Label',
        { type: 'Label', id: `AGENT_RUN-${label.agent_run_id}` },
      ],
    }),
    getLabel: build.query<Label, { collectionId: string; labelId: string }>({
      query: ({ collectionId, labelId }) => ({
        url: `/${collectionId}/label/${labelId}`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result ? [{ type: 'Label', id: result.id }] : ['Label'],
    }),
    updateLabel: build.mutation<
      { message: string },
      {
        collectionId: string;
        labelId: string;
        label_value: Record<string, any>;
        agentRunId: string;
      }
    >({
      query: ({ collectionId, labelId, label_value }) => ({
        url: `/${collectionId}/label/${labelId}`,
        method: 'PUT',
        body: { label_value },
      }),
      invalidatesTags: (result, error, { agentRunId, labelId }) => [
        { type: 'Label', id: `AGENT_RUN-${agentRunId}` },
        { type: 'Label', id: labelId },
      ],
    }),
    deleteLabel: build.mutation<
      { message: string },
      { collectionId: string; labelId: string; agentRunId: string }
    >({
      query: ({ collectionId, labelId }) => ({
        url: `/${collectionId}/label/${labelId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { agentRunId, labelId }) => [
        { type: 'Label', id: `AGENT_RUN-${agentRunId}` },
        { type: 'Label', id: labelId },
      ],
    }),
    deleteLabelsByLabelSet: build.mutation<
      { message: string },
      { collectionId: string; labelSetId: string }
    >({
      query: ({ collectionId, labelSetId }) => ({
        url: `/${collectionId}/label_set/${labelSetId}/labels`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { labelSetId }) => [
        { type: 'Label', id: `LABEL_SET-${labelSetId}` },
        'Label',
      ],
    }),

    // Label Set CRUD
    createLabelSet: build.mutation<
      { label_set_id: string },
      { collectionId: string } & CreateLabelSetRequest
    >({
      query: ({ collectionId, ...body }) => ({
        url: `/${collectionId}/label_set`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['LabelSet'],
    }),
    getLabelSet: build.query<
      LabelSet,
      { collectionId: string; labelSetId: string }
    >({
      query: ({ collectionId, labelSetId }) => ({
        url: `/${collectionId}/label_set/${labelSetId}`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result ? [{ type: 'LabelSet', id: result.id }] : ['LabelSet'],
    }),
    getLabelSets: build.query<LabelSet[], { collectionId: string }>({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/label_sets`,
        method: 'GET',
      }),
      providesTags: ['LabelSet'],
    }),
    getLabelSetsWithCounts: build.query<
      LabelSetWithCount[],
      { collectionId: string }
    >({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/label_sets_with_counts`,
        method: 'GET',
      }),
      providesTags: ['LabelSet'],
    }),
    updateLabelSet: build.mutation<
      { message: string },
      { collectionId: string; labelSetId: string } & UpdateLabelSetRequest
    >({
      query: ({ collectionId, labelSetId, ...body }) => ({
        url: `/${collectionId}/label_set/${labelSetId}`,
        method: 'PUT',
        body,
      }),
      invalidatesTags: (result, error, { labelSetId }) => [
        { type: 'LabelSet', id: labelSetId },
        'LabelSet',
      ],
    }),
    getLabelsInLabelSet: build.query<
      Label[],
      { collectionId: string; labelSetId: string }
    >({
      query: ({ collectionId, labelSetId }) => ({
        url: `/${collectionId}/label_set/${labelSetId}/labels`,
        method: 'GET',
      }),
      providesTags: (result, error, { labelSetId }) =>
        result
          ? [
              { type: 'Label', id: `LIST-${labelSetId}` },
              ...result.map((label) => ({
                type: 'Label' as const,
                id: label.id,
              })),
            ]
          : [{ type: 'Label', id: `LIST-${labelSetId}` }],
    }),
    deleteLabelSet: build.mutation<
      { message: string },
      { collectionId: string; labelSetId: string }
    >({
      query: ({ collectionId, labelSetId }) => ({
        url: `/${collectionId}/label_set/${labelSetId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { labelSetId }) => [
        { type: 'LabelSet', id: labelSetId },
        { type: 'Label', id: `LIST-${labelSetId}` },
        'LabelSet',
      ],
    }),
    getLabelsForAgentRun: build.query<
      Label[],
      { collectionId: string; agentRunId: string }
    >({
      query: ({ collectionId, agentRunId }) => ({
        url: `/${collectionId}/agent_run/${agentRunId}/labels`,
        method: 'GET',
      }),
      providesTags: (result, error, { agentRunId }) =>
        result
          ? [
              { type: 'Label', id: `AGENT_RUN-${agentRunId}` },
              ...result.map((label) => ({
                type: 'Label' as const,
                id: label.id,
              })),
            ]
          : [{ type: 'Label', id: `AGENT_RUN-${agentRunId}` }],
    }),

    // Annotation CRUD
    createAnnotation: build.mutation<
      { message: string },
      { collectionId: string; annotation: NewAnnotation }
    >({
      query: ({ collectionId, annotation }) => ({
        url: `/${collectionId}/annotation`,
        method: 'POST',
        body: annotation,
      }),
      invalidatesTags: (result, error, { annotation }) => [
        'Annotation',
        { type: 'Annotation', id: `AGENT_RUN-${annotation.agent_run_id}` },
      ],
    }),
    updateAnnotation: build.mutation<
      { message: string },
      {
        collectionId: string;
        annotationId: string;
        content: string;
        agentRunId: string;
      }
    >({
      query: ({ collectionId, annotationId, content }) => ({
        url: `/${collectionId}/annotation/${annotationId}`,
        method: 'PUT',
        body: { content },
      }),
      invalidatesTags: (result, error, { agentRunId, annotationId }) => [
        { type: 'Annotation', id: `AGENT_RUN-${agentRunId}` },
        { type: 'Annotation', id: annotationId },
      ],
    }),
    deleteAnnotation: build.mutation<
      { message: string },
      { collectionId: string; annotationId: string; agentRunId: string }
    >({
      query: ({ collectionId, annotationId }) => ({
        url: `/${collectionId}/annotation/${annotationId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { agentRunId, annotationId }) => [
        { type: 'Annotation', id: `AGENT_RUN-${agentRunId}` },
        { type: 'Annotation', id: annotationId },
      ],
    }),
    getAnnotationsForAgentRun: build.query<
      Annotation[],
      { collectionId: string; agentRunId: string }
    >({
      query: ({ collectionId, agentRunId }) => ({
        url: `/${collectionId}/agent_run/${agentRunId}/annotations`,
        method: 'GET',
      }),
      providesTags: (result, error, { agentRunId }) =>
        result
          ? [
              { type: 'Annotation', id: `AGENT_RUN-${agentRunId}` },
              ...result.map((annotation) => ({
                type: 'Annotation' as const,
                id: annotation.id,
              })),
            ]
          : [{ type: 'Annotation', id: `AGENT_RUN-${agentRunId}` }],
    }),
  }),
});

export const {
  // Label CRUD
  useCreateLabelMutation,
  useGetLabelQuery,
  useUpdateLabelMutation,
  useDeleteLabelMutation,
  useDeleteLabelsByLabelSetMutation,

  // Label Set CRUD
  useCreateLabelSetMutation,
  useGetLabelSetQuery,
  useGetLabelSetsQuery,
  useGetLabelSetsWithCountsQuery,
  useUpdateLabelSetMutation,
  useGetLabelsInLabelSetQuery,
  useDeleteLabelSetMutation,

  // Other
  useGetLabelsForAgentRunQuery,

  // Annotation CRUD
  useCreateAnnotationMutation,
  useUpdateAnnotationMutation,
  useDeleteAnnotationMutation,
  useGetAnnotationsForAgentRunQuery,
} = labelApi;
