import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Messages | CivicAgent",
  description:
    "Secure complaint conversations with your civic officials — messages, attachments, read receipts and AI-assisted drafts.",
};

export default function MessagesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}