import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    'break-anywhere': 'overflow-wrap: break-anywhere',
    extend: {
      width: {
        sm: '400px',
        md: '600px',
        lg: '800px',
      },
      fontFamily: {
        sans: ['var(--font-open-sans)'],
        mono: ['var(--font-jetbrains-mono)'],
      },
      backgroundColor: {
        'field-wrapper': 'hsl(var(--secondary))',
        'light-green': 'hsl(var(--accent))',
        'mid-green': 'hsl(var(--accent-foreground))',
        'navbar-btn': 'hsl(var(--muted))',
        pill: 'hsl(var(--primary-foreground))',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic':
          'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      colors: {
        navbar: 'hsl(var(--secondary))',
        normal: 'hsl(var(--foreground))',
        'card-border': 'hsl(var(--border))',
        'sample-expanded': 'hsl(var(--accent))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        chart: {
          '1': 'hsl(var(--chart-1))',
          '2': 'hsl(var(--chart-2))',
          '3': 'hsl(var(--chart-3))',
          '4': 'hsl(var(--chart-4))',
          '5': 'hsl(var(--chart-5))',
        },
        'blue-bg': 'hsl(var(--blue))',
        'blue-border': 'hsl(var(--blue-border))',
        'blue-text': 'hsl(var(--blue-text))',
        'blue-muted': 'hsl(var(--blue-muted))',

        'orange-bg': 'hsl(var(--orange))',
        'orange-border': 'hsl(var(--orange-border))',
        'orange-text': 'hsl(var(--orange-text))',

        'green-bg': 'hsl(var(--green))',
        'green-border': 'hsl(var(--green-border))',
        'green-text': 'hsl(var(--green-text))',
        'green-muted': 'hsl(var(--green-muted))',

        'yellow-bg': 'hsl(var(--yellow))',
        'yellow-border': 'hsl(var(--yellow-border))',
        'yellow-text': 'hsl(var(--yellow-text))',
        'yellow-muted': 'hsl(var(--yellow-muted))',

        'red-bg': 'hsl(var(--red))',
        'red-border': 'hsl(var(--red-border))',
        'red-text': 'hsl(var(--red-text))',
        'red-muted': 'hsl(var(--red-muted))',

        'indigo-bg': 'hsl(var(--indigo))',
        'indigo-border': 'hsl(var(--indigo-border))',
        'indigo-text': 'hsl(var(--indigo-text))',
        'indigo-muted': 'hsl(var(--indigo-muted))',

        'purple-bg': 'hsl(var(--purple))',
        'purple-border': 'hsl(var(--purple-border))',
        'purple-text': 'hsl(var(--purple-text))',
      },
      fontSize: {
        '3xs': '0.5rem',
        '2xs': '0.625rem',
        xxs: ['0.625rem', { lineHeight: '0.875rem' }], // This is equivalent to 10px with a line-height of 14px
        // xs: ['0.825rem', { lineHeight: '1.1rem' }], // Custom text-sm definition (changed from default 0.875rem)
      },
      transitionDuration: {
        '1500': '1500ms',
      },
    },
  },
  plugins: [require('tailwindcss-animate'), require('@tailwindcss/typography')],
  safelist: [
    // These colors are dynamically generated in AgentRunViewer.tsx, so we have to tell tailwind to include them
    {
      pattern: /(bg|border)-(blue|gray|green|orange)-(bg|border|text)/,
    },
  ],
};
export default config;
