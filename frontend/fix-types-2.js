const fs = require('fs');
const path = require('path');

let adminList = path.join(__dirname, 'src/components/modules/organizations/admin-organizations-list.tsx');
let adminListContent = fs.readFileSync(adminList, 'utf8');
adminListContent = adminListContent.replace(/size="sm"\n/g, '');
adminListContent = adminListContent.replace(/ size="sm"/g, '');
fs.writeFileSync(adminList, adminListContent);

let invAccept = path.join(__dirname, 'src/components/modules/organizations/invitation-accept.tsx');
let invAcceptContent = fs.readFileSync(invAccept, 'utf8');
invAcceptContent = invAcceptContent.replace(/<Button asChild variant="secondary" className="w-full">/g, '<a className="inline-flex h-10 items-center justify-center rounded-xl bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-3 w-full">');
invAcceptContent = invAcceptContent.replace(/<\/Button>/g, '</a>'); // this might replace all Buttons, let me check.

// Better replacement for invAccept
invAcceptContent = fs.readFileSync(invAccept, 'utf8'); // reset
invAcceptContent = invAcceptContent.replace(
  /<Button asChild variant="secondary" className="w-full">\s*<Link href="\/login\?next=\/org-invitations\/\[token\]" as={`\/login\?next=\/org-invitations\/\${token}`}>\s*Log in to accept\s*<\/Link>\s*<\/Button>/g,
  '<Link href="/login?next=/org-invitations/[token]" as={`/login?next=/org-invitations/${token}`} className="inline-flex h-10 items-center justify-center rounded-xl bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-3 w-full">Log in to accept</Link>'
);
invAcceptContent = invAcceptContent.replace(
  /<Button asChild variant="secondary" className="w-full mt-2">\s*<Link href="\/register\?next=\/org-invitations\/\[token\]" as={`\/register\?next=\/org-invitations\/\${token}`}>\s*Create an account\s*<\/Link>\s*<\/Button>/g,
  '<Link href="/register?next=/org-invitations/[token]" as={`/register?next=/org-invitations/${token}`} className="inline-flex h-10 items-center justify-center rounded-xl bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-3 w-full mt-2">Create an account</Link>'
);
fs.writeFileSync(invAccept, invAcceptContent);

let shell = path.join(__dirname, 'src/components/modules/organizations/organization-shell.tsx');
let shellContent = fs.readFileSync(shell, 'utf8');
shellContent = shellContent.replace(/o =>/g, '(o: any) =>');
// To be safe, if we already replaced it to (o: any) => we don't need to do it again, but if it was something else, let's fix it.
shellContent = shellContent.replace(/\(\(o: any\) =>/g, '(o: any) =>'); // just in case
fs.writeFileSync(shell, shellContent);
