import type { Metadata } from "next";
import localFont from "next/font/local";
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

const bodyFont = localFont({
  variable: "--font-body",
  src: [
    {
      path: "./fonts/space-grotesk-variable.ttf",
      style: "normal",
      weight: "300 700",
    },
  ],
});

const monoFont = localFont({
  variable: "--font-mono",
  src: [
    {
      path: "./fonts/jetbrains-mono-variable.ttf",
      style: "normal",
      weight: "100 800",
    },
    {
      path: "./fonts/jetbrains-mono-variable-italic.ttf",
      style: "italic",
      weight: "100 800",
    },
  ],
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
