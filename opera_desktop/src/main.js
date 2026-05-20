const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs-extra');
const { spawn } = require('child_process');
let mw, py = null, folders = [], queue = [], history = [], mem = {workflows:[],patterns:[]};
const MP = path.join(app.getPath('userData'),'memory.json'), HP = path.join(app.getPath('userData'),'history.json');
function load(){try{if(fs.existsSync(MP))mem=JSON.parse(fs.readFileSync(MP,'utf8'));if(fs.existsSync(HP))history=JSON.parse(fs.readFileSync(HP,'utf8'));}catch(e){}}
function save(){fs.writeFileSync(MP,JSON.stringify(mem,null,2));fs.writeFileSync(HP,JSON.stringify(history.slice(-100),null,2));}
function s(ch,d){if(mw&&!mw.isDestroyed())mw.webContents.send(ch,d);}
function cw(){mw=new BrowserWindow({width:1280,height:820,minWidth:900,minHeight:600,webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false},titleBarStyle:'hiddenInset',backgroundColor:'#f6f5f1',show:false});mw.loadFile(path.join(__dirname,'..','renderer','index.html'));mw.once('ready-to-show',()=>mw.show());}
ipcMain.handle('select-folder',async()=>{const r=await dialog.showOpenDialog(mw,{properties:['openDirectory']});if(!r.canceled&&r.filePaths[0]){folders.push(r.filePaths[0]);return r.filePaths[0];}return null;});
ipcMain.handle('read-file',async(_,fp)=>{if(!folders.some(f=>fp.startsWith(f)))return{error:'Access denied'};try{const st=await fs.stat(fp);if(st.size>1048576)return{error:'File too large'};return{content:await fs.readFile(fp,'utf8'),name:path.basename(fp),size:st.size};}catch(e){return{error:e.message};}});
ipcMain.handle('delete-file',async(_,fp)=>{if(!folders.some(f=>fp.startsWith(f)))return{error:'Access denied'};const r=await dialog.showMessageBox(mw,{type:'warning',buttons:['Cancel','Delete'],defaultId:0,title:'Confirm Deletion',message:'Delete this file?',detail:fp});if(r.response===1){await fs.remove(fp);return{ok:true};}return{ok:false,reason:'cancelled'};});
ipcMain.handle('submit-task',async(_,{prompt,type})=>{const t={id:Date.now().toString(36),prompt,type:type||'general',status:'pending',created:Date.now(),result:null};queue.push(t);s('task-update',t);processTask();return t;});
ipcMain.handle('get-tasks',()=>history.slice(-50));
ipcMain.handle('get-memory',()=>mem);
ipcMain.handle('save-memory',async(_,d)=>{mem={...mem,...d};save();return{ok:true};});
ipcMain.handle('start-engine',async()=>{if(py)return{status:'running',pid:py.pid};const ep=path.join(process.resourcesPath||__dirname,'..','..','opera_engine','executor.py');if(fs.existsSync(ep)){py=spawn('python3',[ep],{stdio:['pipe','pipe','pipe'],env:{...process.env}});py.stdout.on('data',d=>s('engine-log',d.toString()));py.stderr.on('data',d=>s('engine-error',d.toString()));py.on('exit',(code)=>{py=null;mem.stats.engineRestarts+=1;s('engine-status','stopped');if(code!==0&&code!==null){setTimeout(()=>{ipcMain.emit('start-engine')},2000);}});s('engine-status','running');return{status:'started',pid:py.pid};}return{status:'not-found'};});
ipcMain.handle('stop-engine',()=>{if(py){py.kill();py=null;s('engine-status','stopped');}return{ok:true};});
ipcMain.handle('request-approval',async(_,{action,detail})=>{const r=await dialog.showMessageBox(mw,{type:'warning',buttons:['Deny','Approve'],defaultId:0,title:'Approval: '+action,message:action,detail});return{approved:r.response===1};});
async function processTask(){const p=queue.find(t=>t.status==='pending');if(!p||py)return;p.status='processing';s('task-update',p);setTimeout(()=>{p.status='done';p.result='Processed: '+p.prompt;history.push(p);mem.stats.tasksCompleted+=1;save();s('task-update',p);processTask();},1000);}
app.whenReady().then(()=>{load();mem.stats.startupTime=Date.now();cw();});
app.on('window-all-closed',()=>{if(py)py.kill();save();app.quit();});
