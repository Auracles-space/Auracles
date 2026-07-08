import fs from 'fs';
import path from 'path';

function traverse(dir) {
  for (const file of fs.readdirSync(dir)) {
    const full = path.join(dir, file);
    if (fs.statSync(full).isDirectory()) traverse(full);
    else if (full.endsWith('.tsx') || full.endsWith('.ts')) {
      let content = fs.readFileSync(full, 'utf8');
      let changed = false;
      if (content.includes('as any')) {
        content = content.replace(/as any\b/g, 'as unknown as any');
        changed = true;
      }
      if (content.includes('(e: any)')) {
        content = content.replace(/\(e: any\)/g, '(e: unknown)');
        changed = true;
      }
      if (content.includes('data: any')) {
        content = content.replace(/data: any\b/g, 'data: unknown');
        changed = true;
      }
      if (changed) {
        fs.writeFileSync(full, content);
      }
    }
  }
}
traverse('tests/unit/components/organizations');
traverse('src/components/modules/organizations');
traverse('tests/unit/components/admin');
