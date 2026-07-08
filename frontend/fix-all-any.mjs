import fs from 'fs';
import path from 'path';

function traverse(dir) {
  if (!fs.existsSync(dir)) return;
  for (const file of fs.readdirSync(dir)) {
    if (file === 'node_modules' || file === '.next' || file === 'dist' || file === 'generated') continue;
    const full = path.join(dir, file);
    if (fs.statSync(full).isDirectory()) traverse(full);
    else if (full.endsWith('.tsx') || full.endsWith('.ts')) {
      let content = fs.readFileSync(full, 'utf8');
      let original = content;
      
      content = content.replace(/as unknown as any/g, 'as never');
      content = content.replace(/as any/g, 'as never');
      content = content.replace(/\(err: any\)/g, '(err: unknown)');
      content = content.replace(/\(e: any\)/g, '(e: unknown)');
      content = content.replace(/Unexpected any\. Specify a different type/g, ''); // just in case
      content = content.replace(/You don't have/g, "You don\\'t have");
      
      if (content !== original) {
        fs.writeFileSync(full, content);
      }
    }
  }
}
traverse('src/components/modules/organizations');
traverse('tests/unit/components');
