"use client";

import { useAuth } from "@/lib/auth";
import UsersPanel from "@/components/users-panel";

export default function OrgAdminUsersPage() {
  const { user } = useAuth();

  return (
    <UsersPanel
      usersApiPath="/api/v1/users"
      updateApiPrefix="/api/v1/users"
      createApiPath="/api/v1/users"
      deleteApiPrefix="/api/v1/admin/users/by-email"
      rolesApiPath="/api/v1/users/roles"
      showTeam
      teamsApiPath={
        user?.org_id
          ? `/api/v1/orgs/${user.org_id}/teams`
          : undefined
      }
      excludeRoles={["platform_admin"]}
    />
  );
}
