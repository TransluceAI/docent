import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';

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
  label_schema: Record<string, any>;
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

export interface LabelSetName {
  id: string;
  name: string;
}

export const labelApi = createApi({
  reducerPath: 'labelApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/label`,
    credentials: 'include',
  }),
  tagTypes: ['Label', 'LabelSet', 'LabelSetAssociation'],
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
      invalidatesTags: ['Label'],
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
      }
    >({
      query: ({ collectionId, labelId, label_value }) => ({
        url: `/${collectionId}/label/${labelId}`,
        method: 'PUT',
        body: { label_value },
      }),
      invalidatesTags: ['Label'],
    }),
    deleteLabel: build.mutation<
      { message: string },
      { collectionId: string; labelId: string }
    >({
      query: ({ collectionId, labelId }) => ({
        url: `/${collectionId}/label/${labelId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (result, error, { labelId }) => [
        { type: 'Label', id: labelId },
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
    getLabelsInLabelSets: build.query<
      Label[],
      { collectionId: string; labelSetIds: string[] }
    >({
      query: ({ collectionId, labelSetIds }) => {
        const params = new URLSearchParams();
        labelSetIds.forEach((id) => params.append('labelSetIds', id));
        return {
          url: `/${collectionId}/labels_in_label_sets?${params.toString()}`,
          method: 'GET',
        };
      },
      providesTags: (result) =>
        result
          ? [
              'Label',
              ...result.map((label) => ({
                type: 'Label' as const,
                id: label.id,
              })),
            ]
          : ['Label'],
    }),
    getLabelSets: build.query<LabelSet[], { collectionId: string }>({
      query: ({ collectionId }) => ({
        url: `/${collectionId}/label_sets`,
        method: 'GET',
      }),
      providesTags: ['LabelSet'],
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
  }),
});

export const {
  // Label CRUD
  useCreateLabelMutation,
  useGetLabelQuery,
  useUpdateLabelMutation,
  useDeleteLabelMutation,

  // Label Set CRUD
  useCreateLabelSetMutation,
  useGetLabelSetQuery,
  useGetLabelSetsQuery,
  useGetLabelsInLabelSetQuery,
  useDeleteLabelSetMutation,
  useGetLabelsInLabelSetsQuery,
} = labelApi;
