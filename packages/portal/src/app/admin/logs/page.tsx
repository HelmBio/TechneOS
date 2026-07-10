"use client";

import AuditLogsPanel from "@/components/audit-logs-panel";

export default function AdminAuditLogsPage() {
  return (
    <AuditLogsPanel
      logsApiPath="/api/v1/admin/audit-logs"
      usersApiPath="/api/v1/admin/users"
      orgsApiPath="/api/v1/admin/orgs"
      rolesApiPath="/api/v1/admin/roles"
    />
  );
}
