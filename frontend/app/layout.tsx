import type { Metadata } from 'next';
import './globals.css';
import './design.css';
import './ai-demo.css';
import './marketplace.css';
import './aries.css';
import './motion.css';
import {MotionProvider} from './motion';
export const metadata: Metadata = { title: 'mimas — пространство интервью', description: 'Демонстрация технического интервью с записью и доказательствами навыков' };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="ru"><body><MotionProvider>{children}</MotionProvider></body></html>; }
