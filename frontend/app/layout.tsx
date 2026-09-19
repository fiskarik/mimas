import type { Metadata } from 'next';
import './globals.css';
import './design.css';
export const metadata: Metadata = { title: 'Автособес — пространство интервью', description: 'Демонстрация технического интервью с записью и доказательствами навыков' };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="ru"><body>{children}</body></html>; }
