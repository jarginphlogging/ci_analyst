import type { Metadata } from "next";
import localFont from "next/font/local";
import { Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const displayFont = localFont({
  variable: "--font-display",
  src: [
    {
      path: "./fonts/fraunces-variable.ttf",
      style: "normal",
      weight: "100 900",
    },
    {
      path: "./fonts/fraunces-variable-italic.ttf",
      style: "italic",
      weight: "100 900",
    },
  ],
});

const bodyFont = Space_Grotesk({
  variable: "--font-body",
  subsets: ["latin"],
});

const monoFont = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Cortex Conversational Analyst",
  description: "Distinctive, production-grade interface for conversational analytics",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${displayFont.variable} ${bodyFont.variable} ${monoFont.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
