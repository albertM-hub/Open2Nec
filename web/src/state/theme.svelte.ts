// Thème de l'interface : Auto (réglage du système), Clair ou Sombre, mémorisé dans le navigateur.
// Les couleurs sont des variables CSS (app.css). La vue 3D et les courbes dessinent sur un
// canevas, qui ne lit pas ces variables : elles appellent color() et se reconstruisent quand
// `theme.version` change (choix de l'utilisateur, ou réglage du système en mode Auto).

export type ThemeChoice = 'auto' | 'light' | 'dark';

const KEY = 'open2nec-theme';
const CHOICES: ThemeChoice[] = ['auto', 'light', 'dark'];

function load(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return CHOICES.includes(v as ThemeChoice) ? (v as ThemeChoice) : 'auto';
  } catch {
    return 'auto'; // stockage indisponible (navigation privée, réglages) : on suit le système
  }
}

let choice = $state<ThemeChoice>(load());
let version = $state(0);

function apply() {
  const root = document.documentElement;
  if (choice === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

apply();
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (choice === 'auto') version += 1;
});

export const theme = {
  get choice() {
    return choice;
  },
  /** Change à chaque changement effectif de couleurs : à lire dans un $effect pour redessiner. */
  get version() {
    return version;
  },
  /** Auto → Clair → Sombre → Auto. */
  cycle() {
    choice = CHOICES[(CHOICES.indexOf(choice) + 1) % CHOICES.length];
    try {
      localStorage.setItem(KEY, choice);
    } catch {
      // non mémorisé, mais appliqué pour cette visite
    }
    apply();
    version += 1;
  },
};

/** Valeur d'une variable de couleur du thème courant (« --accent » → « #4f8cff »). */
export function color(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

/** Même couleur avec une opacité (canevas : pas de color-mix). */
export function alpha(name: string, a: number): string {
  const hex = color(name).replace('#', '');
  const full = hex.length === 3 ? [...hex].map((c) => c + c).join('') : hex;
  const n = parseInt(full, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** Couleur du thème en entier 0xRRGGBB (Three.js). */
export function colorHex(name: string): number {
  return parseInt(color(name).replace('#', ''), 16);
}
