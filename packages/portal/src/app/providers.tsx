"use client";

import { AuthProvider, useAuth, SessionExpiredAlert, SessionExpiryBanner } from "@/lib/auth";
import { LabelsProvider } from "@/lib/labels";
import { TopBar, Sidebar } from "@/components/navbar";

function AppShell({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        {user && <Sidebar />}
        <main className="flex-1 overflow-y-auto px-4 py-3">
          {children}
        </main>
      </div>
    </div>
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <LabelsProvider>
        <SessionExpiryBanner />
        <AppShell>{children}</AppShell>
        <SessionExpiredAlert />
      </LabelsProvider>
    </AuthProvider>
  );
}
