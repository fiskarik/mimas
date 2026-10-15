import type { Metadata } from 'next';
import './globals.css';
import './design.css';
import './ai-demo.css';
import './marketplace.css';
import './aries.css';
import './motion.css';
import './brand-logo.css';
import './mimas-dashboard-theme.css';
import './cursor-dots.css';
import {MotionProvider} from './motion';
export const metadata: Metadata = { title: 'mimas — голосовое AI-интервью', description: 'Голосовое AI-интервью для кандидатов на работу в магазине и на складе: рабочие ситуации, ответы и понятный отчёт по навыкам' };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="ru"><body><MotionProvider>{children}</MotionProvider></body></html>; }
