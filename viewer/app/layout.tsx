import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'PureLab — F2P Build Explorer',
  description:
    'Explore, filter and compare mathematically ranked OSRS F2P pure builds.',
  icons: { icon: '/favicon.svg' },
  openGraph: {
    type: 'website',
    siteName: 'PureLab',
    title: 'PureLab — F2P Build Explorer',
    description:
      'Search, group and inspect mathematically ranked OSRS F2P pure builds.',
    images: [
      {
        url: '/og.png',
        width: 1200,
        height: 630,
        alt: 'PureLab F2P Build Explorer',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'PureLab — F2P Build Explorer',
    description:
      'Search, group and inspect mathematically ranked OSRS F2P pure builds.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
