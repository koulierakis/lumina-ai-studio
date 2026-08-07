import fs from 'fs';
import path from 'path';

describe('StudioLayout document scrolling', () => {
  test('uses intrinsic page height and visible overflow throughout the route shell', () => {
    const layout = fs.readFileSync(path.join(__dirname, 'StudioLayout.jsx'), 'utf8');
    const sidebar = fs.readFileSync(path.join(__dirname, 'Sidebar.jsx'), 'utf8');
    const layoutClasses = [...layout.matchAll(/className="([^"]*)"/g)]
      .flatMap((match) => match[1].split(/\s+/));
    const sidebarClass = sidebar.match(/<aside className="([^"]*)"/)?.[1].split(/\s+/) || [];

    expect(layout).toContain('min-h-screen w-full overflow-visible');
    expect(layout).toContain('!h-auto min-h-screen w-full !overflow-visible');
    expect(layout).toContain('<main className="min-h-screen w-full overflow-visible">');
    expect(layoutClasses).not.toContain('h-screen');
    expect(layoutClasses).not.toContain('h-full');
    expect(layoutClasses).not.toContain('overflow-hidden');
    expect(sidebar).toContain('<aside className="min-h-screen');
    expect(sidebarClass).not.toContain('h-full');
  });
});
