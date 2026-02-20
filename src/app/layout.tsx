import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bookmate — Find Book Discussions",
  description:
    "Search for any book and instantly find active discussions, reading groups, and communities on Reddit, Goodreads, and more.",
  keywords: ["book club", "book discussion", "reading group", "reddit bookclub", "goodreads"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>{children}</body>
    </html>
  );
}
