"use client";

import UsersPanel from "@/components/users-panel";

export default function AdminUsersPage() {
  return (
    <UsersPanel
      usersApiPath="/api/v1/admin/users"
      updateApiPrefix="/api/v1/admin/users"
      createApiPath="/api/v1/admin/users"
      rolesApiPath="/api/v1/admin/roles"
      showOrg
      orgsApiPath="/api/v1/admin/orgs"
      showTeam
      teamsApiPath="/api/v1/admin/teams"
    />
  );
}
