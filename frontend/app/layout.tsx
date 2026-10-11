import type { Metadata } from 'next';
import './globals.css';
import './design.css';
import './ai-demo.css';
import './marketplace.css';
import './aries.css';
import './motion.css';
import './mimas-dashboard-theme.css';
import {MotionProvider} from './motion';
export const metadata: Metadata = { title: 'mimas — голосовое AI-интервью', description: 'Голосовое интервью по вакансии для квалифицированных рабочих: вопросы, ответы и понятный отчёт для человека, принимающего решение' };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="ru"><body><MotionProvider>{children}</MotionProvider></body></html>; }
