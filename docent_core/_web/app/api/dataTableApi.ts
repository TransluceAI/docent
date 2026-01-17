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
        url: `/${collectionId}/${dataTableId}`,
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
      async onQueryStarted({ collectionId }, { dispatch, queryFulfilled }) {
        try {
          const { data } = await queryFulfilled;
          dispatch(
            dataTableApi.util.updateQueryData(
              'listDataTables',
              { collectionId },
              (draft) => {
                draft.unshift(data);
              }
            )
          );
        } catch {}
      },
    }),
    updateDataTable: build.mutation<DataTable, DataTableUpdatePayload>({
      query: ({ collectionId, dataTableId, name, dql, state }) => ({
        url: `/${collectionId}/${dataTableId}`,
        method: 'POST',
        body: { name, dql, state },
      }),
      async onQueryStarted(
        { collectionId, dataTableId },
        { dispatch, queryFulfilled }
      ) {
        try {
          const { data } = await queryFulfilled;
          dispatch(
            dataTableApi.util.updateQueryData(
              'listDataTables',
              { collectionId },
              (draft) => {
                const index = draft.findIndex(
                  (table) => table.id === dataTableId
                );
                if (index >= 0) {
                  draft[index] = data;
                }
              }
            )
          );
        } catch {}
      },
    }),
    deleteDataTable: build.mutation<
      { status: string },
      { collectionId: string; dataTableId: string }
    >({
      query: ({ collectionId, dataTableId }) => ({
        url: `/${collectionId}/${dataTableId}`,
        method: 'DELETE',
      }),
      async onQueryStarted(
        { collectionId, dataTableId },
        { dispatch, queryFulfilled }
      ) {
        try {
          await queryFulfilled;
          dispatch(
            dataTableApi.util.updateQueryData(
              'listDataTables',
              { collectionId },
              (draft) => {
                const index = draft.findIndex(
                  (table) => table.id === dataTableId
                );
                if (index >= 0) {
                  draft.splice(index, 1);
                }
              }
            )
          );
        } catch {}
      },
    }),
    duplicateDataTable: build.mutation<
      DataTable,
      { collectionId: string; dataTableId: string }
    >({
      query: ({ collectionId, dataTableId }) => ({
        url: `/${collectionId}/${dataTableId}/duplicate`,
        method: 'POST',
      }),
      async onQueryStarted({ collectionId }, { dispatch, queryFulfilled }) {
        try {
          const { data } = await queryFulfilled;
          dispatch(
            dataTableApi.util.updateQueryData(
              'listDataTables',
              { collectionId },
              (draft) => {
                draft.unshift(data);
              }
            )
          );
        } catch {}
      },
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
} = dataTableApi;
