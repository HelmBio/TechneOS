"use client";

import { useState } from "react";
import { ConfirmModal } from "@/components/run/confirm-modal";

interface RunActionButtonsProps {
  canCancel: boolean;
  canRestart: boolean;
  cancelling: boolean;
  restarting: boolean;
  onCancel: () => void;
  onRestart: () => void;
}

function Spinner() {
  return (
    <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" />
    </svg>
  );
}

function IconButton({
  onClick,
  disabled,
  tooltip,
  borderColor,
  textColor,
  hoverBg,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  tooltip: string;
  borderColor: string;
  textColor: string;
  hoverBg: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`group relative rounded-md border ${borderColor} p-2 ${textColor} ${hoverBg} disabled:opacity-50`}
    >
      {children}
      <span className="pointer-events-none absolute right-0 top-full mt-1 hidden w-max max-w-[200px] rounded bg-gray-800 px-2 py-1 text-xs text-white shadow group-hover:block">
        {tooltip}
      </span>
    </button>
  );
}

export function RunActionButtons({
  canCancel,
  canRestart,
  cancelling,
  restarting,
  onCancel,
  onRestart,
}: RunActionButtonsProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <>
      <div className="flex items-center gap-2">
        {canCancel && (
          <IconButton
            onClick={() => setConfirmOpen(true)}
            disabled={cancelling}
            tooltip="Cancel run"
            borderColor="border-red-300"
            textColor="text-red-700"
            hoverBg="hover:bg-red-50"
          >
            {cancelling ? (
              <Spinner />
            ) : (
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="m15 9-6 6" />
                <path d="m9 9 6 6" />
              </svg>
            )}
          </IconButton>
        )}
        {canRestart && (
          <IconButton
            onClick={onRestart}
            disabled={restarting}
            tooltip="Restart run"
            borderColor="border-blue-300"
            textColor="text-blue-700"
            hoverBg="hover:bg-blue-50"
          >
            {restarting ? (
              <Spinner />
            ) : (
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M1 4v6h6" />
                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
              </svg>
            )}
          </IconButton>
        )}
      </div>
      <ConfirmModal
        open={confirmOpen}
        title="Cancel Run"
        message="Are you sure you want to cancel this run? This action cannot be undone."
        confirmLabel="Cancel Run"
        cancelLabel="Keep Running"
        confirmColor="red"
        loading={cancelling}
        onConfirm={() => {
          onCancel();
          setConfirmOpen(false);
        }}
        onClose={() => setConfirmOpen(false)}
      />
    </>
  );
}
