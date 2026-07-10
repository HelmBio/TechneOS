"use client";

import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/rbac";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

const ORG_ADMIN_NAV = [
  { href: "/org-admin", label: "Overview" },
  { href: "/org-admin/config", label: "Config" },
  { href: "/org-admin/users", label: "Users" },
  { href: "/org-admin/logs", label: "Audit Logs" },
];

export default function OrgAdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, permissions, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const hasOrgAccess = hasPermission(permissions, "org", "update", "org");

  useEffect(() => {
    if (!loading && (!user || !hasOrgAccess)) {
      router.replace("/");
    }
  }, [user, permissions, loading, router, hasOrgAccess]);

  if (loading || !user || !hasOrgAccess) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          Organization Admin
        </h1>
        <p className="text-sm text-gray-500">
          Manage users and teams within your organization
        </p>
      </div>
      <div className="mb-6 flex gap-1 border-b border-gray-200">
        {ORG_ADMIN_NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              pathname === item.href
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </div>
      {children}
    </div>
  );
}
