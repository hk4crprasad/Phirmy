import {lazy, Suspense, useEffect, useRef, useState} from 'react';
import RotatingText from './react-bits/new/RotatingText';
const Threads = lazy(() => import('./react-bits/new/Threads'));

// One lifecycle gate for idle, hidden, offscreen, mobile and reduced-motion states.
export function useAccentMotion(paused: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [desktop, setDesktop] = useState(false);
  useEffect(() => {
    const query = matchMedia('(min-width: 768px) and (pointer: fine)');
    const change = () => setDesktop(query.matches);
    const visibility = () => setHidden(document.hidden);
    change(); visibility();
    query.addEventListener('change', change);
    document.addEventListener('visibilitychange', visibility);
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    if (ref.current) observer.observe(ref.current);
    return () => { observer.disconnect(); query.removeEventListener('change',change); document.removeEventListener('visibilitychange',visibility); };
  }, []);
  return {ref, active: !paused && visible && !hidden, desktop};
}
export function HeroThreads({paused}:{paused:boolean}) {
  const {ref, active, desktop} = useAccentMotion(paused);
  return <div ref={ref} className="hero-threads" aria-hidden="true">
    {desktop && active && <Suspense fallback={null}><Threads color="#397552" accentColor="#9dbba1" lineCount={26} amplitude={1.1} distance={.18} thickness={.55} speed={.32} opacity={.48} fade={.35} angle={-22} enableMouseInteraction={false}/></Suspense>}
  </div>;
}
export function ConversationWords({paused}:{paused:boolean}) {
 const {ref,active} = useAccentMotion(paused);
 return <div ref={ref} className="conversation-words">
   <span className="sr-only">Make room for first hellos, bright ideas, and real connections.</span>
   <div aria-hidden="true" className="conversation-words-visual"><span>Make room for</span>{paused ? <span className="conversation-word-static">real connections.</span> : <RotatingText texts={['first hellos.','bright ideas.','real connections.']} auto={active} rotationInterval={3800} staggerDuration={.015} effect="blur" splitBy="words" mainClassName="conversation-word" transition={{type:'spring',damping:28,stiffness:180}}/>}</div>
 </div>;
}
