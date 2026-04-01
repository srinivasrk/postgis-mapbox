import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Seattle traffic (MVT)",
  description: "Animated traffic congestion from Timescale + PostGIS tiles",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
