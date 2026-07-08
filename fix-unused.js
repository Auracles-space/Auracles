const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, 'frontend/src/components/modules');

function walk(dir, callback) {
  fs.readdirSync(dir).forEach(f => {
    let dirPath = path.join(dir, f);
    let isDirectory = fs.statSync(dirPath).isDirectory();
    isDirectory ? 
      walk(dirPath, callback) : callback(path.join(dir, f));
  });
}

walk(dir, function(filePath) {
  if (filePath.endsWith('.tsx') || filePath.endsWith('.ts')) {
    let content = fs.readFileSync(filePath, 'utf8');
    let changed = false;
    
    if (content.includes('catch (err) {')) {
      content = content.replace(/catch \(err\) \{/g, 'catch (_err) {');
      changed = true;
    }

    if (content.includes('catch (e) {')) {
      content = content.replace(/catch \(e\) \{/g, 'catch (_e) {');
      changed = true;
    }
    
    if (changed) {
      fs.writeFileSync(filePath, content, 'utf8');
      console.log('Fixed', filePath);
    }
  }
});
