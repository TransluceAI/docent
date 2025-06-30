import { PermissionLevel } from './types';
import { User } from '@/app/types/userTypes';
import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { BASE_URL } from '@/app/constants';
import { UserPermissions } from '@/app/services/permissionsService';

type CollaboratorIdentifier = Pick<
  Collaborator,
  'collection_id' | 'subject_type' | 'subject_id'
>;
export const collabApi = createApi({
  reducerPath: 'collab',
  baseQuery: fetchBaseQuery({
    baseUrl: `${BASE_URL}/rest`,
    credentials: 'include',
  }),
  tagTypes: ['Collaborators', 'Users', 'CollectionPermissions'],
  endpoints: (build) => ({
    getCollectionPermissions: build.query<UserPermissions, string>({
      query: (collectionId) => `/${collectionId}/permissions`,
      providesTags: ['CollectionPermissions'],
    }),
    getOrgUsers: build.query<User[], string>({
      query: (orgId) => `/organizations/${orgId}/users`,
      providesTags: ['Users'],
    }),
    getUserByEmail: build.query<User | null, string>({
      query: (email) => `/users/by-email/${encodeURIComponent(email)}`,
      providesTags: ['Users'],
    }),
    getCollaborators: build.query<Collaborator[], string>({
      query: (collectionId) => `/collections/${collectionId}/collaborators`,
      providesTags: ['Collaborators'],
    }),
    removeCollaborator: build.mutation<
      void,
      Pick<Collaborator, 'collection_id' | 'subject_type' | 'subject_id'>
    >({
      query: ({ subject_type, subject_id, collection_id }) => ({
        url: `collections/${collection_id}/collaborators/delete`,
        method: 'DELETE',
        body: {
          subject_id,
          subject_type,
          collection_id,
        },
      }),
      invalidatesTags: ['Collaborators'],
    }),
    upsertCollaborator: build.mutation<
      Collaborator,
      CollaboratorIdentifier & { permission_level: PermissionLevel }
    >({
      query: ({
        collection_id,
        subject_type,
        subject_id,
        permission_level,
      }) => ({
        url: `/collections/${collection_id}/collaborators/upsert`,
        method: 'PUT',
        body: {
          subject_id,
          subject_type,
          collection_id,
          permission_level,
        },
      }),
      invalidatesTags: ['Collaborators'],
    }),
  }),
});

export const {
  useGetCollectionPermissionsQuery,
  useGetOrgUsersQuery,
  useGetUserByEmailQuery,
  useLazyGetUserByEmailQuery,
  useGetCollaboratorsQuery,
  useUpsertCollaboratorMutation,
  useRemoveCollaboratorMutation,
} = collabApi;

export interface Organization {
  id: string;
  name: string;
  description: string;
}

export interface UserCollaborator {
  subject_type: 'user';
  subject_id: string;
  permission_level: PermissionLevel;
  collection_id: string;
  subject: User;
}
export interface OrganizationCollaborator {
  subject_type: 'organization';
  subject_id: string;
  permission_level: PermissionLevel;
  collection_id: string;
  subject: Organization;
}
export interface PublicCollaborator {
  subject_type: 'public';
  subject_id: 'public';
  permission_level: PermissionLevel;
  collection_id: string;
}

export type Collaborator =
  | UserCollaborator
  | OrganizationCollaborator
  | PublicCollaborator;
