import { NavLink } from 'react-router-dom';
import { useTheme } from '../hooks/useTheme';

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/agents', label: 'Agents' },
  { to: '/tickets', label: 'Tickets' },
  { to: '/messages', label: 'Messages' },
  { to: '/feedback', label: 'Feedback' },
];

export default function Sidebar({ collapsed, onToggle }: { collapsed?: boolean; onToggle?: () => void }) {
  const { theme, setTheme } = useTheme();

  return (
    <>
      {/* Mobile overlay */}
      {!collapsed && onToggle && (
        <div className="fixed inset-0 bg-black/40 z-30 lg:hidden" onClick={onToggle} />
      )}
      <aside className={`
        ${collapsed ? '-translate-x-full' : 'translate-x-0'}
        fixed lg:static inset-y-0 left-0 z-40
        w-56 bg-gray-900 text-gray-300 flex flex-col min-h-screen
        transition-transform duration-200 ease-in-out lg:translate-x-0
      `}>
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <h1 className="text-lg font-bold text-white">Agent Hub</h1>
          {onToggle && (
            <button onClick={onToggle} className="lg:hidden text-gray-400 hover:text-white">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
        <nav className="flex-1 p-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={onToggle}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm ${
                  isActive
                    ? 'bg-gray-700 text-white'
                    : 'hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        {/* Theme toggle */}
        <div className="p-3 border-t border-gray-700">
          <div className="flex items-center gap-1 bg-gray-800 rounded p-0.5">
            {(['light', 'system', 'dark'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTheme(t)}
                className={`flex-1 px-2 py-1 rounded text-xs capitalize ${
                  theme === t ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                {t === 'light' ? '\u2600' : t === 'dark' ? '\u263E' : '\u2699'} {t}
              </button>
            ))}
          </div>
        </div>
      </aside>
    </>
  );
}
