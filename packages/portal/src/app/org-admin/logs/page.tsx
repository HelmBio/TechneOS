"use client";

import AuditLogsPanel from "@/components/audit-logs-panel";

export default function OrgAdminAuditLogsPage() {
  return (
    <AuditLogsPanel
      logsApiPath="/api/v1/users/audit-logs"
      usersApiPath="/api/v1/users"
      rolesApiPath="/api/v1/users/roles"
    />
  );
}
