/**
 * The page works without this file. It adds the 3D stages after first paint,
 * and the copy buttons on /press.
 */

interface NetworkInformation {
  saveData?: boolean;
  effectiveType?: string;
}

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function canUse3d(): boolean {
  const connection = (navigator as Navigator & { connection?: NetworkInformation }).connection;
  if (connection?.saveData) return false;
  if (connection?.effectiveType && /(^|-)2g$/.test(connection.effectiveType)) return false;
  try {
    const probe = document.createElement('canvas');
    return Boolean(probe.getContext('webgl2') ?? probe.getContext('webgl'));
  } catch {
    return false;
  }
}

function whenIdle(run: () => void): void {
  const idle = () => ('requestIdleCallback' in window ? window.requestIdleCallback(run, { timeout: 2500 }) : setTimeout(run, 300));
  if (document.readyState === 'complete') idle();
  else window.addEventListener('load', idle, { once: true });
}

function mountStages(): void {
  if (!canUse3d()) return;

  const hero = document.querySelector<HTMLElement>('[data-stage="hero"]');
  if (hero && !reducedMotion) {
    whenIdle(() => {
      import('./three/hero')
        .then((m) => m.mountHero(hero))
        .catch(() => hero.classList.remove('is-live'));
    });
  }

  const head = document.querySelector<HTMLElement>('[data-stage="head"]');
  if (head) {
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        whenIdle(() => {
          import('./three/head')
            .then((m) => m.mountHead(head, reducedMotion))
            .catch(() => head.classList.remove('is-live'));
        });
      },
      { rootMargin: '600px 0px' },
    );
    io.observe(head);
  }
}

function copyButtons(): void {
  for (const button of document.querySelectorAll<HTMLButtonElement>('[data-copy]')) {
    button.addEventListener('click', async () => {
      const source = document.getElementById(button.dataset.copy ?? '');
      const status = button.parentElement?.querySelector<HTMLElement>('[role="status"]');
      if (!source) return;
      const text = [...source.querySelectorAll('p')].map((p) => p.textContent?.trim() ?? '').join('\n\n');
      try {
        await navigator.clipboard.writeText(text);
        if (status) status.textContent = button.dataset.labelDone ?? '';
      } catch {
        if (status) status.textContent = button.dataset.labelFailed ?? '';
      }
      if (status) setTimeout(() => (status.textContent = ''), 2500);
    });
  }
}

mountStages();
copyButtons();
