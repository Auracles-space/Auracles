const fs = require('fs');
const path = require('path');

const target = path.join(__dirname, 'src/components/modules/attestation/attestation-workspaces.tsx');
let content = fs.readFileSync(target, 'utf8');

// Replace imports
content = content.replace(
  'import { Button } from "@/components/ui/button";',
  'import { Button } from "@/components/ui/button";\nimport { Input } from "@/components/ui/input";\nimport { Textarea } from "@/components/ui/textarea";\nimport { Select } from "@/components/ui/select";'
);

// We'll just replace the tag names. It will keep the classNames which will merge with the component defaults.
// This is safest to preserve behavior.
content = content.replace(/<input /g, '<Input ');
content = content.replace(/<\/input>/g, '</Input>');
content = content.replace(/<textarea /g, '<Textarea ');
content = content.replace(/<\/textarea>/g, '</Textarea>');
content = content.replace(/<select /g, '<Select ');
content = content.replace(/<\/select>/g, '</Select>');

// Let's remove the massive hardcoded classes from inputs that match what Input provides to avoid visual clutter
const inputRegex = /className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"/g;
content = content.replace(inputRegex, '');

const textareaRegex = /className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"/g;
content = content.replace(textareaRegex, '');

const textarea2Regex = /className="min-h-28 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"/g;
content = content.replace(textarea2Regex, 'className="min-h-28"');

fs.writeFileSync(target, content);
console.log('Done');
