"use client";

import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

const ADMIN_NAV = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/config", label: "Config" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/infrastructure", label: "Infrastructure" },
  { href: "/admin/services", label: "Services" },
  { href: "/admin/logs", label: "Audit Logs" },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, loading, role } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const isPlatformAdmin = role === "platform_admin";

  useEffect(() => {
    if (!loading && (!user || !isPlatformAdmin)) {
      router.replace("/");
    }
  }, [user, loading, isPlatformAdmin, router]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  if (!user || !isPlatformAdmin) {
    return null;
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Platform Admin</h1>
        <p className="text-sm text-gray-500">
          Manage users, roles, organizations, and monitor platform services
        </p>
      </div>
      <div className="mb-6 flex gap-1 border-b border-gray-200">
        {ADMIN_NAV.map((item) => (
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
