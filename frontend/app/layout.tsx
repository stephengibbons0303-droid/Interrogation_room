import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Interrogation Room",
  description: "Immersive AI-driven interrogation experience",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
