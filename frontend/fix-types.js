const fs = require('fs');
const path = require('path');

function replaceInFile(filePath, search, replacement) {
  let content = fs.readFileSync(filePath, 'utf8');
  content = content.replace(search, replacement);
  fs.writeFileSync(filePath, content);
}

// 1. src/app/(auth)/dashboard/organizations/page.tsx
// wait, the error is in src/components/modules/organizations/organization-shell.tsx
let shellPath = path.join(__dirname, 'src/components/modules/organizations/organization-shell.tsx');
let shellContent = fs.readFileSync(shellPath, 'utf8');
shellContent = shellContent.replace(/getMyOrganizationsV1OrgsMineGet/g, 'listMyOrganizationsV1OrgsMineGet');
shellContent = shellContent.replace(/o =>/g, '(o: any) =>');
fs.writeFileSync(shellPath, shellContent);

// 2. src/app/(public)/orgs/[slug]/page.tsx
let publicOrgPath = path.join(__dirname, 'src/app/(public)/orgs/[slug]/page.tsx');
let publicOrgContent = fs.readFileSync(publicOrgPath, 'utf8');
publicOrgContent = publicOrgContent.replace(/\(cap\) =>/g, '(cap: string) =>');
fs.writeFileSync(publicOrgPath, publicOrgContent);

// 3. Button variants across files
const filesWithOutline = [
  'src/components/modules/organizations/admin-organizations-list.tsx',
  'src/components/modules/organizations/invitation-accept.tsx',
  'src/components/modules/organizations/organization-invitations.tsx',
  'src/components/modules/organizations/organization-teams.tsx'
];

filesWithOutline.forEach(f => {
  let fp = path.join(__dirname, f);
  let content = fs.readFileSync(fp, 'utf8');
  content = content.replace(/variant="outline"/g, 'variant="secondary"');
  fs.writeFileSync(fp, content);
});

// 4. src/components/modules/organizations/invitation-accept.tsx previewInvitation...
let invAcceptPath = path.join(__dirname, 'src/components/modules/organizations/invitation-accept.tsx');
let invAcceptContent = fs.readFileSync(invAcceptPath, 'utf8');
invAcceptContent = invAcceptContent.replace(/previewInvitationV1OrgInvitationsTokenGetData/g, 'previewInvitationV1OrgInvitationsTokenGet');
fs.writeFileSync(invAcceptPath, invAcceptContent);

// 5. src/components/modules/organizations/organization-danger-zone.tsx
let dangerPath = path.join(__dirname, 'src/components/modules/organizations/organization-danger-zone.tsx');
let dangerContent = fs.readFileSync(dangerPath, 'utf8');
dangerContent = dangerContent.replace(/\(m\) =>/g, '(m: any) =>');
dangerContent = dangerContent.replace(/variant="default"/g, 'variant="primary"');
fs.writeFileSync(dangerPath, dangerContent);

console.log('Fixes applied');
