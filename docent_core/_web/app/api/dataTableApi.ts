import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { DataTable, DataTableState } from '@/app/types/dataTableTypes';

type DataTableCreatePayload = {
  collectionId: string;
  name?: string;
  dql?: string;
  state?: DataTableState | null;
};

type DataTableUpdatePayload = {
  collectionId: string;
  dataTableId: string;
  name?: string;
  dql?: string;
  state?: DataTableState | null;
};

type GenerateNamePayload = {
  collectionId: string;
  dql: string;
};

type GenerateNameResponse = {
  name: string;
};

export const dataTableApi = createApi({
  reducerPath: 'dataTableApi',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest/data-table`,
    credentials: 'include',
  }),
  tagTypes: ['DataTables'],
  endpoints: (build) => ({
    listDataTables: build.query<DataTable[], { collectionId: string }>({
      query: ({ collectionId }) => ({
        url: `/${collectionId}`,
        method: 'GET',
      }),
      providesTags: (result) =>
        result
          ? [
              ...result.map((table) => ({
                type: 'DataTables' as const,
                id: table.id,
              })),
              { type: 'DataTables' as const, id: 'LIST' },
            ]
          : [{ type: 'DataTables' as const, id: 'LIST' }],
    }),
    getDataTable: build.query<
      DataTable,
      { collectionId: string; dataTableId: string }
    >({
      query: ({ collectionId, dataTableId }) => ({
        url: `/${collectionId}/table/${dataTableId}`,
        method: 'GET',
      }),
      providesTags: (_result, _error, { dataTableId }) => [
        { type: 'DataTables', id: dataTableId },
      ],
    }),
    createDataTable: build.mutation<DataTable, DataTableCreatePayload>({
      query: ({ collectionId, name, dql, state }) => ({
        url: `/${collectionId}`,
        method: 'POST',
        body: { name, dql, state },
      }),
      invalidatesTags: ['DataTables'],
    }),
    updateDataTable: build.mutation<DataTable, DataTableUpdatePayload>({
      query: ({ collectionId, dataTableId, name, dql, state }) => ({
        url: `/${collectionId}/table/${dataTableId}`,
        method: 'POST',
        body: { name, dql, state },
      }),
      invalidatesTags: (_result, _error, { dataTableId }) => [
        { type: 'DataTables', id: dataTableId },
        { type: 'DataTables', id: 'LIST' },
      ],
    }),
    deleteDataTable: build.mutation<
      { status: string },
      { collectionId: string; dataTableId: string }
    >({
      query: ({ collectionId, dataTableId }) => ({
        url: `/${collectionId}/table/${dataTableId}`,
        method: 'DELETE',
      }),
      invalidatesTags: (_result, _error, { dataTableId }) => [
        { type: 'DataTables', id: dataTableId },
        { type: 'DataTables', id: 'LIST' },
      ],
    }),
    duplicateDataTable: build.mutation<
      DataTable,
      { collectionId: string; dataTableId: string }
    >({
      query: ({ collectionId, dataTableId }) => ({
        url: `/${collectionId}/table/${dataTableId}/duplicate`,
        method: 'POST',
      }),
      invalidatesTags: ['DataTables'],
    }),
    generateName: build.mutation<GenerateNameResponse, GenerateNamePayload>({
      query: ({ collectionId, dql }) => ({
        url: `/${collectionId}/generate-name`,
        method: 'POST',
        body: { dql },
      }),
    }),
  }),
});

export const {
  useListDataTablesQuery,
  useGetDataTableQuery,
  useCreateDataTableMutation,
  useUpdateDataTableMutation,
  useDeleteDataTableMutation,
  useDuplicateDataTableMutation,
  useGenerateNameMutation,
} = dataTableApi;
